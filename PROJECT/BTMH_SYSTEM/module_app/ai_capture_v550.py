"""One private AI substream decoder and a single immutable latest-frame slot.

The main camera source is never changed here. Readiness is proven with decoded
frames before the substream is exposed. A failed lane makes its main fallback
reason explicit, and retries independently without restarting video or BTMH.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from . import config as cfg
from .camera_profiles import hikvision_ai_substream, normalize_camera_source
from .capture_session_v544 import CaptureSession, ERRORS, FramePacket


@dataclass(frozen=True)
class AIFramePacket:
    frame: object
    seq: int
    at: float
    source_epoch: int


class AICaptureLane:
    """Own at most one decoder; source changes invalidate in-flight packets."""

    def __init__(self, *, session_factory=None, clock=None):
        self._factory = session_factory or CaptureSession
        self._clock = clock or time.perf_counter
        self._lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._stop = threading.Event()
        self._changed = threading.Event()
        self._thread = None
        self._session = None
        self._source = ""
        self._source_epoch = 0
        self._generation = 0
        self._frame_seq = 0
        self._latest = AIFramePacket(None, 0, 0.0, 0)
        self._state = "MAIN_FALLBACK"
        self._reason = "NOT_CONFIGURED"
        self._configured_reason = "NOT_CONFIGURED"
        self._blocked = False
        self._retire_failed = False
        self._failures = 0
        self._retry_at = 0.0
        self._reconnects = 0
        self._capture_fps = 0.0

    def configure(self, main_source: str, source_epoch: int, *, registered: bool):
        desired = hikvision_ai_substream(main_source) if registered and cfg.AI_SUBSTREAM_ENABLED else None
        reason = "SUBSTREAM_CONNECTING" if desired else (
            "SUBSTREAM_DISABLED" if not cfg.AI_SUBSTREAM_ENABLED else
            "SOURCE_NOT_REGISTERED" if not registered else "NO_KNOWN_SUBSTREAM")
        with self._lock:
            self._configured_reason = reason
            if self._source == (desired or "") and self._source_epoch == int(source_epoch):
                if not desired and not self._retire_failed and not self._stop.is_set():
                    self._reason = reason
                return
            self._source = normalize_camera_source(desired or "")
            self._source_epoch = int(source_epoch)
            self._generation += 1
            self._frame_seq = 0
            self._latest = AIFramePacket(None, 0, 0.0, self._source_epoch)
            self._state = "OPENING" if desired and not self._retire_failed else "MAIN_FALLBACK"
            self._reason = "SUBSTREAM_RETIRE_FAILED" if self._retire_failed else reason
            self._blocked = self._retire_failed
            self._failures = 0
            self._retry_at = 0.0
            self._capture_fps = 0.0
        self._changed.set()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            if not self._blocked:
                self._state = "OPENING" if self._source else "MAIN_FALLBACK"
                self._reason = self._configured_reason
            self._thread = threading.Thread(target=self._run, name="btmh-ai-substream", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._changed.set()
        with self._lock:
            self._generation += 1
            session, thread = self._session, self._thread
            self._latest = AIFramePacket(None, 0, 0.0, self._source_epoch)
            self._state = "STOPPED"
            self._reason = "SUBSTREAM_STOPPED"
        if session:
            self._retire(session)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _is_current(self, generation):
        with self._lock:
            return not self._stop.is_set() and self._generation == generation

    def _failure(self, code, generation):
        safe_code = code if code in ERRORS else "READ_FAILED"
        with self._lock:
            if not self._is_current(generation):
                return
            self._latest = AIFramePacket(None, 0, 0.0, self._source_epoch)
            self._state = "MAIN_FALLBACK"
            self._reason = "SUBSTREAM_" + safe_code
            self._failures += 1
            self._reconnects += 1
            self._blocked = safe_code in {"AUTH_FAILED", "PATH_NOT_FOUND", "MASKED_CREDENTIALS", "INVALID_SOURCE"}
            self._retry_at = self._clock() + min(30.0, 1.0 * 2 ** min(self._failures - 1, 5))
            self._capture_fps = 0.0

    def _retire(self, session) -> bool:
        """Never replace a decoder whose close did not complete successfully."""
        with self._close_lock:
            with self._lock:
                if self._session is not session:
                    # A cancelled factory can return before taking ownership.
                    owned = False
                else:
                    owned = True
            try:
                session.close()
            except Exception:
                with self._lock:
                    if not owned and self._session is None:
                        self._session = session
                    self._retire_failed = True
                    self._blocked = True
                    self._state = "STOPPED" if self._stop.is_set() else "MAIN_FALLBACK"
                    self._reason = "SUBSTREAM_RETIRE_FAILED"
                    self._latest = AIFramePacket(None, 0, 0.0, self._source_epoch)
                    self._capture_fps = 0.0
                    self._retry_at = self._clock() + 1.0
                return False
            with self._lock:
                if self._session is session:
                    self._session = None
                if self._retire_failed:
                    self._retire_failed = False
                    self._blocked = False
                    self._retry_at = 0.0
                    self._reason = "SUBSTREAM_STOPPED" if self._stop.is_set() else (
                        "SUBSTREAM_CONNECTING" if self._source else self._configured_reason)
            return True

    def snapshot(self, source_epoch: int) -> AIFramePacket | None:
        with self._lock:
            packet = self._latest
            if (self._state != "READY" or packet.frame is None or packet.source_epoch != int(source_epoch)
                    or not packet.at or not 0.0 <= self._clock() - packet.at <= cfg.AI_SUBSTREAM_MAX_AGE_SEC):
                return None
            return packet

    def status(self):
        with self._lock:
            packet = self._latest
            age = self._clock() - packet.at if packet.at else None
            ready = bool(self._state == "READY" and packet.frame is not None
                         and age is not None and 0.0 <= age <= cfg.AI_SUBSTREAM_MAX_AGE_SEC)
            return {"state": self._state if ready or self._state != "READY" else "MAIN_FALLBACK",
                    "mode": "HIKVISION_SUBSTREAM" if ready else "MAIN_FALLBACK",
                    "fallback_reason": "" if ready else ("SUBSTREAM_STALE" if self._state == "READY" else self._reason),
                    "source_epoch": self._source_epoch, "latest_seq": packet.seq,
                    "frame_age_ms": round(age * 1000, 1) if age is not None else None,
                    "capture_fps": self._capture_fps if ready else 0.0, "reconnect_count": self._reconnects,
                    "retry_blocked": self._blocked, "retry_in_sec": round(max(0.0, self._retry_at - self._clock()), 1),
                    "queue_depth": 0, "latest_slot_capacity": 1,
                    "worker_alive": bool(self._thread and self._thread.is_alive())}

    def _run(self):
        while not self._stop.is_set():
            self._changed.clear()
            with self._lock:
                pending = self._session
                retire_due = self._clock() >= self._retry_at
            if pending is not None:
                if retire_due:
                    self._retire(pending)
                else:
                    self._changed.wait(0.1)
                continue
            with self._lock:
                source, epoch, generation = self._source, self._source_epoch, self._generation
                can_open = bool(source and not self._blocked and self._clock() >= self._retry_at)
            if not can_open:
                self._changed.wait(0.1)
                continue
            session = None
            try:
                session = self._factory(source, output_fps=cfg.AI_SUBSTREAM_CAPTURE_FPS,
                                        output_max_width=cfg.RTSP_AI_WIDTH,
                                        open_timeout_ms=int(cfg.AI_SUBSTREAM_OPEN_TIMEOUT_SEC * 1000))
                with self._lock:
                    if not self._is_current(generation):
                        continue
                    self._session = session
                    self._state = "OPENING"
                    self._reason = "SUBSTREAM_CONNECTING"
                session.start()
                diagnostic = session.wait_ready(3, cfg.AI_SUBSTREAM_OPEN_TIMEOUT_SEC,
                                                 cancelled=lambda: not self._is_current(generation))
                if not self._is_current(generation):
                    continue
                if not diagnostic.get("ok"):
                    self._failure(str(diagnostic.get("code") or "OPEN_FAILED"), generation)
                    continue
                last_seq = 0
                fps_seq, fps_at = 0, None
                last_frame_at = self._clock()
                while self._is_current(generation):
                    packet: FramePacket = session.snapshot()
                    now = self._clock()
                    age = now - packet.at if packet.at else None
                    valid = packet.frame is not None and age is not None and 0.0 <= age <= cfg.AI_SUBSTREAM_MAX_AGE_SEC
                    if not session.alive() or (not valid and now - last_frame_at > cfg.AI_SUBSTREAM_MAX_AGE_SEC):
                        self._failure("READ_FAILED" if not session.alive() else "TIMEOUT", generation)
                        break
                    if valid and packet.seq > last_seq:
                        with self._lock:
                            if not self._is_current(generation):
                                break
                            self._frame_seq += packet.seq - last_seq
                            self._latest = AIFramePacket(packet.frame, self._frame_seq, packet.at, epoch)
                            self._state = "READY"
                            self._reason = ""
                            # Readiness may decode a buffered startup burst. Measure
                            # ongoing arrivals, including frames skipped by this
                            # latest-slot consumer, rather than freezing that burst.
                            if fps_at is None or packet.at < fps_at:
                                fps_seq, fps_at = packet.seq, packet.at
                                self._capture_fps = 0.0
                            elif packet.at - fps_at >= 1.0:
                                self._capture_fps = round((packet.seq - fps_seq) / (packet.at - fps_at), 1)
                                fps_seq, fps_at = packet.seq, packet.at
                            self._failures = 0
                        last_seq = packet.seq
                        last_frame_at = now
                    elif now - last_frame_at > cfg.AI_SUBSTREAM_MAX_AGE_SEC:
                        self._failure("TIMEOUT", generation)
                        break
                    self._changed.wait(0.008)
            except Exception as exc:
                # Constructors reject malformed/masked sources before starting
                # a decoder. Only exact allowlisted categories may be surfaced.
                code = str(exc) if isinstance(exc, ValueError) and str(exc) in ERRORS else (
                    "START_FAILED" if session is None else "READ_FAILED")
                self._failure(code, generation)
            finally:
                if session is not None:
                    self._retire(session)
