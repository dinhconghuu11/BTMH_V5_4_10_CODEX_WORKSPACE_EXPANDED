"""Deterministic supervisor/lifecycle tests; no model, decoder or customer DB."""
import importlib.util
from pathlib import Path
import sys
import threading
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("module_app")
package.__path__ = [str(ROOT / "module_app")]
sys.modules.setdefault("module_app", package)
profiles = types.ModuleType("module_app.camera_profiles")
profiles.normalize_camera_source = lambda value: str(value).strip()
sys.modules[profiles.__name__] = profiles
from module_app.ai_camera_runtime import CameraAIRuntime, budgeted_inference, _MODEL_BUDGETS
from module_app.ai_pipeline_v550 import LatestBatchLane, InferenceJob


class FakeCamera:
    def __init__(self, source="1"):
        self.source = source
        self.opened = False
        self.started = self.stopped = 0
        self.blocked = False
        self.enabled = False
        self.context = {}
    def start(self):
        self.started += 1
        self.opened = True
    def stop(self):
        self.stopped += 1
        self.opened = False
    def status(self):
        return {"opened": self.opened, "state": "online" if self.opened else "offline",
                "safe_decoder_shutdown": not self.blocked}
    def current_source_identity(self):
        return self.source
    def configure_ai_pipeline(self, context, *, enabled, consumer=None):
        self.context, self.enabled = dict(context), enabled
    def performance_status(self):
        return {"load_state": "HIGH" if self.blocked else "NORMAL"}


