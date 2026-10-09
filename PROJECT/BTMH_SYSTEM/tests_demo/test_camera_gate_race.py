"""Run the production AI loop/handover methods against fake dependencies.

Only the selected StaticCameraService methods are compiled from its actual AST,
avoiding the module-level CAMERA singleton/model imports. The test coordinates a
real thread waiting on the real work lock; it does not copy the gate condition.
"""
from __future__ import annotations

import ast
from collections import deque
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
import uuid

from test_demo_handover import CameraHarness, FakeSession, PACKAGE


@contextmanager
def event_context(_):
    yield


class FakeAppearances:
    @contextmanager
    def frame(self, *_):
        yield SimpleNamespace(prepare=lambda *args: {}, annotate=lambda result: result)


for name, values in (
    ("demo_context", {"camera_event_context": event_context}),
    ("camera_appearances", {"APPEARANCES": FakeAppearances()}),
    ("ai_camera_runtime", {"MAX_ACTIVE_TRACKS": 32, "budgeted_inference": lambda kind, infer: infer}),
):
    module = ModuleType(PACKAGE + "." + name)
    module.__dict__.update(values)
    sys.modules[module.__name__] = module


source_path = Path(__file__).resolve().parents[1] / "module_app" / "camera.py"
tree = ast.parse(source_path.read_text(encoding="utf-8"), str(source_path))
camera_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StaticCameraService")
methods = [node for node in camera_class.body if isinstance(node, ast.FunctionDef) and
           node.name in {"_ai_loop", "_run_is_active", "configure_ai_pipeline", "_publish_frame", "status"}]
camera_class.bases, camera_class.keywords, camera_class.decorator_list, camera_class.body = [], [], [], methods
selected = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), camera_class], type_ignores=[])
ast.fix_missing_locations(selected)
namespace = {"__name__": PACKAGE + ".camera_loop_test", "__package__": PACKAGE,
             "time": time, "uuid": uuid, "datetime": datetime, "timezone": timezone, "nullcontext": nullcontext,
             "cfg": SimpleNamespace(AI_ASYNC_ENABLED=True),
             "np": SimpleNamespace(float32=float, percentile=lambda values, percentile: 0.0,
                                   asarray=lambda values, dtype=None: SimpleNamespace(mean=lambda: 0.0)),
             "AI_TARGET_FPS": 100., "OBSERVATION_FACE_AI_FPS": 100., "RTSP_AI_TARGET_FPS": 100.,
             "RTSP_AI_WIDTH": 640, "OBSERVATION_FACE_AI_WIDTH": 640, "AI_WIDTH": 640,
             "AI_NATIVE_FRAME": True, "AI_NATIVE_MAX_WIDTH": 2048,
             "OBSERVATION_MAX_FACES": 8, "OBSERVATION_IDENTITY_BUDGET": 8}
exec(compile(selected, str(source_path), "exec"), namespace)
ProductionCamera = namespace["StaticCameraService"]


class ObservedLock:
    def __init__(self):
        self.lock = threading.RLock()
        self.attempted, self.acquired = threading.Event(), threading.Event()

    def acquire(self, blocking=True, timeout=-1):
        ai_thread = threading.current_thread().name == "test-ai-loop"
        if ai_thread:
            self.attempted.set()
        acquired = self.lock.acquire(blocking, timeout)
        if acquired and ai_thread:
            self.acquired.set()
        return acquired

    def release(self):
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


class FakeFrame:
    shape = (240, 320, 3)

    def copy(self):
        return self


