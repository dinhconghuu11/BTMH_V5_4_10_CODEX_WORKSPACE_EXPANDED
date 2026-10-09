"""Reader leases, decoder retirement and recovery without customer/hardware data."""
import threading
import time

import numpy as np
import pytest

from module_app.camera_fleet_v4 import CameraFleetV4, FleetUnavailable, FleetWorker, MAX_LEASES_PER_CAMERA
from module_app.capture_session_v544 import FramePacket


class Clock:
    def __init__(self):
        self.value = 100.

    def __call__(self):
        return self.value


class CountingWorker(FleetWorker):
    starts = 0
    allow_retire = True

    def start(self):
        if not self.running:
            self.starts += 1
        self.running = True
        self.stopped.clear()

    def stop(self, **kwargs):
        self.running = False
        self.stopped.set()
        self.latest_jpeg = None
        return self.retired()

    def retired(self):
        return self.allow_retire and not self.running


class Session:
    def __init__(self, clock, *, code="READY", close_fails=False):
        self.clock, self.code, self.close_fails = clock, code, close_fails
        self.closed = False
        self.entered = threading.Event()
        self.image = np.zeros((120, 160, 3), np.uint8)
        self.packet = FramePacket(self.image, 3, clock())

    def start(self):
        pass

    def wait_ready(self, *args, **kwargs):
        self.entered.set()
        return {"ok": self.code == "READY", "code": self.code}

    def snapshot(self):
        return self.packet

    def alive(self):
        return not self.closed

    def retired(self):
        return self.closed

    def close(self):
        if self.close_fails:
            raise RuntimeError("private source must not leak")
        self.closed = True


def wait_for(predicate, timeout=1.5):
    end = time.perf_counter() + timeout
    while not predicate():
        if time.perf_counter() >= end:
            pytest.fail("fleet worker did not make the expected bounded progress")
        time.sleep(.005)


@pytest.fixture
def fleet():
    clock = Clock()
    manager = CameraFleetV4(clock=clock, worker_factory=CountingWorker)
    yield manager, clock
    for worker in manager.workers.values():
        worker.allow_retire = True
    manager.shutdown()
    assert not manager._sweeper or not manager._sweeper.is_alive()


def test_status_reads_never_create_or_refresh_readers(fleet):
    manager, clock = fleet
    assert manager.get(1) is None and manager._sweeper is None
    worker = manager.ensure(1, "0", "USB")
    for _ in range(5):
        manager.get(1).status()
        clock.value += 4
    manager.sweep_idle()
    assert manager.get(1) is None and worker.starts == 1


def test_polling_touches_one_ttl_slot_and_idle_sweep_retires_it(fleet):
    manager, clock = fleet
    worker = manager.ensure(1, "0", "USB")
    clock.value += 10
    assert manager.ensure(1, "0", "USB") is worker
    assert len(manager._leases[1]) == 1 and worker.starts == 1
    clock.value += 10
    manager.sweep_idle()
    assert manager.get(1) is worker
    clock.value += 6
    manager.sweep_idle()
    assert manager.get(1) is None


def test_stream_leases_renew_release_and_expire_independently(fleet):
    manager, clock = fleet
    worker, first = manager.acquire(1, "0", "USB")
    same, second = manager.acquire(1, "0", "USB")
    assert same is worker and first != second
    clock.value += 10
    assert manager.renew(1, first)
    clock.value += 6
    assert not manager.renew(1, second)
    assert manager.get(1) is worker
    assert manager.release(1, first)
    assert manager.get(1) is None and not manager.release(1, first)


def test_expired_stream_token_cannot_resurrect_its_reader(fleet):
    manager, clock = fleet
    worker, token = manager.acquire(1, "0", "USB")
    clock.value += 16
    assert not manager.renew(1, token)
    manager.sweep_idle()
    assert manager.get(1) is None and worker.starts == 1


def test_source_change_revokes_old_tokens_and_stale_release_does_not_stop_new_reader(fleet):
    manager, _ = fleet
    old, token = manager.acquire(1, "0", "USB")
    new = manager.ensure(1, "1", "Other USB")
    assert new is not old and old.stopped.is_set()
    assert not manager.renew(1, token) and not manager.release(1, token)
    assert manager.get(1) is new and new.running


