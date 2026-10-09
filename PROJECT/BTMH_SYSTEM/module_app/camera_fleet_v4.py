"""Leased auxiliary readers with source-bound ownership and bounded recovery."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Any
import uuid
import cv2
from .capture_session_v544 import CaptureSession, ERRORS

PERMANENT_ERRORS = frozenset({"AUTH_FAILED", "PATH_NOT_FOUND", "MASKED_CREDENTIALS", "INVALID_SOURCE"})
READER_TTL_SEC = 15.0
JPEG_MAX_AGE_SEC = 4.0
MAX_LEASES_PER_CAMERA = 64


class FleetUnavailable(RuntimeError):
    def __init__(self, code="FLEET_RETIRE_FAILED"):
        self.code = code if code in {"FLEET_RETIRE_FAILED", "FLEET_LEASE_LIMIT"} else "FLEET_RETIRE_FAILED"
        super().__init__(self.code)


@dataclass
class FleetWorker:
    camera_id: int
    source: Any
    name: str
    target_fps: float = 8.
    lock: threading.RLock = field(default_factory=threading.RLock)
    thread: threading.Thread | None = None
    running: bool = False
    latest_jpeg: bytes | None = None
    latest_at: float = 0.
    frame_seq: int = 0
    opened: bool = False
    error: str = ""
    reconnects: int = 0
    session: Any = None
    stopped: threading.Event = field(default_factory=threading.Event)
    session_factory: Any = None
    clock: Any = time.perf_counter
    _retire_lock: Any = field(default_factory=threading.Lock)
    _failures: int = 0
    _retry_at: float = 0.
    _blocked_code: str = ""
    _retire_retry_at: float = 0.

    def start(self):
        with self.lock:
            if self.error in PERMANENT_ERRORS or self._blocked_code:
                return
            if self.thread and self.thread.is_alive():
                return
            self.running = True
            self.stopped.clear()
            self.thread = threading.Thread(target=self._run, name=f"btmh-fleet-{self.camera_id}", daemon=True)
            self.thread.start()

    @staticmethod
    def _decoder_retired(session):
        proof = getattr(session, "retired", None)
        return bool(proof()) if callable(proof) else not session.alive()

    def retired(self):
        with self.lock:
            return not bool(self.thread and self.thread.is_alive()) and (
                self.session is None or self._decoder_retired(self.session))

    def _clear_frame(self):
        self.latest_jpeg = None
        self.latest_at = 0.
        self.opened = False

    def stop(self, *, wait=True, timeout=6.5):
        with self.lock:
            self.running = False
            self.stopped.set()
            self._clear_frame()
            thread, session = self.thread, self.session
        if thread and thread is not threading.current_thread() and wait:
            thread.join(timeout=min(2., max(0., timeout)))
        # Retry a retained decoder only after its owner has exited.
        if session is not None and not bool(thread and thread.is_alive()) and self.clock() >= self._retire_retry_at:
            if wait:
                self._retire(session)
            else:
                with self.lock:
                    if self.session is session and not bool(self.thread and self.thread.is_alive()):
                        self.thread = threading.Thread(target=lambda: self._retire(session), name=f"btmh-fleet-retire-{self.camera_id}", daemon=True)
                        self.thread.start()
        return self.retired()

    def status(self):
        with self.lock:
            age = self.clock() - self.latest_at if self.latest_at else None
            fresh = age is not None and math.isfinite(age) and 0. <= age < JPEG_MAX_AGE_SEC
            return dict(online=bool(self.running and self.opened and self.latest_jpeg and fresh),
                        last_frame_age_sec=round(age, 2) if age is not None and math.isfinite(age) else None,
                        error=self.error, reconnects=self.reconnects, frame_seq=self.frame_seq,
                        worker_alive=bool(self.thread and self.thread.is_alive()),
                        retry_blocked=bool(self._blocked_code or self.error in PERMANENT_ERRORS),
                        retry_in_sec=round(max(0., self._retry_at - self.clock()), 1))

    def jpeg(self):
        with self.lock:
            age = self.clock() - self.latest_at if self.latest_at else None
            if (not self.running or not self.opened or age is None or not math.isfinite(age)
                    or not 0. <= age < JPEG_MAX_AGE_SEC):
                return None
            return self.latest_jpeg

    def _failure(self, code):
        with self.lock:
            self.error = code if code in ERRORS else "DECODER_ERROR"
            if self.error in PERMANENT_ERRORS:
                self._blocked_code = self.error
            self._clear_frame()
            self.reconnects += 1
            self._failures += 1
            self._retry_at = self.clock() + min(30., 2. ** min(self._failures - 1, 5))

    def _retire(self, session):
        with self._retire_lock:
            try:
                session.close()
                if not self._decoder_retired(session):
                    raise RuntimeError("DECODER_RETIRE_FAILED")
            except Exception:
                with self.lock:
                    self.session = session
                    self.error = "DECODER_RETIRE_FAILED"
                    self._clear_frame()
                    self._retire_retry_at = self.clock() + 1.
                return False
            with self.lock:
                if self.session is session:
                    self.session = None
                if self.error == "DECODER_RETIRE_FAILED":
                    self.error = self._blocked_code
                self._retire_retry_at = 0.
            return True

    def _new_session(self):
        if self.session_factory is not None:
            return self.session_factory(str(self.source), output_fps=self.target_fps)
        from .camera import StaticCameraService
        from dataclasses import asdict
        src = int(self.source) if str(self.source).isdigit() else self.source
        return CaptureSession(str(self.source), plans=[asdict(p) for p in StaticCameraService.capture_plans(src)],
                              output_fps=self.target_fps)

    def _run(self):
        try:
            while not self.stopped.is_set():
                with self.lock:
                    pending = self.session
                    due = self.clock() >= (self._retire_retry_at if pending is not None else self._retry_at)
                if not due:
                    self.stopped.wait(.1)
                    continue
                if pending is not None:
                    self._retire(pending)
                    continue
                session = None
                try:
                    session = self._new_session()
                    with self.lock:
                        self.session = session
                    if self.stopped.is_set():
                        continue
                    session.start()
                    ready = session.wait_ready(3, 18., cancelled=self.stopped.is_set)
                    if self.stopped.is_set():
                        continue
                    if not ready.get("ok"):
                        self._failure(str(ready.get("code") or "OPEN_FAILED"))
                    else:
                        seq, progress_at = 0, self.clock()
                        while not self.stopped.is_set():
                            packet = session.snapshot()
                            now = self.clock()
                            age = now - packet.at if packet.at else None
                            fresh = packet.frame is not None and age is not None and math.isfinite(age) and 0. <= age < JPEG_MAX_AGE_SEC
                            if not session.alive() or now - progress_at >= JPEG_MAX_AGE_SEC:
                                self._failure("READ_FAILED" if not session.alive() else "TIMEOUT")
                                break
                            if fresh and packet.seq > seq:
                                frame = packet.frame
                                if frame.shape[1] > 1280:
                                    frame = cv2.resize(frame, (1280, round(frame.shape[0] * 1280 / frame.shape[1])))
                                ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
                                if ok:
                                    with self.lock:
                                        if self.stopped.is_set():
                                            break
                                        self.latest_jpeg = buf.tobytes()
                                        self.latest_at = packet.at
                                        self.frame_seq += packet.seq - seq
                                        self.opened = True
                                        self.error = ""
                                        self._failures = 0
                                seq, progress_at = packet.seq, now
                            self.stopped.wait(.02)
                except Exception as exc:
                    code = str(exc) if isinstance(exc, ValueError) and str(exc) in ERRORS else "DECODER_ERROR"
                    self._failure(code)
                finally:
                    if session is not None:
                        self._retire(session)
                    with self.lock:
                        self.opened = False
                if self.error in PERMANENT_ERRORS or self._blocked_code:
                    break
        finally:
            with self.lock:
                self.running = False
                self._clear_frame()


class CameraFleetV4:
    def __init__(self, *, clock=None, worker_factory=None, lease_ttl=READER_TTL_SEC):
        self.lock = threading.RLock()
        self.workers: dict[int, FleetWorker] = {}
        self._reserved: dict[int, int] = {}
        self._leases: dict[int, dict[str, float]] = {}
        self._camera_locks: dict[int, Any] = {}
        self._clock = clock or time.perf_counter
        self._factory = worker_factory or FleetWorker
        self._ttl = max(1., min(60., float(lease_ttl)))
        self._sweeper = None
        self._sweep_stop = threading.Event()
        self._sweep_cursor = 0

    def _camera_lock(self, cid):
        with self.lock:
            return self._camera_locks.setdefault(cid, threading.RLock())

    def _prune(self, cid):
        now = self._clock()
        leases = self._leases.get(cid, {})
        for token, deadline in list(leases.items()):
            if deadline <= now:
                leases.pop(token, None)
        if not leases:
            self._leases.pop(cid, None)

    def _ensure_worker(self, cid, source, name):
        with self.lock:
            worker = self.workers.get(cid)
        if worker and str(worker.source) != str(source):
            if not self.stop(cid):
                raise FleetUnavailable()
            worker = None
        if worker and worker.stopped.is_set() and not worker.retired():
            if not self.stop(cid):
                raise FleetUnavailable()
            worker = None
        if worker is None:
            worker = self._factory(cid, source, name)
            with self.lock:
                self.workers[cid] = worker
        return worker

    def _start_sweeper(self):
        with self.lock:
            if self._sweeper and self._sweeper.is_alive():
                return
            self._sweep_stop.clear()
            self._sweeper = threading.Thread(target=self._sweep_loop, name="btmh-fleet-leases", daemon=True)
            self._sweeper.start()

    def _lease(self, camera_id, source, name, token):
        cid = int(camera_id)
        with self._camera_lock(cid):
            worker = self._ensure_worker(cid, source, name)
            with self.lock:
                self._prune(cid)
                leases = self._leases.setdefault(cid, {})
                if token not in leases and len(leases) >= MAX_LEASES_PER_CAMERA:
                    raise FleetUnavailable("FLEET_LEASE_LIMIT")
                leases[token] = self._clock() + self._ttl
                reserved = bool(self._reserved.get(cid))
            if not reserved:
                worker.start()
            else:
                worker.error = "HANDOVER_RESERVED"
            self._start_sweeper()
            return worker

    def ensure(self, camera_id, source, name):
        """Frame polling touches one implicit TTL slot instead of owning forever."""
        return self._lease(camera_id, source, name, "_poll")

    def acquire(self, camera_id, source, name):
        token = uuid.uuid4().hex
        return self._lease(camera_id, source, name, token), token

    def renew(self, camera_id, token):
        cid = int(camera_id)
        with self._camera_lock(cid):
            with self.lock:
                self._prune(cid)
                leases = self._leases.get(cid, {})
                if token not in leases or self._reserved.get(cid):
                    return False
                leases[token] = self._clock() + self._ttl
                return True

    def release(self, camera_id, token):
        cid = int(camera_id)
        with self._camera_lock(cid):
            with self.lock:
                leases = self._leases.get(cid, {})
                found = token in leases
                leases.pop(token, None)
                self._prune(cid)
                idle = not self._leases.get(cid)
            if idle:
                self.stop(cid, wait=False)
            return found

    def get(self, camera_id):
        with self.lock:
            return self.workers.get(int(camera_id))

    def stop(self, camera_id, *, wait=True, timeout=6.5):
        cid = int(camera_id)
        with self.lock:
            # Unknown request IDs must not allocate persistent lifecycle entries.
            # An existing lock can represent construction already in progress.
            if cid not in self.workers and cid not in self._leases and cid not in self._camera_locks:
                return True
        with self._camera_lock(cid):
            with self.lock:
                worker = self.workers.get(cid)
                self._leases.pop(cid, None)
            if worker is None:
                return True
            worker.stop(wait=wait, timeout=timeout)
            retired = worker.retired()
            with self.lock:
                if retired and self.workers.get(cid) is worker:
                    self.workers.pop(cid, None)
            return retired

    def sweep_idle(self, max_workers=16):
        with self.lock:
            ids = list(self.workers)
            if not ids:
                return
            offset = self._sweep_cursor % len(ids)
            selected = (ids[offset:] + ids[:offset])[:max(1, min(64, int(max_workers)))]
            self._sweep_cursor = offset + len(selected)
        for cid in selected:
            lifecycle = self._camera_lock(cid)
            if not lifecycle.acquire(blocking=False):
                continue
            try:
                with self.lock:
                    self._prune(cid)
                    idle = not self._leases.get(cid) and not self._reserved.get(cid)
                if idle:
                    self.stop(cid, wait=False)
            finally:
                lifecycle.release()

    def _sweep_loop(self):
        while not self._sweep_stop.wait(1.):
            self.sweep_idle()

    @contextmanager
    def reserve(self, camera_id):
        if camera_id is None:
            yield
            return
        cid = int(camera_id)
        with self._camera_lock(cid):
            with self.lock:
                self._reserved[cid] = self._reserved.get(cid, 0) + 1
        try:
            if not self.stop(cid, wait=True, timeout=2.):
                raise FleetUnavailable()
            yield
        finally:
            with self.lock:
                self._reserved[cid] = self._reserved.get(cid, 1) - 1
                if self._reserved[cid] <= 0:
                    self._reserved.pop(cid, None)

    def shutdown(self):
        self._sweep_stop.set()
        with self.lock:
            ids = list(self.workers)
        for cid in ids:
            self.stop(cid)
        if self._sweeper and self._sweeper is not threading.current_thread():
            self._sweeper.join(timeout=1.2)


FLEET_V4 = CameraFleetV4()
