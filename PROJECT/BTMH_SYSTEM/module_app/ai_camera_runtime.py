"""Backend-owned camera admission; browser readers never own AI workers.

Reuse the mature StaticCameraService for every admitted source. Each owns its
WalkBy session and latest-frame capture, while model jobs share finite budgets.
This module imports no camera/model/database until the default factory is used.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import json
import os
import threading
import time


def _setting(name, default, ceiling):
    try:
        return max(1, min(ceiling, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


DEMO_AI_CAPACITY = 4
MAX_ACTIVE_TRACKS = _setting("BTMH_AI_MAX_TRACKS", 32, 128)
FACEID_CONCURRENCY = _setting("BTMH_AI_FACEID_CONCURRENCY", 2, DEMO_AI_CAPACITY)
PAD_CONCURRENCY = _setting("BTMH_AI_PAD_CONCURRENCY", 2, DEMO_AI_CAPACITY)
RECONCILE_SECONDS = 2.0
_MODEL_BUDGETS = {"faceid": threading.BoundedSemaphore(FACEID_CONCURRENCY),
                  "pad": threading.BoundedSemaphore(PAD_CONCURRENCY)}


def budgeted_inference(kind, infer):
    """No model-wait queue: busy jobs fail closed and retry on a newer sample."""
    def run(job):
        budget = _MODEL_BUDGETS[kind]
        if not budget.acquire(timeout=.02):
            raise RuntimeError("AI_BUDGET_BUSY")
        try:
            # Recheck freshness after acquiring the shared model budget.
            from .ai_pipeline_v550 import MAX_RESULT_AGE_SEC
            if not 0 <= time.perf_counter() - job.captured_at <= MAX_RESULT_AGE_SEC:
                raise RuntimeError("AI_SAMPLE_EXPIRED")
            return infer(job)
        finally:
            budget.release()
    return run


def consume_business_result(context, result, observed_at):
    """Small backend hooks; business modules are integrated in phases D/E."""
    try:
        from .shift_attendance import consume_camera_result
    except ImportError:
        consume_camera_result = None
    if consume_camera_result is not None:
        consume_camera_result(context, result, observed_at)
    try:
        from .entrance_visits import ENTRY_VISITS
    except ImportError:
        ENTRY_VISITS = None
    if ENTRY_VISITS is not None:
        ENTRY_VISITS.consume(context, result, observed_at)


def _worker_factory(row, context):
    from .camera import StaticCameraService
    from .walkby import WalkByEngine
    engine = WalkByEngine(max_tracks=MAX_ACTIVE_TRACKS, inference_wrapper=budgeted_inference)
    camera = StaticCameraService(engine=engine, session_id=f"camera-{int(row['id'])}")
    camera.configure_source(str(row["source"]), context["camera_name"])
    camera.configure_ai_source(str(row["source"]))
    camera.configure_ai_pipeline(context, enabled=True, consumer=consume_business_result)
    return camera


def processing_context(context):
    """Display metadata never changes capture, inference or business policy."""
    return {key: value for key, value in context.items()
            if key not in {"name", "camera_name", "store_name", "zone_id"}}


def _signature(row, context):
    return str(row.get("source") or ""), json.dumps(processing_context(context), sort_keys=True, ensure_ascii=False)


class CameraAIRuntime:
    def __init__(self, primary=None, *, rows=None, contexts=None, worker_factory=None,
                 capacity=DEMO_AI_CAPACITY, retire_reader=None, reader_reservation=None, retire_business=None):
        self.primary = primary
        self.capacity = max(1, int(capacity))  # future deployments can increase capacity without changing UI
        self._rows, self._contexts = rows, contexts
        self._factory = worker_factory or _worker_factory
        self._retire_reader = retire_reader
        self._reader_reservation = reader_reservation
        self._retire_business = retire_business
        self._lock = threading.RLock()
        self._changes = threading.RLock()
        self._workers = {}
        self._retiring = {}
        self._signatures = {}
        self._requested = {}
        self._failures = {}
        self._reserved = set()
        self._reservation_slots = set()
        self._stop = threading.Event()
        self._thread = None
        self._error = None

    def _configuration(self):
        if self._rows is None:
            from .production_ops import list_camera_devices
            rows = list_camera_devices()
        else:
            rows = self._rows()
        if self._contexts is None:
            from .demo_context import list_camera_contexts
            contexts = list_camera_contexts()
        else:
            contexts = self._contexts()
        return {int(row["id"]): row for row in rows}, {int(c["camera_id"]): c for c in contexts}

    @staticmethod
    def _retired(worker):
        status = worker.status()
        if status.get("recovery_blocked") or status.get("safe_decoder_shutdown") is False:
            return False
        engine = getattr(worker, "_walkby", None)
        if engine is not None:
            lanes = engine._pipeline.status()
            if any(lane.get("busy") or (lane.get("stopping") and lane.get("alive")) for lane in lanes.values()):
                return False
        return True

    def _retire(self, cid):
        with self._lock:
            worker = self._workers.pop(cid, None) or self._retiring.get(cid)
            self._signatures.pop(cid, None)
        if worker is None:
            return True
        if worker is self.primary:
            worker.configure_ai_pipeline({}, enabled=False)
        else:
            worker.stop()
        if self._retire_business is not None:
            self._retire_business(cid)
        retired = self._retired(worker)
        with self._lock:
            if retired:
                self._retiring.pop(cid, None)
            else:
                self._retiring[cid] = worker
        return retired

    def reconcile(self):
        with self._changes:
            rows, contexts = self._configuration()
            eligible = {cid for cid, c in contexts.items() if cid in rows and c.get("enabled")
                        and c.get("ai_enabled") and c.get("store_id") and c.get("zone_name")}
            primary_id = None
            if self.primary is not None:
                from .camera_profiles import normalize_camera_source
                source = normalize_camera_source(self.primary.current_source_identity())
                primary_id = next((cid for cid, row in rows.items()
                                   if normalize_camera_source(str(row.get("source") or "")) == source), None)
                if primary_id is not None and self.service(primary_id) is not self.primary and hasattr(self.primary, "set_source_label"):
                    self.primary.set_source_label(contexts.get(primary_id, {}).get("camera_name"))
            with self._lock:
                self._requested = contexts
                existing = list(self._workers)
                retiring = list(self._retiring)
            for cid in retiring:
                self._retire(cid)
            for cid in existing:
                worker = self.service(cid)
                expected_primary = cid == primary_id
                if (cid not in eligible or cid in self._reserved
                        or (worker is self.primary) != expected_primary
                        or self._signatures.get(cid) != _signature(rows[cid], contexts[cid])):
                    self._retire(cid)
                elif hasattr(worker, "refresh_ai_metadata"):
                    worker.refresh_ai_metadata(contexts[cid])
            # Keep current owners stable. Waiting cameras are admitted in ID order.
            order = sorted(eligible, key=lambda cid: (cid != primary_id, cid))
            for cid in order:
                with self._lock:
                    if cid in self._workers or cid in self._retiring or cid in self._reserved:
                        continue
                    held = len(self._reservation_slots - set(self._workers) - set(self._retiring))
                    if len(self._workers) + len(self._retiring) + held >= self.capacity:
                        break
                    if cid == primary_id and any(worker is self.primary for worker in self._retiring.values()):
                        continue
                worker = None
                try:
                    if cid == primary_id:
                        worker = self.primary
                        worker.configure_ai_pipeline(contexts[cid], enabled=True, consumer=consume_business_result)
                    else:
                        reader_scope = self._reader_reservation(cid) if self._reader_reservation else nullcontext()
                        with reader_scope:
                            if self._retire_reader is not None and self._retire_reader(cid) is False:
                                self._failures[cid] = "READER_RETIRE_PENDING"
                                continue  # never start over a decoder whose retirement is unproven
                            worker = self._factory(rows[cid], contexts[cid])
                            worker.start()
                            # Publish before releasing the reader reservation: polling
                            # now reuses this service instead of opening another decoder.
                            with self._lock:
                                self._workers[cid] = worker
                    with self._lock:
                        self._workers[cid] = worker
                        self._signatures[cid] = _signature(rows[cid], contexts[cid])
                        self._failures.pop(cid, None)
                except Exception:
                    self._error = "AI_WORKER_START_FAILED"
                    self._failures[cid] = "AI_WORKER_START_FAILED"
                    if worker is not None and worker is not self.primary:
                        worker.stop()
                        if not self._retired(worker):
                            with self._lock:
                                self._retiring[cid] = worker
            with self._lock:
                primary_admitted = any(worker is self.primary for worker in self._workers.values())
            if self.primary is not None and not primary_admitted:
                self.primary.configure_ai_pipeline({}, enabled=False)
            self._error = None

    def service(self, camera_id):
        with self._lock:
            return self._workers.get(int(camera_id))

    @contextmanager
    def metadata_change(self):
        """Serialize metadata commits against reservations and supervisor reads."""
        with self._changes:
            yield

    def refresh_metadata(self):
        """Update existing owners only; never admit, stop or reserve a worker."""
        with self._changes:
            rows, contexts = self._configuration()
            with self._lock:
                owners = dict(self._workers)
                self._requested = contexts
            for cid, worker in owners.items():
                if cid in rows and cid in contexts and self._signatures.get(cid) == _signature(rows[cid], contexts[cid]):
                    worker.refresh_ai_metadata(contexts[cid])
            if self.primary is not None and self.primary not in owners.values():
                from .camera_profiles import normalize_camera_source
                source = normalize_camera_source(self.primary.current_source_identity())
                for cid, row in rows.items():
                    if normalize_camera_source(str(row.get("source") or "")) == source:
                        self.primary.set_source_label(contexts.get(cid, {}).get("camera_name"))
                        break

    def context(self, camera_id):
        with self._lock:
            value = self._requested.get(int(camera_id))
            return dict(value) if value else None

    def camera_state(self, camera_id):
        cid = int(camera_id)
        with self._lock:
            context = self._requested.get(cid, {})
            worker = self._workers.get(cid)
            retiring = cid in self._retiring
            failure = self._failures.get(cid)
        if not context.get("ai_enabled"):
            return {"ai_state": "DISABLED", "ai_admitted": False}
        if not context.get("enabled") or not context.get("store_id") or not context.get("zone_name"):
            return {"ai_state": "OFFLINE", "ai_admitted": False, "reason_code": "CAMERA_NOT_READY"}
        if worker is None:
            if failure == "AI_WORKER_START_FAILED":
                return {"ai_state": "OFFLINE", "ai_admitted": False, "reason_code": failure}
            return {"ai_state": "WAITING_FOR_CAPACITY", "ai_admitted": False,
                    "reason_code": "RETIREMENT_PENDING" if retiring else failure or "CAPACITY_WAIT"}
        status = worker.status()
        live = bool(status.get("opened")) and status.get("state") == "online"
        perf = worker.performance_status() if hasattr(worker, "performance_status") else {}
        load = str(perf.get("load_state") or "NORMAL")
        error = "AI_PROCESS_FAILED" if status.get("ai_error_code") == "AI_PROCESS_FAILED" else ""
        paused = bool(status.get("ai_paused") or status.get("recognition_paused"))
        successes = status.get("ai_successful_results_current_source")
        if not live:
            state, reason = "OFFLINE", "CAMERA_NOT_READY"
        elif error:
            state, reason = "ERROR", error
        elif paused:
            state, reason = "PAUSED", "AI_PAUSED"
        elif successes == 0:
            state, reason = "STARTING", "AI_STARTING"
        else:
            state, reason = "ACTIVE", ""
        out = {"ai_state": state, "ai_admitted": True,
               "online": live, "ai_error_code": error,
               "ai_successful_results_current_source": successes,
               "overload_state": "OVERLOAD" if load == "HIGH" else
               "BUSY" if load in {"BUSY", "RECOVERING"} else "NORMAL"}
        if reason:
            out["reason_code"] = reason
        return out

    def status(self):
        with self._lock:
            ids = list(self._requested)
            admitted = len(self._workers)
            retiring = len(self._retiring)
        return {"capacity": self.capacity, "admitted": admitted, "retiring": retiring,
                "frame_policy": "LATEST_FRAME_DROP_STALE", "background_owned": True,
                "faceid_concurrency": FACEID_CONCURRENCY, "pad_concurrency": PAD_CONCURRENCY,
                "max_tracks_per_camera": MAX_ACTIVE_TRACKS,
                "items": [{"camera_id": cid, **self.camera_state(cid)} for cid in ids]}

    @contextmanager
    def reserve_camera(self, camera_id):
        if camera_id is None:
            yield
            return
        cid = int(camera_id)
        with self._changes:
            self._reserved.add(cid)
            with self._lock:
                if cid in self._workers or cid in self._retiring:
                    self._reservation_slots.add(cid)
            if not self._retire(cid):
                self._reserved.discard(cid)
                self._reservation_slots.discard(cid)
                raise RuntimeError("AI_RETIRE_PENDING")
        try:
            yield
        finally:
            with self._changes:
                self._reserved.discard(cid)
                self._reservation_slots.discard(cid)

    def start(self):
        with self._changes:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self.reconcile()
            self._thread = threading.Thread(target=self._run, name="btmh-ai-camera-supervisor", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.wait(RECONCILE_SECONDS):
            try:
                self.reconcile()
            except Exception:
                self._error = "AI_CONFIGURATION_UNAVAILABLE"

    def stop(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3.)
        with self._changes:
            with self._lock:
                ids = set(self._workers) | set(self._retiring)
            for cid in ids:
                self._retire(cid)

    def purge_student(self, student_id):
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.purge_student(student_id)
            engine = getattr(worker, "_walkby", None)
            if engine is not None:
                engine.purge_student(student_id)