def test_failed_retirement_retains_owner_and_blocks_replacement_and_handover(fleet):
    manager, _ = fleet
    old = manager.ensure(1, "0", "USB")
    old.allow_retire = False
    assert not manager.stop(1, wait=False) and manager.get(1) is old
    with pytest.raises(FleetUnavailable, match="FLEET_RETIRE_FAILED"):
        manager.ensure(1, "1", "Other")
    with pytest.raises(FleetUnavailable, match="FLEET_RETIRE_FAILED"):
        with manager.reserve(1):
            pytest.fail("handover proceeded without retiring previous decoder")
    assert manager.get(1) is old and not manager._reserved
    old.allow_retire = True
    assert manager.ensure(1, "1", "Other") is not old


def test_handover_reservation_never_starts_an_auxiliary_reader(fleet):
    manager, _ = fleet
    with manager.reserve(1):
        worker = manager.ensure(1, "0", "USB")
        assert worker.error == "HANDOVER_RESERVED" and worker.starts == 0
    assert manager.ensure(1, "0", "USB") is worker and worker.starts == 1


def test_only_one_sweeper_is_created_and_lease_count_is_bounded(fleet):
    manager, _ = fleet
    manager.ensure(1, "0", "USB")
    sweeper = manager._sweeper
    for _ in range(MAX_LEASES_PER_CAMERA - 1):
        manager.acquire(1, "0", "USB")
    with pytest.raises(FleetUnavailable, match="FLEET_LEASE_LIMIT"):
        manager.acquire(1, "0", "USB")
    assert manager._sweeper is sweeper and len(manager._leases[1]) == MAX_LEASES_PER_CAMERA


@pytest.mark.parametrize("timestamp", [0., 95., 101., float("nan"), float("inf")])
def test_jpeg_rejects_stale_missing_and_invalid_capture_timestamp(timestamp):
    clock = Clock()
    worker = FleetWorker(1, "0", "USB", clock=clock)
    worker.running = worker.opened = True
    worker.latest_jpeg, worker.latest_at = b"jpeg", timestamp
    assert worker.jpeg() is None and not worker.status()["online"]


def test_fresh_jpeg_uses_capture_age_and_stop_clears_it():
    clock = Clock()
    worker = FleetWorker(1, "0", "USB", clock=clock)
    worker.running = worker.opened = True
    worker.latest_jpeg, worker.latest_at = b"jpeg", 99.
    assert worker.jpeg() == b"jpeg" and worker.status()["last_frame_age_sec"] == 1.
    worker.stop()
    assert worker.jpeg() is None and worker.latest_jpeg is None


@pytest.mark.parametrize("code", ["AUTH_FAILED", "PATH_NOT_FOUND", "MASKED_CREDENTIALS", "INVALID_SOURCE"])
def test_permanent_decoder_failures_never_reopen_unchanged_source(code):
    clock, calls = Clock(), []
    session = Session(clock, code=code)
    worker = FleetWorker(1, "0", "USB", clock=clock, session_factory=lambda *a, **kw: calls.append(a[0]) or session)
    worker.start()
    wait_for(lambda: not worker.running)
    clock.value += 60
    for _ in range(10):
        worker.start()
    assert calls == ["0"] and worker.status()["retry_blocked"] and session.closed
    worker.stop()


def test_constructor_invalid_source_is_classified_without_retry_or_secret():
    calls = []
    def factory(*args, **kwargs):
        calls.append(1)
        raise ValueError("MASKED_CREDENTIALS")
    worker = FleetWorker(1, "0", "USB", session_factory=factory)
    worker.start()
    wait_for(lambda: not worker.running)
    worker.start()
    assert len(calls) == 1 and worker.error == "MASKED_CREDENTIALS"


def test_recoverable_failures_back_off_before_reconnecting():
    clock, calls = Clock(), []
    sessions = [Session(clock, code="UNREACHABLE"), Session(clock, code="UNREACHABLE"), Session(clock)]
    def factory(*args, **kwargs):
        calls.append(clock())
        return sessions[len(calls) - 1]
    worker = FleetWorker(1, "0", "USB", clock=clock, session_factory=factory)
    try:
        worker.start()
        wait_for(lambda: len(calls) == 1 and sessions[0].closed)
        assert worker.status()["retry_in_sec"] == 1.
        clock.value += 1.1
        wait_for(lambda: len(calls) == 2 and sessions[1].closed)
        assert worker.status()["retry_in_sec"] == 2.
        clock.value += 2.1
        sessions[2].packet = FramePacket(sessions[2].image, 3, clock())
        wait_for(lambda: worker.jpeg() is not None)
        assert len(calls) == 3 and worker.reconnects == 2
    finally:
        worker.stop()