class RuntimeTests(unittest.TestCase):
    def make(self, count=6, primary=None):
        rows = [{"id": i, "source": str(i)} for i in range(1, count + 1)]
        contexts = [{"camera_id": i, "camera_name": f"Device {i}", "store_id": 1,
                     "zone_name": "Entry", "enabled": True, "ai_enabled": True} for i in range(1, count + 1)]
        made = []
        def factory(row, context):
            camera = FakeCamera(row["source"])
            camera.configure_ai_pipeline(context, enabled=True)
            made.append(camera)
            return camera
        runtime = CameraAIRuntime(primary, rows=lambda: rows, contexts=lambda: contexts, worker_factory=factory)
        return runtime, rows, contexts, made

    def test_four_admissions_and_waiting_registry_not_limited(self):
        runtime, _, _, made = self.make()
        runtime.reconcile()
        self.assertEqual(runtime.status()["admitted"], 4)
        self.assertEqual(len(runtime.status()["items"]), 6)
        self.assertEqual(runtime.camera_state(5)["ai_state"], "WAITING_FOR_CAPACITY")
        self.assertEqual(len(made), 4)
        owners = [runtime.service(i) for i in range(1, 5)]
        runtime.reconcile()
        self.assertEqual(owners, [runtime.service(i) for i in range(1, 5)])

    def test_primary_counts_towards_four_and_is_reused(self):
        primary = FakeCamera("1")
        primary.start()
        runtime, _, _, made = self.make(primary=primary)
        runtime.reconcile()
        self.assertIs(runtime.service(1), primary)
        self.assertEqual(len(made), 3)
        self.assertTrue(primary.enabled)
        self.assertEqual(primary.started, 1)

    def test_disable_admits_waiting_without_changing_other_owners(self):
        runtime, _, contexts, _ = self.make()
        runtime.reconcile()
        owner = runtime.service(2)
        removed = runtime.service(1)
        contexts[0]["ai_enabled"] = False
        runtime.reconcile()
        self.assertEqual(runtime.camera_state(1)["ai_state"], "DISABLED")
        self.assertIs(runtime.service(2), owner)
        self.assertIsNotNone(runtime.service(5))
        self.assertEqual(removed.stopped, 1)

    def test_store_or_source_change_retires_only_changed_worker(self):
        runtime, rows, contexts, _ = self.make()
        runtime.reconcile()
        old, other = runtime.service(1), runtime.service(2)
        contexts[0]["store_id"] = 2
        rows[0]["source"] = "changed"
        runtime.reconcile()
        self.assertEqual(old.stopped, 1)
        self.assertIsNot(runtime.service(1), old)
        self.assertIs(runtime.service(2), other)
        self.assertEqual(runtime.service(1).context["store_id"], 2)

    def test_failed_retirement_keeps_capacity_reserved(self):
        runtime, _, contexts, _ = self.make()
        runtime.reconcile()
        old = runtime.service(1)
        old.blocked = True
        contexts[0]["ai_enabled"] = False
        runtime.reconcile()
        self.assertEqual(runtime.status()["retiring"], 1)
        self.assertIsNone(runtime.service(5))
        old.blocked = False
        runtime.reconcile()
        self.assertIsNotNone(runtime.service(5))

    def test_camera_open_failure_is_offline_not_fake_active(self):
        runtime, _, _, _ = self.make(1)
        runtime._factory = lambda *args: (_ for _ in ()).throw(RuntimeError("private raw error"))
        runtime.reconcile()
        self.assertEqual(runtime.camera_state(1)["ai_state"], "OFFLINE")
        self.assertNotIn("private", str(runtime.status()))

    def test_background_start_needs_no_browser_or_display_slots(self):
        runtime, _, _, made = self.make()
        runtime.start()
        self.assertTrue(runtime._thread.is_alive())
        self.assertEqual(runtime.status()["admitted"], 4)
        self.assertTrue(all(camera.opened for camera in made))
        runtime.stop()
        self.assertFalse(runtime._thread.is_alive())
        self.assertTrue(all(camera.stopped == 1 for camera in made))

    def test_primary_switch_reservation_never_duplicates_decoder(self):
        runtime, _, _, _ = self.make()
        runtime.reconcile()
        old = runtime.service(2)
        with runtime.reserve_camera(2):
            runtime.reconcile()
            self.assertIsNone(runtime.service(2))
            self.assertEqual(old.stopped, 1)
        runtime.reconcile()
        self.assertIsNotNone(runtime.service(2))

    def test_missing_store_or_zone_is_not_ai_active(self):
        runtime, _, contexts, _ = self.make(2)
        contexts[0]["store_id"] = None
        contexts[1]["zone_name"] = ""
        runtime.reconcile()
        self.assertEqual(runtime.status()["admitted"], 0)
        self.assertEqual(runtime.camera_state(1)["ai_state"], "OFFLINE")

    def test_busy_model_budget_fails_closed_without_backlog(self):
        budget = _MODEL_BUDGETS["faceid"]
        taken = []
        while budget.acquire(blocking=False):
            taken.append(True)
        called = []
        try:
            inference = budgeted_inference("faceid", lambda job: called.append(job))
            with self.assertRaisesRegex(RuntimeError, "AI_BUDGET_BUSY"):
                inference(types.SimpleNamespace(captured_at=time.perf_counter()))
            self.assertEqual(called, [])
        finally:
            for _ in taken:
                budget.release()

    def test_latest_batch_replaces_old_pending_and_has_finite_depth(self):
        entered, finish = threading.Event(), threading.Event()
        seen = []
        def infer(job):
            seen.append(job.seq)
            if job.seq == 1:
                entered.set()
                finish.wait(1.)
            return job.seq
        lane = LatestBatchLane("demo-bounded", infer)
        def job(seq):
            return InferenceJob("camera-1", 1, 1, seq, time.perf_counter(), time.time(), None, None)
        try:
            lane.submit([job(1)])
            self.assertTrue(entered.wait(.5))
            for seq in range(2, 30):
                lane.submit([job(seq)])
                self.assertLessEqual(lane.status()["pending"], 1)
            finish.set()
            deadline = time.monotonic() + 1.
            while lane.status()["busy"] or lane.status()["pending"]:
                if time.monotonic() > deadline:
                    self.fail("bounded lane did not drain")
                time.sleep(.005)
            self.assertEqual(seen, [1, 29])
            self.assertGreaterEqual(lane.status()["dropped"], 27)
        finally:
            finish.set()
            lane.shutdown()

    def test_invalidated_inflight_result_never_becomes_current_identity(self):
        entered, finish = threading.Event(), threading.Event()
        def infer(job):
            entered.set()
            finish.wait(1.)
            return "old identity"
        lane = LatestBatchLane("demo-generation", infer)
        job = InferenceJob("camera-1", 7, 1, 1, time.perf_counter(), time.time(), None, None)
        try:
            lane.submit([job])
            self.assertTrue(entered.wait(.5))
            lane.invalidate("camera-1", 7)
            finish.set()
            deadline = time.monotonic() + 1.
            while lane.status()["busy"]:
                if time.monotonic() > deadline:
                    self.fail("invalidated call did not retire")
                time.sleep(.005)
            self.assertEqual(lane.drain("camera-1", 7), [])
        finally:
            finish.set()
            lane.shutdown()


if __name__ == "__main__":
    unittest.main()
