"""Primary camera ownership, stop and handover contracts with fake decoders."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from module_app import camera_handover_v544 as handover
from module_app.camera import StaticCameraService
from module_app.capture_session_v544 import FramePacket
from module_app.walkby import WALKBY


class Session:
    def __init__(self, source, *, close_fails=False, start_fails=False):
        self.source = source
        self.close_fails = close_fails
        self.start_fails = start_fails
        self.closed = False
        self.close_calls = 0
        self.started_at = time.perf_counter()
        self.image = np.zeros((120, 160, 3), np.uint8)
        self.packet = FramePacket(self.image, 1, time.perf_counter())

    def start(self):
        if self.start_fails:
            raise RuntimeError("private decoder exception")

    def close(self):
        self.close_calls += 1
        if self.close_fails:
            raise RuntimeError("private decoder exception")
        self.closed = True

    def retired(self):
        return self.closed

    def alive(self):
        return not self.closed

    def healthy(self, **_):
        return not self.closed

    def snapshot(self):
        return self.packet

    def metadata(self):
        return {"backend": "fake", "transport": "tcp"}

    def get(self, prop):
        return 25 if prop == 5 else 0

    def diagnostics(self, code=None):
        return {"code": code or "READY", "message": "test diagnostic", "width": 160,
                "height": 120, "observed_fps": 25, "transport": "tcp", "stable_frames": 5}

    def wait_ready(self, *args, **kwargs):
        return {"ok": True, **self.diagnostics("READY")}


class ThreadHandle:
    def __init__(self, *, name="cf-camera-ai", alive=False, stop_on_join=False, **_):
        self.name = name
        self.live = alive
        self.stop_on_join = stop_on_join
        self.started = False

    def start(self):
        self.started = self.live = True

    def is_alive(self):
        return self.live

    def join(self, timeout):
        if self.stop_on_join:
            self.live = False


@pytest.fixture
def primary(monkeypatch):
    cam = StaticCameraService()
    old = Session("0")
    cam.configure_source("0", "Laptop")
    cam._active_session = cam._cap = old
    cam._publish_frame(old.image, old.packet.at)
    cam._status.update(running=True, opened=True, state="online")
    monkeypatch.setattr(handover.cfg, "CAMERA_MODE", "service")
    monkeypatch.setattr(cam, "_clear_transient_recognition", lambda **kw: None)
    monkeypatch.setattr(cam, "_sync_ai_capture_epoch", lambda: None)
    monkeypatch.setattr(cam, "_set_placeholder", lambda message: None)
    monkeypatch.setattr(cam, "_ai_capture", SimpleNamespace(stop=lambda: None, start=lambda: None, status=lambda: {}))
    monkeypatch.setattr(WALKBY, "shutdown", lambda key: None)
    yield cam, old
    for session in [cam._active_session, cam._pending_session, *getattr(cam, "_retiring_sessions", [])]:
        if session is not None:
            session.close_fails = False
    for thread in cam._threads:
        if isinstance(thread, ThreadHandle):
            thread.live = False
    cam.stop()


def _fake_threads(monkeypatch):
    created = []

    def create(**kwargs):
        thread = ThreadHandle(stop_on_join=True, **kwargs)
        created.append(thread)
        return thread

    monkeypatch.setattr(handover.threading, "Thread", create)
    return created


def test_stop_keeps_unretired_child_and_start_waits_for_exit(primary, monkeypatch):
    cam, old = primary
    old.close_fails = True
    created = _fake_threads(monkeypatch)
    cam.stop()
    assert cam._active_session is old and old in cam._retiring_sessions
    assert cam._cap is None and cam._status["recovery_blocked"]
    cam.start()
    assert not created and cam._stop.is_set()
    old.close_fails = False
    cam.start()
    assert old.retired() and cam._active_session is None and not cam._retiring_sessions
    assert len(created) == 3 and all(thread.started for thread in created)
    assert not cam._status["recovery_blocked"]


def test_stop_keeps_any_live_worker_and_never_duplicates_ai_or_preview(primary, monkeypatch):
    cam, old = primary
    lingering = ThreadHandle(name="cf-camera-ai", alive=True)
    cam._threads = [lingering]
    created = _fake_threads(monkeypatch)
    cam.stop()
    assert old.retired() and cam._threads == [lingering]
    cam.start()
    assert not created and cam._stop.is_set()
    lingering.live = False
    cam.start()
    assert len(created) == 3 and lingering not in cam._threads


def test_committed_handover_retirement_failure_is_warning_and_blocks_next_owner(primary, monkeypatch):
    cam, old = primary
    old.close_fails = True
    candidate = Session("1")
    opened = []

    def create(source):
        opened.append(source)
        return candidate

    monkeypatch.setattr(cam, "_new_session", create)
    result = cam.safe_select_source("1", source_label="Second")
    assert result["ok"] and not result["rolled_back"]
    assert result["retirement_warning"] == "DECODER_RETIRE_FAILED"
    assert cam._active_session is candidate and cam._cap is candidate and not candidate.closed
    assert old in cam._retiring_sessions
    cam._status.update(cam._session_runtime(candidate))
    assert not cam._status["safe_decoder_shutdown"]
    blocked = cam.safe_select_source("0")
    assert not blocked["ok"] and blocked["code"] == "DECODER_RETIRE_FAILED"
    assert opened == ["1"] and cam._active_session is candidate

    old.close_fails = False
    replacement = Session("0")
    monkeypatch.setattr(cam, "_new_session", lambda source: replacement)
    assert cam.safe_select_source("0")["ok"]
    assert old.retired() and candidate.retired() and cam._active_session is replacement
    assert cam._session_runtime(replacement)["safe_decoder_shutdown"]


def test_test_source_never_passes_if_candidate_cannot_retire(primary, monkeypatch):
    cam, old = primary
    candidate = Session("1", close_fails=True)
    monkeypatch.setattr(cam, "_new_session", lambda source: candidate)
    result = cam.test_source("1")
    assert not result["ok"] and result["code"] == "DECODER_RETIRE_FAILED"
    assert cam._active_session is old and not old.closed
    assert cam._pending_session is candidate and candidate in cam._retiring_sessions
    assert cam._handover_lock.acquire(blocking=False)
    cam._handover_lock.release()


def test_candidate_start_and_retirement_failures_keep_owner_and_release_handover(primary, monkeypatch):
    cam, old = primary
    candidate = Session("1", start_fails=True, close_fails=True)
    monkeypatch.setattr(cam, "_new_session", lambda source: candidate)
    result = cam.safe_select_source("1")
    assert not result["ok"] and result["code"] == "START_FAILED"
    assert cam._pending_session is candidate and candidate in cam._retiring_sessions
    assert cam._active_session is old and not old.closed
    assert cam._handover_lock.acquire(blocking=False)
    cam._handover_lock.release()
    monkeypatch.setattr(cam, "_new_session", lambda source: pytest.fail("opened another candidate while failed owner retained"))
    assert cam.safe_select_source("2")["code"] == "DECODER_RETIRE_FAILED"


def test_capture_recovery_retains_failed_child_and_does_not_spawn_replacement(primary, monkeypatch):
    cam, old = primary
    old.packet = FramePacket(None, 0, 0)
    old.started_at = time.perf_counter() - 25

    def refuse_close():
        old.close_calls += 1
        cam._stop.set()
        raise RuntimeError("private decoder exception")

    monkeypatch.setattr(old, "close", refuse_close)
    monkeypatch.setattr(cam, "_new_session", lambda source: pytest.fail("replacement opened before retirement proof"))
    cam._capture_loop(cam._run_generation)
    assert cam._active_session is old and old in cam._retiring_sessions
    assert cam._status["camera_error_code"] == "DECODER_RETIRE_FAILED"


def test_restart_keeps_failed_child_then_recovers_same_owner(primary, monkeypatch):
    cam, old = primary
    old.close_fails = True
    starts = []
    monkeypatch.setattr(cam, "start", lambda: starts.append(True))
    cam.restart()
    assert not starts and cam._active_session is old and old in cam._retiring_sessions
    old.close_fails = False
    cam.restart()
    assert starts == [True] and old.retired() and cam._active_session is None


def test_close_return_without_exit_proof_still_blocks_primary_replacement(primary, monkeypatch):
    cam, old = primary
    monkeypatch.setattr(old, "close", lambda: None)
    cam.stop()
    monkeypatch.setattr(cam, "_new_session", lambda source: pytest.fail("unproven child replaced"))
    result = cam.safe_select_source("1")
    assert not result["ok"] and result["code"] == "DECODER_RETIRE_FAILED"
    assert cam._active_session is old and old in cam._retiring_sessions
