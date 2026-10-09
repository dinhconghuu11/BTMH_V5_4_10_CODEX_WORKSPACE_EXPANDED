"""Isolated decoder executable. No app/database imports and no URL in argv.

One process owns one VideoCapture. Parent communicates using private pipes; native
FFmpeg diagnostics go to stderr (classified, never forwarded verbatim). A blocked
native open/read can be terminated without touching another camera's decoder.
"""
from __future__ import annotations
import json
import os
import queue
import struct
import sys
import threading
import time

MAGIC = b"BTM4"
HEADER = struct.Struct("!4sII")
MAX_FRAME = 4096 * 2160 * 3


def main() -> int:
    raw = sys.stdin.buffer.readline(65537)
    if len(raw) > 65536:
        return 2
    cfg = json.loads(raw)
    source = cfg["source"]
    network = isinstance(source, str) and source.lower().startswith(("rtsp://", "http://", "https://"))
    # Each process has its own options. Do not inherit experimental low-buffer,
    # stimeout or hardware-acceleration flags from a previous camera generation.
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;" + cfg.get("transport", "tcp") if str(source).lower().startswith("rtsp://") else ""
    os.environ.setdefault("OPENCV_FFMPEG_THREADS", "2")
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    out = sys.stdout.buffer
    commands = queue.Queue(maxsize=16)
    closing = threading.Event()

    def emit(meta, frame=None):
        data = b"" if frame is None else np.ascontiguousarray(frame).tobytes()
        if len(data) > MAX_FRAME:
            raise ValueError("frame exceeds supported limit")
        body = json.dumps(meta, separators=(",", ":")).encode("utf-8")
        for chunk in (HEADER.pack(MAGIC, len(body), len(data)), body, data):
            view = memoryview(chunk)
            while view:
                written = out.write(view)
                if not written: raise BrokenPipeError
                view = view[written:]
        out.flush()

    def receive():
        while True:
            line = sys.stdin.buffer.readline(4097)
            if not line:
                # Parent has died/closed the pipe. Also stops a blocked native read.
                os._exit(0)
            try:
                cmd = json.loads(line)
                if cmd.get("op") == "stop":
                    closing.set()
                else:
                    commands.put_nowait(cmd)
            except (ValueError, queue.Full):
                continue

    threading.Thread(target=receive, daemon=True, name="decoder-commands").start()
    def valid(f):
        return f is not None and isinstance(f, np.ndarray) and f.dtype == np.uint8 and f.ndim == 3 and f.shape[2] == 3 and f.shape[0] >= 16 and f.shape[1] >= 16 and f.size <= MAX_FRAME
    plans = cfg.get("plans") or [{"backend_name":"ffmpeg", "backend_code":cv2.CAP_FFMPEG, "width":1920,"height":1080,"fps":25,"fourcc":None}]
    if network:
        plans = plans[:1]  # No repeated authentication attempts across backends.
    cap = None
    first = None
    selected = None
    for plan in plans:
        if closing.is_set():
            return 0
        emit({"type":"state", "state":"opening", "backend":plan["backend_name"]})
        api = cv2.CAP_FFMPEG if network else plan.get("backend_code")
        api = cv2.CAP_ANY if api is None else api
        try:
            if network:
                params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(cfg.get("open_timeout_ms", 8000)),
                          cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(cfg.get("read_timeout_ms", 3000))]
                if hasattr(cv2, "CAP_PROP_HW_ACCELERATION"):
                    params += [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE]
                cap = cv2.VideoCapture(source, api, params)
            else:
                cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source, api)
            if not cap or not cap.isOpened():
                if cap is not None:
                    cap.release()
                cap = None
                continue
            if not network:
                if plan.get("fourcc"):
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*plan["fourcc"][:4]))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, plan["width"])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, plan["height"])
                cap.set(cv2.CAP_PROP_FPS, plan["fps"])
                if cfg.get("autofocus"):
                    cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
                if cfg.get("auto_exposure"):
                    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, .75)
            # Frames, not isOpened(), prove readiness. Accept an actual USB mode
            # rather than repeatedly releasing a working 720p laptop for 1080p.
            deadline = time.monotonic() + (6.0 if network else 3.0)
            while not closing.is_set() and time.monotonic() < deadline:
                ok, frame = cap.read()
                if ok and valid(frame):
                    first = frame
                    break
                time.sleep(.01)
            if first is not None:
                selected = plan
                break
            cap.release()
            cap = None
        except Exception:
            # Never serialize an exception containing the connection URL.
            if cap is not None:
                cap.release()
            cap = None
    if cap is None or first is None:
        emit({"type":"error", "code":"OPEN_FAILED", "stage":"decode"})
        return 3
    properties = {}
    for name in ("CAP_PROP_FPS", "CAP_PROP_FOURCC", "CAP_PROP_PAN", "CAP_PROP_TILT", "CAP_PROP_ZOOM", "CAP_PROP_FOCUS", "CAP_PROP_AUTOFOCUS", "CAP_PROP_AUTO_EXPOSURE"):
        prop = getattr(cv2, name, None)
        if prop is not None:
            try:
                value = float(cap.get(prop))
                properties[str(prop)] = value if np.isfinite(value) else 0.0
            except Exception:
                properties[str(prop)] = 0.0
    emit({"type":"opened", "backend":selected["backend_name"], "plan":selected,
          "properties":properties, "width":first.shape[1], "height":first.shape[0],
          "transport":cfg.get("transport", "tcp") if network else "usb"})
    seq = 0
    last_sent = 0.
    output_fps = float(cfg.get("output_fps") or 0)
    frame = first
    bad = 0
    try:
        while not closing.is_set():
            at = time.perf_counter()
            if valid(frame) and (not output_fps or at - last_sent >= 1. / max(1., output_fps)):
                seq += 1
                emit({"type":"frame", "seq":seq, "shape":list(frame.shape), "at":at}, frame)
                last_sent = at
            while not commands.empty():
                cmd = commands.get_nowait()
                ident = str(cmd.get("id", ""))[:60]
                prop = int(cmd.get("prop", -1))
                allowed = {getattr(cv2, n, -10) for n in ("CAP_PROP_PAN", "CAP_PROP_TILT", "CAP_PROP_ZOOM", "CAP_PROP_FOCUS", "CAP_PROP_AUTOFOCUS")}
                success = False
                if not network and cmd.get("op") == "set" and prop in allowed:
                    try:
                        success = bool(cap.set(prop, float(cmd["value"])))
                        properties[str(prop)] = float(cap.get(prop))
                    except Exception:
                        pass
                emit({"type":"control", "id":ident, "ok":success, "properties":properties})
            ok, frame = cap.read()
            if not ok or not valid(frame):
                bad += 1
                frame = None
                if bad >= 3:
                    emit({"type":"error", "code":"READ_FAILED", "stage":"video"})
                    break
                time.sleep(.03)
            else:
                bad = 0
    finally:
        cap.release()  # This is the ONLY process/thread that releases this handle.
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BrokenPipeError, OSError):
        raise SystemExit(0)
    except Exception:
        # No traceback/URL/credential to inherited stdout or parent logs.
        raise SystemExit(4)