class LoopHarness(CameraHarness):
    _ai_loop = ProductionCamera._ai_loop
    _run_is_active = ProductionCamera._run_is_active
    configure_ai_pipeline = ProductionCamera.configure_ai_pipeline

    def __init__(self):
        candidate = FakeSession("1")
        candidate.frame = FakeFrame()
        super().__init__(candidate)
        self._ai_work_lock = ObservedLock()
        self._ai_session_id = "camera-11"
        self._appearance_owner = "owner-A"
        self._enrollment_hold_until = 0.0
        self._ptz_guard_until = 0.0
        self._observation_mode = False
        self._frame = FakeFrame()
        self._status["dropped_for_ai"] = 0
        self._status["ai_error_code"] = ""
        self._status["ai_successful_results_current_source"] = 0
        self._ai_total = 0
        self._ai_result_at = 0.0
        self._ai_result_source_epoch = self._ai_error_source_epoch = -1
        self._latencies = deque(maxlen=16)
        self._recent_events = deque(maxlen=16)
        self.packet_entered, self.completed = threading.Event(), threading.Event()
        self.reader_calls = 0
        self.model_calls, self.event_writes, self.reset_calls = [], [], []
        self._walkby = SimpleNamespace(reset=lambda session: self.reset_calls.append(session),
                                       configure_resource_limits=lambda *args: None, process=self._process)
        self._business_consumer = self.consumer

    def _performance_target_fps(self, *_):
        return 100.

    def _is_network_source(self, _):
        return False

    def _resize_for_ai(self, frame, _):
        return frame

    def _ai_input_packet(self):
        self.reader_calls += 1
        self.packet_entered.set()
        return self._frame, self.reader_calls, time.perf_counter(), self._source_epoch, "FAKE_LATEST"

    def _ai_evidence_provider(self, **_):
        return None

    def _process(self, *_, **kwargs):
        camera_id = self._event_context.get("camera_id")
        self.model_calls.append(camera_id)
        self.event_writes.append(camera_id)
        if kwargs.get("appearance_observer"):
            kwargs["appearance_observer"]([], 320, 240)
        return {"ok": True, "tracks": [], "events": [{"id": 7}], "frame_width": 320, "frame_height": 240}

    def consumer(self, context, result, observed_at):
        self.completed.set()
        self._stop.set()


class CameraGateRaceTests(unittest.TestCase):
    def run_change_while_waiting(self, change, *, readmit=True):
        cam = LoopHarness()
        cam._ai_work_lock.acquire()
        thread = threading.Thread(target=cam._ai_loop, args=(1,), name="test-ai-loop")
        thread.start()
        try:
            self.assertTrue(cam._ai_work_lock.attempted.wait(1), "loop did not reach work-lock wait")
            change(cam)
        finally:
            cam._ai_work_lock.release()
        try:
            self.assertTrue(cam._ai_work_lock.acquired.wait(1), "waiting loop did not resume")
            self.assertFalse(cam.packet_entered.wait(.12), "disabled/stale loop read the new source")
            self.assertEqual(cam.reader_calls, 0)
            self.assertEqual(cam.model_calls, [])
            self.assertEqual(cam.event_writes, [])
            if readmit:
                with cam._lock:
                    cam._ptz_guard_until = cam._enrollment_hold_until = 0.0
                cam.configure_ai_pipeline({"camera_id": 12, "store_id": 4, "zone_name": "Entry B"},
                                          enabled=True, consumer=cam.consumer)
                self.assertTrue(cam.completed.wait(1), "readmitted backend worker did not process")
                self.assertEqual(cam.model_calls, [12])
                self.assertEqual(cam.event_writes, [12])
        finally:
            cam._stop.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_actual_handover_commit_while_loop_waits_requires_readmission(self):
        def handover(cam):
            result = cam.safe_select_source("1", source_label="Camera B")
            self.assertTrue(result["ok"])
            self.assertFalse(cam._pipeline_enabled)
            self.assertEqual(cam._event_context, {})
        self.run_change_while_waiting(handover)

    def test_actual_configuration_disable_while_loop_waits_requires_readmission(self):
        self.run_change_while_waiting(lambda cam: cam.configure_ai_pipeline({}, enabled=False))

    def test_new_hold_and_ptz_guard_while_waiting_prevent_reader_and_inference(self):
        for field in ("_enrollment_hold_until", "_ptz_guard_until"):
            with self.subTest(field=field):
                self.run_change_while_waiting(lambda cam: setattr(cam, field, time.perf_counter() + 10))

    def test_stale_run_generation_while_waiting_cannot_process(self):
        self.run_change_while_waiting(lambda cam: setattr(cam, "_run_generation", 2), readmit=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