def test_decoder_close_failure_retains_session_until_proven_retired():
    clock = Clock()
    session = Session(clock, close_fails=True)
    worker = FleetWorker(1, "0", "USB", clock=clock, session_factory=lambda *a, **kw: session)
    worker.start()
    wait_for(lambda: worker.jpeg() is not None)
    worker.stop()
    assert not worker.retired() and worker.session is session and worker.error == "DECODER_RETIRE_FAILED"
    session.close_fails = False
    clock.value += 1.1
    assert worker.stop() and worker.retired() and worker.session is None


def test_successful_close_without_process_proof_does_not_release_ownership():
    session = Session(Clock())
    session.close = lambda: None
    worker = FleetWorker(1, "0", "USB")
    worker.session = session
    assert not worker.stop() and not worker.retired() and worker.session is session
    session.closed = True
    assert worker.retired()


def test_idle_cleanup_of_failed_owner_is_nonblocking_and_never_starts_replacement():
    clock = Clock()
    entered, release = threading.Event(), threading.Event()
    session = Session(clock)
    def close():
        entered.set()
        release.wait(2)
        session.closed = True
    session.close = close
    worker = FleetWorker(1, "0", "USB", clock=clock)
    worker.session = session
    began = time.perf_counter()
    assert not worker.stop(wait=False)
    assert time.perf_counter() - began < .1 and entered.wait(1)
    thread = worker.thread
    worker.stop(wait=False)
    assert worker.thread is thread
    release.set()
    thread.join(1)
    assert worker.retired()


@pytest.mark.parametrize("operation", ["stop", "release", "replace", "reserve"])
def test_retiring_one_camera_does_not_block_another_camera_status_or_lease(fleet, operation):
    manager, _ = fleet
    first, token = manager.acquire(1, "0", "USB")
    second = manager.ensure(2, "1", "Other USB")
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    failures = []
    original_stop = first.stop

    def blocked_stop(**kwargs):
        entered.set()
        if not release.wait(2):
            raise RuntimeError("test retirement barrier timed out")
        return original_stop(**kwargs)

    first.stop = blocked_stop

    def retire():
        try:
            if operation == "stop":
                manager.stop(1)
            elif operation == "release":
                manager.release(1, token)
            elif operation == "replace":
                manager.ensure(1, "2", "Replacement USB")
            else:
                with manager.reserve(1):
                    pass
        except Exception as exc:
            failures.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=retire, daemon=True)
    thread.start()
    try:
        assert entered.wait(1) and not done.is_set()
        began = time.perf_counter()
        assert manager.get(2) is second
        second.status()
        leased, other_token = manager.acquire(2, "1", "Other USB")
        assert leased is second and manager.renew(2, other_token)
        assert time.perf_counter() - began < .25 and not done.is_set()
    finally:
        release.set()
        thread.join(1)
    assert done.is_set() and not failures


def test_sweep_skips_a_busy_lifecycle_and_retires_other_expired_readers(fleet):
    manager, clock = fleet
    first = manager.ensure(1, "0", "USB")
    manager.ensure(2, "1", "Other USB")
    clock.value += 16
    entered, release = threading.Event(), threading.Event()

    def hold_first_camera():
        with manager._camera_lock(1):
            entered.set()
            release.wait(2)

    thread = threading.Thread(target=hold_first_camera, daemon=True)
    thread.start()
    try:
        assert entered.wait(1)
        manager.sweep_idle()
        assert manager.get(1) is first and manager.get(2) is None
    finally:
        release.set()
        thread.join(1)
    manager.sweep_idle()
    assert manager.get(1) is None


def test_idle_sweep_has_a_fixed_retirement_budget_and_eventually_visits_every_reader(fleet):
    manager, clock = fleet
    # Disable the periodic tick so this proves each explicit sweep's budget.
    manager._start_sweeper = lambda: None
    for cid in range(80):
        manager.ensure(cid, "0", "USB")
    clock.value += 16
    before = len(manager.workers)
    manager.sweep_idle()
    assert before - len(manager.workers) == 16
    for _ in range(10):
        before = len(manager.workers)
        manager.sweep_idle(max_workers=7)
        assert before - len(manager.workers) <= 7
    assert not manager.workers


def test_unknown_stop_ids_do_not_allocate_lifecycle_locks(fleet):
    manager, _ = fleet
    known = manager.ensure(1, "0", "USB")
    initial_locks = dict(manager._camera_locks)
    for cid in range(1000, 2000):
        assert manager.stop(cid, wait=False)
    assert manager._camera_locks == initial_locks and manager.get(1) is known
