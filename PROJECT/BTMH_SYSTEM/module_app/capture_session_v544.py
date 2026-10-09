"""Bounded, latest-frame IPC around one isolated camera decoder.

No native decoder runs inside the HTTP process. A hanging RTSP/USB open/read can
be killed independently. URLs/credentials are sent via stdin, never command line;
native stderr is classified in memory and never copied into API/support logs.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, unquote, urlunsplit
from .rtsp_native_v545 import resolve_ffmpeg, command as ffmpeg_command, input_manifest, read_ppm
import atexit
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import uuid
import weakref
import numpy as np

HEADER = struct.Struct("!4sII")
MAX_FRAME = 4096 * 2160 * 3
_LIVE: weakref.WeakSet = weakref.WeakSet()
# Failed retirement must retain a strong owner even if a caller drops its handle.
_RETIRE_PENDING: set[CaptureSession] = set()

ERRORS = {
    'DECODER_RETIRE_FAILED': 'Camera decoder has not exited; retain ownership and retry retirement before opening a replacement.',
    'DECODER_UNAVAILABLE': 'Không tìm thấy bộ đọc RTSP cục bộ. Chạy lại Cài đặt lần đầu trong đúng tài khoản Windows.',
    'DECODER_OPTIONS': 'Bộ đọc RTSP không hỗ trợ tùy chọn cần thiết. Cần kiểm tra runtime; không đổi camera.',
    'NO_VIDEO_STREAM': 'Kết nối không cung cấp luồng video. Kiểm tra đường dẫn kênh camera.',
    'DECODER_PROTOCOL': 'Bộ đọc trả dữ liệu hình ảnh không hợp lệ.',
    'FRAME_TOO_LARGE': 'Độ phân giải camera vượt giới hạn 4096 x 2160 của bộ đọc này.',
    'CAMERA_BUSY': 'Camera không chấp nhận thêm phiên xem. Đóng phiên xem thử rồi kiểm tra lại.',
    "INVALID_SOURCE": "Ngu\u1ed3n camera kh\u00f4ng h\u1ee3p l\u1ec7. Ki\u1ec3m tra IP, c\u1ed5ng v\u00e0 \u0111\u01b0\u1eddng d\u1eabn.",
    "MASKED_CREDENTIALS": "Camera \u0111ang l\u01b0u m\u1eadt kh\u1ea9u \u0111\u00e3 che. H\u00e3y nh\u1eadp l\u1ea1i t\u00e0i kho\u1ea3n camera trong S\u1eeda k\u1ebft n\u1ed1i.",
    "AUTH_FAILED": "Camera t\u1eeb ch\u1ed1i x\u00e1c th\u1ef1c RTSP. Ki\u1ec3m tra t\u00e0i kho\u1ea3n, m\u1eadt kh\u1ea9u v\u00e0 quy\u1ec1n xem h\u00ecnh.",
    "PATH_NOT_FOUND": "Camera kh\u00f4ng t\u00ecm th\u1ea5y lu\u1ed3ng video. Ki\u1ec3m tra \u0111\u01b0\u1eddng d\u1eabn RTSP.",
    "CONNECTION_REFUSED": "Camera t\u1eeb ch\u1ed1i k\u1ebft n\u1ed1i. Ki\u1ec3m tra IP v\u00e0 c\u1ed5ng RTSP.",
    "UNREACHABLE": "Kh\u00f4ng k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c camera qua m\u1ea1ng. Ki\u1ec3m tra IP v\u00e0 \u0111\u01b0\u1eddng truy\u1ec1n.",
    "CODEC_UNSUPPORTED": "B\u1ed9 gi\u1ea3i m\u00e3 kh\u00f4ng \u0111\u1ecdc \u0111\u01b0\u1ee3c video. Ki\u1ec3m tra codec v\u00e0 c\u1ea5u h\u00ecnh lu\u1ed3ng camera.",
    "OPEN_FAILED": "Kh\u00f4ng m\u1edf \u0111\u01b0\u1ee3c lu\u1ed3ng camera. Ki\u1ec3m tra IP, t\u00e0i kho\u1ea3n, \u0111\u01b0\u1eddng d\u1eabn v\u00e0 gi\u1edbi h\u1ea1n k\u1ebft n\u1ed1i.",
    "READ_FAILED": "\u0110\u00e3 m\u1edf lu\u1ed3ng nh\u01b0ng kh\u00f4ng nh\u1eadn \u0111\u01b0\u1ee3c h\u00ecnh \u1ea3nh li\u00ean ti\u1ebfp.",
    "TIMEOUT": "H\u1ebft th\u1eddi gian ch\u1edd h\u00ecnh t\u1eeb camera. Camera hi\u1ec7n t\u1ea1i kh\u00f4ng b\u1ecb d\u1eebng do l\u1ed7i n\u00e0y.",
    "COMMIT_FAILED": "Ch\u01b0a ho\u00e0n t\u1ea5t \u0111\u1ed5i ngu\u1ed3n. Camera c\u0169 \u0111\u01b0\u1ee3c gi\u1eef l\u1ea1i; h\u00e3y th\u1eed l\u1ea1i.",
    "START_FAILED": "Kh\u00f4ng kh\u1edfi \u0111\u1ed9ng \u0111\u01b0\u1ee3c b\u1ed9 \u0111\u1ecdc camera.",
    "DECODER_EXITED": "B\u1ed9 \u0111\u1ecdc camera \u0111\u00e3 d\u1eebng tr\u01b0\u1edbc khi nh\u1eadn \u0111\u1ee7 h\u00ecnh \u1ea3nh.",
    "CANCELLED": "\u0110\u00e3 h\u1ee7y ki\u1ec3m tra camera.",
    "BUSY": "\u0110ang ki\u1ec3m tra ho\u1eb7c chuy\u1ec3n camera kh\u00e1c. Vui l\u00f2ng ch\u1edd.",
    "AI_BUSY": "Nh\u1eadn di\u1ec7n \u0111ang ho\u00e0n t\u1ea5t khung h\u00ecnh. Ch\u01b0a \u0111\u1ed5i ngu\u1ed3n; h\u00e3y th\u1eed l\u1ea1i.",
}


def valid_source(source: str) -> str:
    value = str(source).strip()
    if value.isdigit() and 0 <= int(value) < 100:
        return value
    if len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("INVALID_SOURCE")
    try:
        p = urlsplit(value)
        if p.scheme.lower() not in {"rtsp", "http", "https"} or not p.hostname or p.fragment:
            raise ValueError("INVALID_SOURCE")
        if p.port is not None and not 0 < p.port <= 65535:
            raise ValueError("INVALID_SOURCE")
        if unquote(p.password or "").strip() in {"***", "********", "<password>"} or unquote(p.username or "").strip() == "***":
            raise ValueError("MASKED_CREDENTIALS")
    except ValueError as exc:
        raise ValueError(str(exc) if str(exc) == "MASKED_CREDENTIALS" else "INVALID_SOURCE") from None
    return value


def display_source(value: str) -> str:
    if str(value).isdigit():
        return "USB " + str(value)
    try:
        p = urlsplit(value)
        # Diagnostics expose host/path, not credentials or secret query arguments.
        return urlunsplit((p.scheme, p.netloc.rsplit("@", 1)[-1], p.path, "", ""))
    except Exception:
        return "Camera"


def classify_diagnostic(text: str) -> str | None:
    t = str(text).lower()
    if re.search(r"(?:failed[^\n]*401|401 unauthorized|failed[^\n]*403|403 forbidden)", t): return "AUTH_FAILED"
    if "unrecognized option" in t or "option not found" in t or "unsupported parameters" in t: return "DECODER_OPTIONS"
    if "protocol not found" in t: return "DECODER_UNAVAILABLE"
    if "matches no streams" in t or "does not contain any stream" in t: return "NO_VIDEO_STREAM"
    if "453 not enough bandwidth" in t or "failed: 453" in t or "503 service unavailable" in t: return "CAMERA_BUSY"
    if "connection timed out" in t or "operation timed out" in t: return "TIMEOUT"
    if "404 not found" in t or "failed: 404" in t: return "PATH_NOT_FOUND"
    if "connection refused" in t: return "CONNECTION_REFUSED"
    if "network is unreachable" in t or "no route to host" in t or "failed to resolve" in t: return "UNREACHABLE"
    if "decoder not found" in t or "could not find decoder" in t or "unsupported codec" in t: return "CODEC_UNSUPPORTED"
    return None


@dataclass(frozen=True)
class FramePacket:
    frame: Any
    seq: int
    at: float


class CaptureRetirementError(RuntimeError):
    """A stop request did not prove that the decoder child exited."""

    def __init__(self) -> None:
        super().__init__("DECODER_RETIRE_FAILED")


class CaptureSession:
    def __init__(self, source: str, *, plans: list[dict] | None = None,
                 open_timeout_ms: int = 8000, read_timeout_ms: int = 3000,
                 autofocus: bool = True, auto_exposure: bool = True, output_fps: float = 0.,
                 output_max_width: int = 0, decoder: str | None = None) -> None:
        self.source = valid_source(source)
        self.config = dict(source=self.source, plans=plans, open_timeout_ms=open_timeout_ms,
                           read_timeout_ms=read_timeout_ms, transport="tcp", autofocus=autofocus,
                           auto_exposure=auto_exposure, output_fps=output_fps, output_max_width=output_max_width)
        self.decoder = str(decoder or os.getenv("BTMH_RTSP_READER", "auto")).lower()
        if self.decoder not in {"auto", "ffmpeg", "opencv"}:
            raise ValueError("INVALID_SOURCE")
        self._native = False
        self._native_done = threading.Event()
        self._stage = "starting"
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self._lifecycle = threading.RLock()
        self._writer = threading.Lock()
        self.process = None
        self.threads = []
        self._latest = FramePacket(None, 0, 0.0)
        self._closed = False
        self._streak = 0
        self._first_at = 0.0
        self._properties: dict[str, float] = {}
        self._metadata: dict[str, Any] = {}
        self._code = ""
        self._native_code = ""
        self._requests: dict[str, dict] = {}
        self.started_at = time.perf_counter()
        _LIVE.add(self)

    def start(self) -> None:
        with self._lifecycle:
            if self._closed or self.process is not None:
                return
            worker = Path(__file__).with_name("capture_worker_v544.py")
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
            native = resolve_ffmpeg() if self.source.lower().startswith("rtsp://") and self.decoder != "opencv" else None
            if self.source.lower().startswith("rtsp://") and self.decoder == "ffmpeg" and not native:
                self._code = "DECODER_UNAVAILABLE"
                self._native_done.set()
                return
            self._native = bool(native)
            args = ffmpeg_command(native, self.config["output_fps"], self.config["output_max_width"]) if native else [sys.executable, "-u", str(worker)]
            try:
                self.process = subprocess.Popen(args, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=env, **kwargs)
            except OSError:
                if not native or self.decoder != "auto":
                    raise
                # A broken/missing executable has not contacted the camera. Safe
                # to retain the old OpenCV path; do not retry authentication here.
                native = None
                self._native = False
                self.process = subprocess.Popen([sys.executable, "-u", str(worker)], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=env, **kwargs)
            self._stage = "opening"
            self.threads = [threading.Thread(target=self._read_native_frames if native else self._read_packets,
                                             name="btmh-decoder-reader", daemon=True),
                            threading.Thread(target=self._read_diagnostics, name="btmh-decoder-status", daemon=True)]
            for t in self.threads: t.start()
            if native:
                self._metadata = {"backend":"ffmpeg-native", "transport":"tcp"}
                # EOF terminates the private, single-source manifest. No secret file.
                data = input_manifest(self.source, self.config["open_timeout_ms"])
                with self._writer:
                    view = memoryview(data)
                    while view:
                        n = self.process.stdin.write(view)
                        if not n: raise BrokenPipeError
                        view = view[n:]
                    self.process.stdin.close()
            else:
                self._send(self.config)

    def _read_native_frames(self) -> None:
        try:
            pipe = self.process.stdout
            while not self._closed:
                w, h, rgb = read_ppm(pipe, self._read_exact)
                image = np.frombuffer(rgb, dtype=np.uint8).reshape(h, w, 3)[:, :, ::-1].copy()
                image.setflags(write=False)
                now = time.perf_counter()
                with self.changed:
                    if self._latest.at and now - self._latest.at > 1.5:
                        self._streak = 0
                    self._streak += 1
                    if not self._first_at: self._first_at = now
                    self._latest = FramePacket(image, self._latest.seq + 1, now)
                    self._stage = "receiving_frames"
                    self._code = ""
                    self._metadata.update(width=w, height=h)
                    self.changed.notify_all()
        except (EOFError, OSError, ValueError, KeyError, TypeError) as exc:
            with self.changed:
                if not self._closed and not self._code:
                    specific = str(exc)
                    self._code = specific if specific in ERRORS else ("READ_FAILED" if self._streak else "OPEN_FAILED")
                self.changed.notify_all()

    def _send(self, data: dict) -> bool:
        if self._native: return False  # RTSP control is not a USB property command.
        try:
            with self._writer:
                if self._closed or self.process is None or self.process.stdin is None:
                    return False
                raw = (json.dumps(data) + "\n").encode("utf-8")
                # FileIO.write may be partial for large payloads.
                view = memoryview(raw)
                while view:
                    n = self.process.stdin.write(view)
                    if not n: return False
                    view = view[n:]
                return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    @staticmethod
    def _read_exact(pipe, n: int) -> bytes:
        out = bytearray(n)
        view = memoryview(out)
        total = 0
        while total < n:
            got = pipe.readinto(view[total:])
            if not got:
                raise EOFError
            total += got
        return bytes(out)

    def _read_packets(self) -> None:
        try:
            pipe = self.process.stdout
            while not self._closed:
                magic, jlen, flen = HEADER.unpack(self._read_exact(pipe, HEADER.size))
                if magic != b"BTM4" or not 0 < jlen <= 32768 or flen > MAX_FRAME:
                    raise ValueError("invalid frame protocol")
                meta = json.loads(self._read_exact(pipe, jlen))
                data = self._read_exact(pipe, flen) if flen else None
                kind = meta.get("type")
                with self.changed:
                    if kind == "frame":
                        shape = meta.get("shape")
                        if not isinstance(shape, list) or len(shape) != 3 or shape[2] != 3 or any(not isinstance(x, int) or x < 1 for x in shape) or int(np.prod(shape)) != flen:
                            raise ValueError("invalid frame shape")
                        now = time.perf_counter()
                        at = float(meta.get("at") or now)
                        if not now - 60 <= at <= now: at = now
                        if self._latest.at and at - self._latest.at > 1.5:
                            self._streak = 0
                        self._streak += 1
                        if not self._first_at: self._first_at = at
                        self._latest = FramePacket(np.frombuffer(data, dtype=np.uint8).reshape(shape), int(meta["seq"]), at)
                        self._code = ""
                    elif kind == "opened":
                        self._metadata = {k:v for k,v in meta.items() if k in {"backend","plan","width","height","transport"}}
                        self._properties = meta.get("properties") or {}
                        self._stage = "receiving_frames"
                    elif kind == "control":
                        self._properties = meta.get("properties") or self._properties
                        pending = self._requests.get(str(meta.get("id")))
                        if pending:
                            pending["ok"] = bool(meta.get("ok")); pending["event"].set()
                    elif kind == "error":
                        self._code = meta.get("code") if meta.get("code") in ERRORS else "OPEN_FAILED"
                    self.changed.notify_all()
        except (EOFError, OSError, ValueError, KeyError, TypeError, struct.error):
            with self.changed:
                if not self._closed and not self._code: self._code = "DECODER_EXITED"
                self.changed.notify_all()

    def _read_diagnostics(self) -> None:
        # Native libraries may include the entire URL/password. Keep ONLY a known
        # error category, never stderr bytes or arbitrary native text.
        try:
            pipe = self.process.stderr
            while not self._closed:
                line = pipe.readline(4096)
                if not line: return
                code = classify_diagnostic(line.decode("utf-8", errors="replace"))
                if code:
                    with self.lock: self._native_code = code
        except (OSError, ValueError):
            return
        finally:
            self._native_done.set()

    def snapshot(self) -> FramePacket:
        with self.lock: return self._latest

    def alive(self) -> bool:
        # A stop request is not evidence of child exit. Owners use this proof to
        # avoid replacing a decoder which still holds the camera connection.
        return self.process is not None and not self.retired()

    def retired(self) -> bool:
        process = self.process
        if process is None:
            return True
        try:
            return process.poll() is not None
        except (OSError, ValueError):
            return False  # No reliable exit proof; retain ownership.

    def healthy(self, max_age: float = 1.5) -> bool:
        with self.lock:
            return not self._closed and self.alive() and not self._code and self._latest.frame is not None and time.perf_counter() - self._latest.at <= max_age

    def diagnostics(self, code: str | None = None) -> dict:
        with self.lock:
            selected = code or self._native_code or self._code or "OPEN_FAILED"
            if code == "TIMEOUT" and self._native_code in {"AUTH_FAILED", "PATH_NOT_FOUND", "CONNECTION_REFUSED", "UNREACHABLE", "CAMERA_BUSY"}:
                selected = self._native_code
            p = self._latest
            span = max(.001, p.at - self._first_at) if p.at else 0
            return {"code": selected, "message": ERRORS.get(selected, ERRORS["OPEN_FAILED"]),
                    "stage": self._stage, "reader": "native" if self._native else "opencv",
                    "credential_supplied": bool(urlsplit(self.source).username) if not self.source.isdigit() else False,
                    "source_display": display_source(self.source), "backend": self._metadata.get("backend", ""),
                    "transport": self._metadata.get("transport", "tcp" if self.source.lower().startswith("rtsp://") else "usb"),
                    "stable_frames": self._streak, "width": int(p.frame.shape[1]) if p.frame is not None else 0,
                    "height": int(p.frame.shape[0]) if p.frame is not None else 0,
                    "observed_fps": round(max(0, p.seq - 1) / span, 1) if span else 0,
                    "decoder_output_fps": float(self.config.get("output_fps") or 0.0),
                    "decoder_max_width": int(self.config.get("output_max_width") or 0),
                    "elapsed_ms": round((time.perf_counter() - self.started_at) * 1000),
                    "frame_age_ms": round((time.perf_counter() - p.at) * 1000) if p.at else None}

    def wait_ready(self, frames: int = 5, timeout: float = 16.0, cancelled=None) -> dict:
        deadline = time.perf_counter() + max(.05, timeout)
        with self.changed:
            while True:
                if self._closed or (cancelled and cancelled()):
                    return {"ok":False, **self.diagnostics("CANCELLED")}
                if self._streak >= max(3, int(frames)) and self.healthy():
                    d = self.diagnostics("READY"); d["message"] = "Camera tr\u1ea3 h\u00ecnh \u1ea3nh \u1ed5n \u0111\u1ecbnh."
                    return {"ok":True, **d}
                if self._code or not self.alive():
                    # EOF on stdout can race stderr. Bound the wait but allow its
                    # classification to finish; never expose the original text.
                    if not self._native_done.is_set(): self.changed.wait(.15)
                    return {"ok":False, **self.diagnostics()}
                remain = deadline - time.perf_counter()
                if remain <= 0: return {"ok":False, **self.diagnostics("TIMEOUT")}
                self.changed.wait(min(.05, remain))

    def get(self, prop: int) -> float:
        with self.lock: return float(self._properties.get(str(prop), 0.0))

    def set(self, prop: int, value: float) -> bool:
        if not self.alive(): return False
        ident = uuid.uuid4().hex
        pending = {"event":threading.Event(), "ok":False}
        with self.lock:
            if len(self._requests) >= 8: return False
            self._requests[ident] = pending
        try:
            if not self._send({"op":"set", "prop":int(prop), "value":float(value), "id":ident}): return False
            pending["event"].wait(.55)
            return bool(pending["ok"])
        finally:
            with self.lock: self._requests.pop(ident, None)

    def metadata(self) -> dict:
        with self.lock: return dict(self._metadata)

    def close(self) -> None:
        with self._lifecycle:
            self._closed = True
            with self.changed:
                self.changed.notify_all()
            p = self.process
            if p is not None:
                if not self.retired():
                    try:
                        p.terminate()
                        p.wait(timeout=.8)
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass
                if not self.retired():
                    try:
                        p.kill()
                        p.wait(timeout=.8)
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass
                if not self.retired():
                    _RETIRE_PENDING.add(self)
                    with self.changed:
                        self._code = "DECODER_RETIRE_FAILED"
                        self._stage = "retirement_failed"
                        self.changed.notify_all()
                    # Leave pipes/process ownership intact. Retrying close is
                    # allowed even though frame delivery is already stopped.
                    raise CaptureRetirementError() from None
                for t in self.threads:
                    if t is not threading.current_thread(): t.join(timeout=.25)
                for pipe in (p.stdin, p.stdout, p.stderr):
                    try:
                        if pipe: pipe.close()
                    except (OSError, ValueError): pass
            with self.changed: self.changed.notify_all()
            _LIVE.discard(self)
            _RETIRE_PENDING.discard(self)

    release = close


def _close_all():
    for session in list(_LIVE):
        try:
            session.close()
        except CaptureRetirementError:
            # A retained failure must not prevent retirement of other children.
            continue
atexit.register(_close_all)
