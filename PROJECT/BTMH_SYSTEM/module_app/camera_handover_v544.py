"""Transactional camera selection: prepare a new decoder before committing.

The active source, FaceID, and preview continue throughout preflight. A failed
candidate is destroyed independently. Only commit briefly gates AI so a frame
from one physical source cannot be processed/labeled as another source.
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import threading
import time

from .capture_session_v544 import CaptureSession, ERRORS, display_source, valid_source
from . import config as cfg


def stamp():
    return datetime.now(timezone.utc).isoformat()


class CameraHandoverV544Mixin:
    def _camera_lifecycle_lock(self):
        with self._lock:
            if not hasattr(self, "_camera_lifecycle"):
                self._camera_lifecycle = threading.RLock()
            return self._camera_lifecycle

    def _retire_session(self, session) -> bool:
        """Keep a strong owner until close supplies reliable child-exit proof."""
        if session is None:
            return True
        with self._lock:
            retained = getattr(self, "_retiring_sessions", [])
            if not any(owner is session for owner in retained):
                retained.append(session)
            self._retiring_sessions = retained
        try:
            session.close()
            proof = getattr(session, "retired", None)
            retired = bool(proof()) if callable(proof) else not session.alive()
        except Exception:
            retired = False
        with self._lock:
            if retired:
                self._retiring_sessions = [owner for owner in self._retiring_sessions if owner is not session]
                if self._pending_session is session:
                    self._pending_session = None
            blocked = bool(self._retiring_sessions)
            self._status.update(safe_decoder_shutdown=not blocked, recovery_blocked=blocked,
                                retirement_warning="DECODER_RETIRE_FAILED" if blocked else "")
        return retired

    def _retry_retiring_sessions(self) -> bool:
        with self._lock:
            sessions = list(getattr(self, "_retiring_sessions", []))
        retired = True
        for session in sessions:
            retired = self._retire_session(session) and retired
        return retired

    def _new_session(self, source: str):
        source = valid_source(source)
        value = int(source) if source.isdigit() else source
        plans = list(self.capture_plans(value))
        cached = self._capture_plan_cache.get(source)
        if cached:
            plans = [cached] + [p for p in plans if p != cached]
        network = str(source).lower().startswith("rtsp://")
        return CaptureSession(
            source, plans=[asdict(p) for p in plans],
            autofocus=cfg.CAMERA_AUTOFOCUS, auto_exposure=cfg.CAMERA_AUTO_EXPOSURE,
            output_fps=cfg.RTSP_CAPTURE_FPS if network else 0.0,
            output_max_width=cfg.RTSP_CAPTURE_MAX_WIDTH if network else 0,
        )

    def start(self) -> None:
        if cfg.CAMERA_MODE != "service":
            return
        with self._camera_lifecycle_lock():
            with self._lock:
                live_threads = [t for t in self._threads if t.is_alive()]
                self._threads = live_threads
                if live_threads:
                    if self._stop.is_set() or not any(t.name == "cf-camera-capture" for t in live_threads):
                        self._status.update(recovery_blocked=True, safe_decoder_shutdown=False,
                                            retirement_warning="WORKER_RETIRE_PENDING")
                    return
                stopped_sessions = [self._active_session, self._pending_session] if self._stop.is_set() else []
            for session in stopped_sessions:
                if session is not None and not self._retire_session(session):
                    return
                with self._lock:
                    if self._active_session is session:
                        self._active_session = None
            if not self._retry_retiring_sessions():
                return
            with self._lock:
                self._run_generation += 1
                generation = self._run_generation
                self._stop.clear()
                self._status.update(running=True, state="opening", worker_generation=generation,
                                    capture_owner="ISOLATED_DECODER_PROCESS", safe_decoder_shutdown=True,
                                    recovery_blocked=False, retirement_warning="")
                self._threads = [
                    threading.Thread(target=self._capture_loop, args=(generation,), name="cf-camera-capture", daemon=True),
                    threading.Thread(target=self._ai_loop, args=(generation,), name="cf-camera-ai", daemon=True),
                    threading.Thread(target=self._preview_loop, args=(generation,), name="cf-camera-preview", daemon=True),
                ]
                for thread in self._threads: thread.start()
            self._sync_ai_capture_epoch()
            self._ai_capture.start()

    def stop(self) -> None:
        # Setting stop also cancels a concurrent candidate's readiness wait.
        self._stop.set()
        with self._camera_lifecycle_lock():
            with self._lock:
                self._run_generation += 1
                sessions = []
                for session in [self._active_session, self._pending_session, *getattr(self, "_retiring_sessions", [])]:
                    if session is not None and not any(owner is session for owner in sessions):
                        sessions.append(session)
                threads = list(self._threads)
                self._source_epoch += 1
                self._status.update(running=False, opened=False, state="stopped", capture_fps=0.)
            with self._cap_lock: self._cap = None
            self._ai_capture.stop()
            for session in sessions:
                if self._retire_session(session):
                    with self._lock:
                        if self._active_session is session:
                            self._active_session = None
            for thread in threads:
                if thread is not threading.current_thread(): thread.join(timeout=.8)
            with self._lock:
                self._threads = [thread for thread in threads if thread.is_alive()]
                blocked = bool(self._threads or getattr(self, "_retiring_sessions", []))
                self._status.update(state="stopping" if blocked else "stopped", recovery_blocked=blocked,
                                    safe_decoder_shutdown=not blocked)
            from .walkby import WALKBY
            getattr(self, "_walkby", WALKBY).shutdown(getattr(self, "_ai_session_id", "service-camera"))
            self._set_placeholder("CAMERA STOPPED")

    def _session_runtime(self, session) -> dict:
        meta = session.metadata()
        d = session.diagnostics("READY")
        fourcc = self._fourcc_text(session.get(6))
        return {"backend": meta.get("backend", ""), "fourcc":fourcc,
                "actual_width":d["width"], "actual_height":d["height"],
                "driver_fps":round(session.get(5), 1), "capture_fps":d["observed_fps"],
                "transport":d["transport"], "capture_owner":"ISOLATED_DECODER_PROCESS",
                "rtsp_hwaccel_requested":False,
                "safe_decoder_shutdown":not bool(getattr(self, "_retiring_sessions", [])),
                "decoder_output_fps": float(d.get("decoder_output_fps") or 0.0),
                "decoder_max_width": int(d.get("decoder_max_width") or 0),
                "realtime_profile": cfg.RTSP_REALTIME_PROFILE if str(session.source).lower().startswith("rtsp://") else "usb",
                "resolution_fallback":d["width"] < cfg.CAMERA_WIDTH or d["height"] < cfg.CAMERA_HEIGHT}

    def _capture_loop(self, generation=None) -> None:
        last_session = None
        last_seq = -1
        retry_at = 0.
        backoff = .5
        while self._run_is_active(generation):
            with self._lock:
                active = self._active_session
                blocked = self._retry_blocked_source
                source = str(self._source_value())
            if active is None:
                if blocked == source or time.perf_counter() < retry_at:
                    self._stop.wait(.05); continue
                if not self._handover_lock.acquire(blocking=False):
                    self._stop.wait(.02); continue
                new = None
                try:
                    if not self._run_is_active(generation): break
                    if not self._retry_retiring_sessions():
                        retry_at = time.perf_counter() + backoff
                        backoff = min(6., backoff * 2)
                        continue
                    with self._lock:
                        if self._active_session is not None: continue
                    new = self._new_session(source)
                    new.start()
                    with self._lock:
                        if self._run_is_active(generation) and self._active_session is None:
                            self._active_session = new
                            self._status.update(state="opening", opened=False, error="", camera_error_code="")
                            with self._cap_lock: self._cap = new
                            new = None
                except Exception as exc:
                    code = str(exc) if str(exc) in ERRORS else "START_FAILED"
                    with self._lock:
                        self._status.update(state="error", opened=False, error=ERRORS[code], camera_error_code=code)
                        if code in {"INVALID_SOURCE", "MASKED_CREDENTIALS"}: self._retry_blocked_source = source
                    retry_at = time.perf_counter() + min(6., backoff)
                    backoff = min(6., backoff * 2)
                finally:
                    if new: self._retire_session(new)
                    self._handover_lock.release()
                self._stop.wait(.01); continue
            packet = active.snapshot()
            if active is not last_session:
                last_seq = -1
                last_session = active
            if packet.frame is not None and packet.seq != last_seq and active.healthy(max_age=1.5):
                with self._lock:
                    if self._active_session is active and self._run_is_active(generation):
                        self._publish_frame(packet.frame, packet.at)
                        self._status.update(self._session_runtime(active))
                        self._status["camera_error_code"] = ""
                        last_seq = packet.seq
                self._update_quality(packet.frame, packet.at)
                backoff = .5
            now = time.perf_counter()
            stale = (packet.at > 0 and now - packet.at > 4.5) or (packet.at == 0 and now - active.started_at > 20.)
            failed = not active.alive() or stale
            if failed and now >= retry_at and self._handover_lock.acquire(blocking=False):
                retire = None
                try:
                    if not self._run_is_active(generation): break
                    with self._lock:
                        if self._active_session is active:
                            d = active.diagnostics("TIMEOUT" if stale else None)
                            self._status.update(opened=False, state="reconnecting", capture_fps=0.,
                                                error=d["message"], camera_error_code=d["code"])
                            self._status["reconnect_count"] += 1
                            # Avoid repeatedly hitting a camera with invalid credentials.
                            if d["code"] in {"AUTH_FAILED", "PATH_NOT_FOUND", "MASKED_CREDENTIALS"}:
                                self._retry_blocked_source = source
                                self._status["state"] = "error"
                            with self._cap_lock:
                                if self._cap is active: self._cap = None
                            retire = active
                    if retire:
                        if self._retire_session(retire):
                            with self._lock:
                                if self._active_session is retire:
                                    self._active_session = None
                        else:
                            with self._lock:
                                self._status.update(error=ERRORS["DECODER_RETIRE_FAILED"],
                                                    camera_error_code="DECODER_RETIRE_FAILED")
                        self._set_placeholder("CAMERA RECONNECTING...")
                        retry_at = time.perf_counter() + backoff
                        backoff = min(6., backoff * 2)
                finally:
                    self._handover_lock.release()
            self._stop.wait(.008)

    def _camera_failure(self, code, source, label, previous_source, previous_label, diagnostic=None):
        with self._lock:
            old = self._active_session
        kept = bool(old and old.healthy())
        message = (diagnostic or {}).get("message") or ERRORS.get(code, ERRORS["OPEN_FAILED"])
        message += (" Camera hi\u1ec7n t\u1ea1i v\u1eabn ho\u1ea1t \u0111\u1ed9ng." if kept else
                    " Ch\u01b0a c\u00f3 ngu\u1ed3n h\u00ecnh \u1ea3nh s\u1eb5n s\u00e0ng.")
        self._set_handover_state(active=False, state="KEPT_PREVIOUS" if kept else "FAILED",
            message=message, finished_at=stamp(), rolled_back=False, error_code=code)
        return {"ok":False, "code":code, "message":message, "error":message,
                "source":display_source(previous_source), "source_label":previous_label,
                "requested_source":display_source(source), "requested_label":label,
                "kept_previous":kept, "rolled_back":False, "diagnostic":diagnostic or {"code":code},
                "runtime":self.status(), "handover":dict(self._handover)}

    def test_source(self, source: str, *, source_label: str | None = None, timeout_sec: float = 18.) -> dict:
        """Read actual frames without changing the active source or FaceID state."""
        return self._prepare_source(source, source_label=source_label, timeout_sec=timeout_sec,
                                    stable_frames=5, commit=False)

    def safe_select_source(self, source: str, *, source_label: str | None = None,
                           stable_frames: int = 5, timeout_sec: float = 18.) -> dict:
        return self._prepare_source(source, source_label=source_label, timeout_sec=timeout_sec,
                                    stable_frames=stable_frames, commit=True)

    def _prepare_source(self, source, *, source_label, timeout_sec, stable_frames, commit):
        value = str(source).strip()
        label = str(source_label or "Camera").strip()[:120]
        with self._lock:
            previous_source = str(self._source_value())
            previous_label = self.event_camera_source()
            generation = self._run_generation
        if not self._handover_lock.acquire(blocking=False):
            return {"ok":False,"busy":True,"code":"BUSY","message":ERRORS["BUSY"],"runtime":self.status()}
        candidate = None
        try:
            self._set_handover_state(active=True, state="CHECKING", from_source=display_source(previous_source),
                to_source=display_source(value), from_label=previous_label, to_label=label,
                message="\u0110ang ki\u1ec3m tra camera m\u1edbi; ngu\u1ed3n hi\u1ec7n t\u1ea1i v\u1eabn ho\u1ea1t \u0111\u1ed9ng.",
                stable_frames=0, required_frames=max(3, int(stable_frames)), error_code="", rolled_back=False,
                started_at=stamp(), finished_at="")
            try:
                value = valid_source(value)
            except ValueError as exc:
                return self._camera_failure(str(exc), value, label, previous_source, previous_label)
            if not self._retry_retiring_sessions():
                return self._camera_failure("DECODER_RETIRE_FAILED", value, label, previous_source, previous_label)
            with self._lock: old = self._active_session
            if value == previous_source and old is not None and old.healthy():
                d = old.diagnostics("READY"); d["message"] = "Camera hi\u1ec7n t\u1ea1i \u0111ang ho\u1ea1t \u0111\u1ed9ng."
                self._set_handover_state(active=False,state="READY",message=d["message"],finished_at=stamp())
                return {"ok":True,"noop":True,"diagnostic":d,"source":display_source(value),"source_label":label,
                        "message":d["message"],"runtime":self.status(),"handover":dict(self._handover)}
            try:
                candidate = self._new_session(value)
                with self._lock: self._pending_session = candidate
                candidate.start()
                diagnostic = candidate.wait_ready(max(3,min(8,int(stable_frames))), min(30.,max(.1,float(timeout_sec))),
                    cancelled=lambda:self._stop.is_set() or generation != self._run_generation)
            except Exception:
                return self._camera_failure("START_FAILED",value,label,previous_source,previous_label)
            if not diagnostic["ok"]:
                return self._camera_failure(diagnostic["code"],value,label,previous_source,previous_label,diagnostic)
            if not commit:
                if not self._retire_session(candidate):
                    return self._camera_failure("DECODER_RETIRE_FAILED", value, label, previous_source, previous_label)
                candidate = None
                self._set_handover_state(active=False, state="TESTED",message=diagnostic["message"],
                                         stable_frames=diagnostic["stable_frames"],finished_at=stamp())
                return {"ok":True,"test_only":True,"diagnostic":diagnostic,"message":diagnostic["message"],
                        "source_label":label,"source_display":display_source(value),"runtime":self.status()}
            # Wait only at commit. During preflight the original FaceID continues.
            if not self._ai_work_lock.acquire(timeout=2.):
                return self._camera_failure("AI_BUSY",value,label,previous_source,previous_label,diagnostic={"code":"AI_BUSY","message":ERRORS["AI_BUSY"]})
            try:
                if self._stop.is_set() or generation != self._run_generation:
                    return self._camera_failure("CANCELLED",value,label,previous_source,previous_label)
                if not candidate.healthy():
                    return self._camera_failure("READ_FAILED",value,label,previous_source,previous_label)
                first = candidate.snapshot()
                # Gather fallible metadata before changing the active pointer.
                try:
                    runtime = self._session_runtime(candidate)
                except Exception:
                    return self._camera_failure("COMMIT_FAILED",value,label,previous_source,previous_label)
                restore = None
                old = None
                try:
                    with self._lock:
                        old = self._active_session
                        fields = ("_source_override", "_source_label_override", "_retry_blocked_source",
                                  "_recognition_paused", "_frame", "_frame_at", "_frame_seq", "_capture_total",
                                  "_jpeg", "_raw_jpeg", "_observation_jpeg", "_observation_jpeg_seq", "_observation_jpeg_at")
                        fields += tuple(name for name in ("_pipeline_enabled", "_event_context") if hasattr(self, name))
                        restore = {name:getattr(self,name) for name in fields}
                        status_before = dict(self._status)
                        ptz_before = dict(self._ptz_state)
                        self._recognition_paused = True
                        self._set_handover_state(state="COMMITTING",message="\u0110ang \u0111\u1ed5i ngu\u1ed3n h\u00ecnh \u1ea3nh.")
                        self._clear_transient_recognition(clear_recent=True)
                        if hasattr(self, "_pipeline_enabled"):
                            # A successful source commit waits for the supervisor
                            # to bind the new stable camera/location snapshot.
                            self._pipeline_enabled = False
                            self._event_context = {}
                        self._clear_camera_buffers_for_handover()
                        self._source_epoch += 1
                        self._active_session = candidate
                        self._pending_session = None
                        self._source_override = value
                        self._source_label_override = label
                        self._retry_blocked_source = ""
                        self._status.update(source=value, source_label=label, opened=True, running=True, state="online",error="",camera_error_code="")
                        self._sync_ai_capture_epoch()
                        self._status.update(runtime)
                        self._ptz_state.update(mode="digital", pan=0., tilt=0., zoom=1., hardware_supported=False)
                        with self._cap_lock: self._cap = candidate
                        self._publish_frame(first.frame, first.at)
                        self._recognition_paused = False
                        self._set_handover_state(active=False,state="READY",message="\u0110\u00e3 chuy\u1ec3n camera an to\u00e0n.",
                            stable_frames=diagnostic["stable_frames"],finished_at=stamp(),rolled_back=False)
                except Exception:
                    # A failed reset/publish cannot leave the active pointer targeting
                    # a candidate about to be closed. Restore the STILL OPEN source.
                    with self._lock:
                        if restore is not None and generation == self._run_generation and not self._stop.is_set():
                            for name, previous in restore.items(): setattr(self,name,previous)
                            self._active_session = old
                            self._status.clear(); self._status.update(status_before)
                            self._ptz_state.clear(); self._ptz_state.update(ptz_before)
                            self._source_epoch += 1
                            self._sync_ai_capture_epoch()
                            with self._cap_lock: self._cap = old
                    return self._camera_failure("COMMIT_FAILED",value,label,previous_source,previous_label)
                committed = candidate
                candidate = None  # Ownership transferred; cleanup must not kill it.
                try:
                    plan = committed.metadata().get("plan")
                    if plan:
                        from .camera import CapturePlan
                        self._capture_plan_cache[value] = CapturePlan(**plan)
                except Exception:
                    pass  # Optional cache cannot turn a committed live switch into failure.
            finally:
                self._ai_work_lock.release()
            retired = True
            if old is not None and old is not self._active_session:
                retired = self._retire_session(old)  # Never releases committed ownership.
            return {"ok":True,"source":display_source(value),"source_label":label,
                    "message":"\u0110\u00e3 chuy\u1ec3n an to\u00e0n sang " + label,
                    "stable_frames":diagnostic["stable_frames"], "diagnostic":diagnostic,
                    "rolled_back":False,"retirement_warning":"" if retired else "DECODER_RETIRE_FAILED",
                    "runtime":self.status(),"ptz":self.ptz_status(),"handover":dict(self._handover)}
        finally:
            if candidate is not None: self._retire_session(candidate)
            with self._lock:
                # Unexpected exceptions must not leave the UI showing HANDOVER forever.
                if self._handover.get("active"):
                    self._set_handover_state(active=False,state="FAILED",message="Ki\u1ec3m tra camera \u0111\u00e3 k\u1ebft th\u00fac.",finished_at=stamp())
            self._handover_lock.release()

    def restart(self) -> None:
        # Automatic recovery must never retire a working source during preflight.
        if not self._handover_lock.acquire(blocking=False):
            return
        try:
            if not self._retry_retiring_sessions():
                return
            with self._lock:
                active = self._active_session
            if active and not self._retire_session(active):
                return
            with self._lock:
                self._retry_blocked_source = ""
                if self._active_session is active:
                    self._active_session = None
                self._status.update(opened=False, state="reconnecting", error="")
            with self._cap_lock: self._cap = None
        finally:
            self._handover_lock.release()
        self.start()
