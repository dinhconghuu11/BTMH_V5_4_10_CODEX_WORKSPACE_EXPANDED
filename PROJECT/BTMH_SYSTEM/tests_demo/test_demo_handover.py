"""Focused handover gate tests: real mixin, fake capture, stdlib only.

No camera/model imports, decoder subprocesses, credentials, or runtime DB.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "btmh_demo_handover_test"
package = ModuleType(PACKAGE)
package.__path__ = [str(SOURCE_ROOT / "module_app")]
sys.modules[PACKAGE] = package
config = ModuleType(f"{PACKAGE}.config")
config.CAMERA_MODE = "service"
sys.modules[config.__name__] = config
capture = ModuleType(f"{PACKAGE}.capture_session_v544")
capture.CaptureSession = object
capture.ERRORS = {code: code for code in (
    "BUSY", "OPEN_FAILED", "START_FAILED", "READ_FAILED", "COMMIT_FAILED",
    "AI_BUSY", "CANCELLED", "DECODER_RETIRE_FAILED", "AUTH_FAILED",
)}
capture.display_source = lambda value: str(value)
capture.valid_source = lambda value: str(value).strip()
sys.modules[capture.__name__] = capture
spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.camera_handover_v544", SOURCE_ROOT / "module_app" / "camera_handover_v544.py",
)
handover = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = handover
spec.loader.exec_module(handover)


class FakeSession:
    def __init__(self, source, *, ready=True, entered=None, release=None):
        self.source = source
        self.ready = ready
        self.closed = False
        self.frame = object()
        self.entered = entered
        self.release = release

    def start(self):
        pass

    def close(self):
        self.closed = True

    def retired(self):
        return self.closed

    def alive(self):
        return not self.closed

    def healthy(self, **_):
        return self.ready and not self.closed

    def snapshot(self):
        return SimpleNamespace(frame=self.frame, seq=10, at=time.perf_counter())

    def metadata(self):
        return {}

    def diagnostics(self, code=None):
        return {"code": code or "READY", "message": "synthetic capture", "stable_frames": 5}

    def wait_ready(self, *_, cancelled=None):
        if self.entered is not None:
            self.entered.set()
        if self.release is not None and not self.release.wait(2):
            raise TimeoutError("test did not release preflight")
        if cancelled and cancelled():
            return {"ok": False, **self.diagnostics("CANCELLED")}
        return {"ok": self.ready, **self.diagnostics("READY" if self.ready else "AUTH_FAILED")}


class CameraHarness(handover.CameraHandoverV544Mixin):
    """Supplies only the host state used by the actual transactional mixin."""

    def __init__(self, candidate, *, failure=None, enabled=True):
        self._lock = threading.RLock()
        self._cap_lock = threading.Lock()
        self._handover_lock = threading.Lock()
        self._ai_work_lock = threading.Lock()
        self._stop = threading.Event()
        self._run_generation = 1
        self._source_epoch = 7
        self._source_override = "0"
        self._source_label_override = "Camera A"
        self._retry_blocked_source = ""
        self._recognition_paused = False
        self._pipeline_enabled = enabled
        self._event_context = {"camera_id": 11, "store_id": 3, "zone_name": "Entry A"}
        self.old = FakeSession("0")
        self._active_session = self.old
        self._cap = self.old
        self._pending_session = None
        self._retiring_sessions = []
        self._frame = self.old.frame
        self._frame_at = 12.0
        self._frame_seq = 4
        self._capture_total = 4
        self._jpeg = b"old-preview"
        self._raw_jpeg = b"old-raw"
        self._observation_jpeg = b"old-observation"
        self._observation_jpeg_seq = 4
        self._observation_jpeg_at = 12.0
        self._status = {"source": "0", "source_label": "Camera A", "opened": True, "running": True}
        self._ptz_state = {"zoom": 2.0, "pan": 0.2}
        self._handover = {"active": False}
        self._capture_plan_cache = {}
        self.candidate = candidate
        self.failure = failure
        self.synced = []

    def _source_value(self):
        return self._source_override

    def event_camera_source(self):
        return self._source_label_override

    def _new_session(self, _):
        return self.candidate

    def _set_handover_state(self, **values):
        self._handover.update(values)

    def _session_runtime(self, _):
        return {"backend": "fake"}

    def _clear_transient_recognition(self, **_):
        if self.failure == "clear":
            raise RuntimeError("synthetic clear failure")

    def _clear_camera_buffers_for_handover(self):
        self._frame = None
        self._jpeg = self._raw_jpeg = self._observation_jpeg = b""

    def _sync_ai_capture_epoch(self):
        self.synced.append((self._source_epoch, self._pipeline_enabled, dict(self._event_context)))

    def _publish_frame(self, frame, at):
        self._frame = frame
        self._frame_at = at
        self._frame_seq += 1
        self._capture_total += 1
        if self.failure == "publish":
            raise RuntimeError("synthetic publish failure")

    def status(self):
        return dict(self._status)

    def ptz_status(self):
        return dict(self._ptz_state)


class HandoverGateTests(unittest.TestCase):
    def test_success_waits_for_supervisor_to_readmit_new_context(self):
        target = FakeSession("1")
        cam = CameraHarness(target)
        result = cam.safe_select_source("1", source_label="Camera B")
        self.assertTrue(result["ok"])
        self.assertIs(cam._active_session, target)
        self.assertIs(cam._cap, target)
        self.assertIs(cam._frame, target.frame)
        self.assertTrue(cam.old.closed)
        self.assertFalse(target.closed)
        self.assertFalse(cam._recognition_paused)
        self.assertFalse(cam._pipeline_enabled)
        self.assertEqual(cam._event_context, {})
        self.assertEqual(cam.synced, [(8, False, {})])

    def test_old_pipeline_and_attribution_continue_through_preflight(self):
        entered, release = threading.Event(), threading.Event()
        target = FakeSession("1", entered=entered, release=release)
        cam = CameraHarness(target)
        context = cam._event_context
        result = {}
        thread = threading.Thread(target=lambda: result.update(cam.safe_select_source("1")))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertIs(cam._active_session, cam.old)
            self.assertTrue(cam._pipeline_enabled)
            self.assertIs(cam._event_context, context)
            self.assertFalse(cam._recognition_paused)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result["ok"])
        self.assertFalse(cam._pipeline_enabled)
        self.assertEqual(cam._event_context, {})

    def test_test_only_keeps_pipeline_and_old_context(self):
        target = FakeSession("1")
        cam = CameraHarness(target)
        context = cam._event_context
        result = cam.test_source("1")
        self.assertTrue(result["ok"])
        self.assertTrue(result["test_only"])
        self.assertIs(cam._active_session, cam.old)
        self.assertTrue(cam._pipeline_enabled)
        self.assertIs(cam._event_context, context)
        self.assertFalse(cam.old.closed)
        self.assertTrue(target.closed)

    def test_bad_preflight_keeps_pipeline_and_old_context(self):
        target = FakeSession("1", ready=False)
        cam = CameraHarness(target)
        context = cam._event_context
        result = cam.safe_select_source("1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "AUTH_FAILED")
        self.assertIs(cam._active_session, cam.old)
        self.assertTrue(cam._pipeline_enabled)
        self.assertIs(cam._event_context, context)
        self.assertFalse(cam.old.closed)
        self.assertTrue(target.closed)

    def test_failed_commit_restores_open_source_context_and_buffers(self):
        for failure in ("clear", "publish"):
            with self.subTest(failure=failure):
                target = FakeSession("1")
                cam = CameraHarness(target, failure=failure)
                context = cam._event_context
                old_status = cam.status()
                old_ptz = cam.ptz_status()
                result = cam.safe_select_source("1")
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "COMMIT_FAILED")
                self.assertTrue(result["kept_previous"])
                self.assertIs(cam._active_session, cam.old)
                self.assertIs(cam._cap, cam.old)
                self.assertIs(cam._frame, cam.old.frame)
                self.assertFalse(cam.old.closed)
                self.assertTrue(target.closed)
                self.assertTrue(cam._pipeline_enabled)
                self.assertIs(cam._event_context, context)
                self.assertFalse(cam._recognition_paused)
                self.assertEqual(cam._source_override, "0")
                self.assertEqual(cam._jpeg, b"old-preview")
                self.assertEqual(cam._frame_seq, 4)
                self.assertEqual(cam._capture_total, 4)
                self.assertEqual(cam.ptz_status(), old_ptz)
                for key, value in old_status.items():
                    self.assertEqual(cam.status()[key], value)
                self.assertEqual(cam.synced[-1][1:], (True, context))

    def test_failed_commit_preserves_previously_disabled_gate(self):
        target = FakeSession("1")
        cam = CameraHarness(target, failure="publish", enabled=False)
        context = cam._event_context
        result = cam.safe_select_source("1")
        self.assertEqual(result["code"], "COMMIT_FAILED")
        self.assertFalse(cam._pipeline_enabled)
        self.assertIs(cam._event_context, context)
        self.assertIs(cam._active_session, cam.old)
        self.assertFalse(cam.old.closed)
        self.assertTrue(target.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
