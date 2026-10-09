"""Real camera loop/status methods with inert frames and no database/models."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import threading
import time
import unittest

from test_camera_gate_race import LoopHarness, ProductionCamera


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("btmh_status_runtime", ROOT / "module_app" / "ai_camera_runtime.py")
runtime_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_module)


class TelemetryCamera(LoopHarness):
    _publish_frame = ProductionCamera._publish_frame
    status = ProductionCamera.status

    def __init__(self):
        super().__init__()
        self._status.update(state="online", opened=True, ai_fps=0.0)
        self._frame_at = time.perf_counter()
        self._performance_effective_fps = 100.

    def _reconcile_stale_pause(self):
        pass

    def _apply_digital_ptz(self, frame):
        return frame

    def performance_status(self):
        return {"effective_target_fps": 100., "load_state": "NORMAL", "drop_ratio": 0.,
                "ptz_guard_active": False, "ptz_guard_remaining_ms": 0, "ai_total": self._ai_total}


def state_for(camera):
    runtime = runtime_module.CameraAIRuntime()
    runtime._requested[11] = {"camera_id": 11, "enabled": True, "ai_enabled": True,
                              "store_id": 3, "zone_name": "Entry A"}
    runtime._workers[11] = camera
    return runtime.camera_state(11)


class AIStatusTests(unittest.TestCase):
    def run_loop(self, camera):
        thread = threading.Thread(target=camera._ai_loop, args=(1,), name="test-ai-telemetry")
        thread.start()
        thread.join(3.)
        if thread.is_alive():
            camera._stop.set()
            thread.join(1.)
            self.fail("isolated AI loop did not stop")

    def test_new_source_is_starting_until_first_success_even_with_live_video(self):
        camera = TelemetryCamera()
        self.assertEqual(state_for(camera)["ai_state"], "STARTING")

    def test_failed_inference_persists_through_new_video_frames(self):
        camera = TelemetryCamera()
        def fail(*_, **__):
            camera._stop.set()
            raise RuntimeError("private model details")
        camera._walkby.process = fail
        self.run_loop(camera)
        self.assertEqual(camera.status()["ai_error_code"], "AI_PROCESS_FAILED")
        camera._publish_frame(camera._frame, time.perf_counter())
        self.assertEqual(camera.status()["error"], "")
        state = state_for(camera)
        self.assertEqual(state["ai_state"], "ERROR")
        self.assertEqual(state["ai_error_code"], "AI_PROCESS_FAILED")
        self.assertNotIn("private", str(state))
        self.assertEqual(camera._ai_total, 0)
        self.assertEqual(state["ai_successful_results_current_source"], 0)

    def test_failed_attempts_do_not_count_as_completed_ai_fps(self):
        camera = TelemetryCamera()
        calls = []
        def fail(*_, **__):
            calls.append(1)
            if len(calls) == 1:
                time.sleep(1.05)  # Cross the production FPS measurement boundary.
            camera._stop.set()
            raise RuntimeError("inert detector failure")
        camera._walkby.process = fail
        self.run_loop(camera)
        self.assertEqual(len(calls), 1)
        self.assertEqual(camera._status["ai_fps"], 0.)
        self.assertEqual(camera._ai_total, 0)

    def test_empty_successful_scene_is_active_and_records_success_without_consumer(self):
        camera = TelemetryCamera()
        camera._business_consumer = None
        # Stop only after publication; generation guard checks _stop.
        def packet():
            if camera.reader_calls:
                camera._stop.set()
                return None, 1, time.perf_counter(), camera._source_epoch, "FAKE_LATEST"
            camera.reader_calls += 1
            return camera._frame, 1, time.perf_counter(), camera._source_epoch, "FAKE_LATEST"
        camera._ai_input_packet = packet
        camera._walkby.process = lambda *a, **k: {"ok": True, "tracks": [], "events": [], "face_count": 0}
        self.run_loop(camera)
        self.assertGreater(camera._ai_result_at, 0.)
        self.assertEqual(camera._ai_total, 1)
        self.assertEqual(camera._status["visible_faces"], 0)
        self.assertEqual(state_for(camera)["ai_state"], "ACTIVE")

    def test_success_clears_ai_error_without_clearing_capture_error(self):
        camera = TelemetryCamera()
        camera._status["error"] = "capture warning"
        camera._status["ai_error_code"] = "AI_PROCESS_FAILED"
        camera._ai_error_source_epoch = camera._source_epoch
        self.run_loop(camera)
        self.assertEqual(camera._status["ai_error_code"], "")
        self.assertEqual(camera._status["error"], "capture warning")
        self.assertEqual(state_for(camera)["ai_state"], "ACTIVE")

    def test_paused_recognition_enrollment_and_ptz_are_not_active(self):
        for field, value in (("_recognition_paused", True), ("_enrollment_hold_until", time.perf_counter() + 10),
                             ("_ptz_guard_until", time.perf_counter() + 10)):
            with self.subTest(field=field):
                camera = TelemetryCamera()
                camera._ai_result_source_epoch = camera._source_epoch
                camera._status["ai_successful_results_current_source"] = 1
                setattr(camera, field, value)
                self.assertEqual(state_for(camera)["ai_state"], "PAUSED")

    def test_source_epoch_change_cannot_inherit_previous_success_or_error(self):
        camera = TelemetryCamera()
        self.run_loop(camera)
        self.assertEqual(state_for(camera)["ai_state"], "ACTIVE")
        camera._status["ai_error_code"] = "AI_PROCESS_FAILED"
        camera._ai_error_source_epoch = camera._source_epoch
        lifetime_total = camera._ai_total
        camera._source_epoch += 1
        state = state_for(camera)
        self.assertEqual(state["ai_state"], "STARTING")
        self.assertEqual(state["ai_successful_results_current_source"], 0)
        self.assertEqual(state["ai_error_code"], "")
        self.assertEqual(camera._ai_total, lifetime_total)

    def test_context_change_resets_current_success_without_resetting_lifetime_total(self):
        camera = TelemetryCamera()
        self.run_loop(camera)
        self.assertEqual(camera._ai_total, 1)
        camera.configure_ai_pipeline({"camera_id": 11, "store_id": 4, "zone_name": "Entry B"}, enabled=True)
        self.assertEqual(camera.status()["ai_successful_results_current_source"], 0)
        self.assertEqual(camera._ai_result_at, 0.)
        self.assertEqual(camera._ai_total, 1)
        self.assertEqual(state_for(camera)["ai_state"], "STARTING")

    def test_discarded_generation_does_not_become_successful_inference(self):
        camera = TelemetryCamera()
        camera._walkby.process = lambda *a, **k: {"ok": True, "tracks": [], "events": [], "discarded_generation": True}
        def packet():
            if camera.reader_calls:
                camera._stop.set()
                return None, 1, time.perf_counter(), camera._source_epoch, "FAKE_LATEST"
            camera.reader_calls += 1
            return camera._frame, 1, time.perf_counter(), camera._source_epoch, "FAKE_LATEST"
        camera._ai_input_packet = packet
        self.run_loop(camera)
        self.assertEqual(camera._ai_total, 0)
        self.assertEqual(state_for(camera)["ai_state"], "STARTING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
