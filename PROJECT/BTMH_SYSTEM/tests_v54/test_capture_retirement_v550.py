"""Child-exit proof with fake processes; never opens a physical camera."""
from __future__ import annotations

import gc
from io import BytesIO
import subprocess
import threading
import time
import weakref

import numpy as np
import pytest

from module_app import capture_session_v544 as capture


class Child:
    def __init__(self, *, terminate_exits=False, kill_exits=False, signals_fail=False):
        self.terminate_exits = terminate_exits
        self.kill_exits = kill_exits
        self.signals_fail = signals_fail
        self.returncode = None
        self.terminations = self.kills = 0
        self.waits = []
        self.stdin, self.stdout, self.stderr = BytesIO(), BytesIO(), BytesIO()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminations += 1
        if self.signals_fail:
            raise OSError("private child detail must not escape")
        if self.terminate_exits:
            self.returncode = 0

    def kill(self):
        self.kills += 1
        if self.signals_fail:
            raise OSError("private child detail must not escape")
        if self.kill_exits:
            self.returncode = -9

    def wait(self, timeout):
        self.waits.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("private command", timeout)
        return self.returncode


@pytest.fixture
def sessions(monkeypatch):
    monkeypatch.setattr(capture, "_LIVE", weakref.WeakSet())
    monkeypatch.setattr(capture, "_RETIRE_PENDING", set())
    owned = []

    def create(child=None):
        session = capture.CaptureSession("0")
        session.process = child
        owned.append(session)
        return session

    yield create
    for session in owned:
        if session.process is not None:
            session.process.returncode = 0
        session.close()


def test_failed_kill_retains_owner_and_retry_proves_exit(sessions):
    child = Child()
    session = sessions(child)
    session._latest = capture.FramePacket(np.zeros((8, 8, 3), np.uint8), 1, time.perf_counter())
    assert session.alive() and session.healthy()

    with pytest.raises(capture.CaptureRetirementError, match="^DECODER_RETIRE_FAILED$"):
        session.close()
    assert session.process is child and session.alive() and not session.retired()
    assert not session.healthy()
    assert session in capture._LIVE and session in capture._RETIRE_PENDING
    assert not any(pipe.closed for pipe in (child.stdin, child.stdout, child.stderr))
    assert child.waits == [.8, .8]
    assert session.diagnostics()["code"] == "DECODER_RETIRE_FAILED"

    child.kill_exits = True
    session.close()
    assert session.retired() and not session.alive()
    assert session not in capture._LIVE and session not in capture._RETIRE_PENDING
    assert all(pipe.closed for pipe in (child.stdin, child.stdout, child.stderr))
    assert child.terminations == child.kills == 2


def test_failed_signals_return_only_fixed_error_and_remain_retryable(sessions):
    child = Child(signals_fail=True)
    session = sessions(child)
    for _ in range(2):
        with pytest.raises(capture.CaptureRetirementError) as error:
            session.close()
        assert str(error.value) == "DECODER_RETIRE_FAILED"
        assert session.alive() and session in capture._LIVE
    assert child.terminations == child.kills == 2
    child.returncode = 0
    session.close()
    assert session.retired()


def test_successful_kill_after_terminate_timeout_is_retired(sessions):
    child = Child(kill_exits=True)
    session = sessions(child)
    session.close()
    assert child.terminations == child.kills == 1
    assert session.retired() and session not in capture._LIVE


def test_dead_and_unstarted_sessions_close_without_new_signals(sessions, monkeypatch):
    child = Child()
    child.returncode = 0
    dead, unstarted = sessions(child), sessions()
    monkeypatch.setattr(capture.subprocess, "Popen", lambda *a, **kw: pytest.fail("closed session restarted"))
    for session in (dead, unstarted):
        session.close()
        session.close()
        session.start()
        assert session.retired() and not session.alive() and session not in capture._LIVE
    assert child.terminations == child.kills == 0


def test_close_all_continues_after_one_child_refuses_exit(sessions):
    blocked = sessions(Child())
    normal = sessions(Child(terminate_exits=True))
    capture._close_all()
    assert blocked in capture._LIVE and blocked in capture._RETIRE_PENDING
    assert normal.retired() and normal not in capture._LIVE


def test_failed_retirement_keeps_strong_owner_when_caller_drops_handle(monkeypatch):
    monkeypatch.setattr(capture, "_LIVE", weakref.WeakSet())
    monkeypatch.setattr(capture, "_RETIRE_PENDING", set())
    session = capture.CaptureSession("0")
    session.process = Child()
    with pytest.raises(capture.CaptureRetirementError):
        session.close()
    reference = weakref.ref(session)
    del session
    gc.collect()
    assert reference() is not None and reference() in capture._LIVE
    reference().process.returncode = 0
    reference().close()
    gc.collect()
    assert reference() is None


def test_concurrent_close_serializes_retirement_and_only_signals_once(sessions):
    entered, release = threading.Event(), threading.Event()
    child = Child(terminate_exits=True)
    original_wait = child.wait

    def wait(timeout):
        entered.set()
        if not release.wait(3):
            raise AssertionError("test did not release child wait")
        return original_wait(timeout)

    child.wait = wait
    session = sessions(child)
    errors = []

    def close():
        try:
            session.close()
        except Exception as exc:
            errors.append(exc)

    first, second = threading.Thread(target=close), threading.Thread(target=close)
    try:
        first.start()
        assert entered.wait(2)
        second.start()
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert child.terminations == 1 and child.kills == 0 and session.retired()
