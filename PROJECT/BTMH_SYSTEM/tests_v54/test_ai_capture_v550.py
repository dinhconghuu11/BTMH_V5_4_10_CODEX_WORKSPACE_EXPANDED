"""Private AI decoder contracts, with no physical camera or customer data."""
import json
import threading
import time

import numpy as np
import pytest

from module_app import config as cfg
from module_app.ai_capture_v550 import AICaptureLane
from module_app.camera_profiles import hikvision_ai_substream
from module_app.capture_session_v544 import FramePacket


MAIN = "rtsp://test-user:test%40secret@camera.example.test:8554/Streaming/Channels/101?test-token=private"


class TestClock:
    __test__ = False

    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class FakeSession:
    def __init__(self, clock, *, ready_gate=None, code="READY", close_fails=False):
        self.clock = clock
        self.ready_gate = ready_gate
        self.code = code
        self.close_fails = close_fails
        self.entered = threading.Event()
        self.closed = False
        self.running = True
        self.close_attempts = 0
        self.image = np.zeros((120, 160, 3), np.uint8)
        self.image.setflags(write=False)
        self.packet = FramePacket(self.image, 3, clock())

    def start(self):
        pass

    def wait_ready(self, frames, timeout, cancelled):
        assert frames >= 3 and timeout > 0
        self.entered.set()
        if self.ready_gate is not None:
            while not self.ready_gate.wait(.005):
                if cancelled():
                    return {"ok": False, "code": "CANCELLED"}
        return {"ok": self.code == "READY", "code": self.code, "observed_fps": 12.0}

    def snapshot(self):
        return self.packet

    def alive(self):
        return self.running and not self.closed

    def close(self):
        self.close_attempts += 1
        if self.close_fails:
            raise OSError("test%40secret and private must never appear in diagnostics")
        self.closed = True

    def publish(self, seq, *, at=None, image=None):
        self.packet = FramePacket(self.image if image is None else image, seq,
                                  self.clock() if at is None else at)


def wait_until(predicate, timeout=1.5):
    deadline = time.perf_counter() + timeout
    while not predicate():
        if time.perf_counter() >= deadline:
            pytest.fail("AI capture worker did not reach the expected state")
        time.sleep(.005)


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(cfg, "AI_SUBSTREAM_ENABLED", True)
    monkeypatch.setattr(cfg, "AI_SUBSTREAM_MAX_AGE_SEC", .2)
    monkeypatch.setattr(cfg, "AI_SUBSTREAM_OPEN_TIMEOUT_SEC", .5)
    items = []

    def create(factory, clock):
        lane = AICaptureLane(session_factory=factory, clock=clock)
        items.append(lane)
        return lane

    yield create
    for lane in items:
        lane.stop()
        assert not lane.status()["worker_alive"]


def test_unconfigured_policy_changes_are_explicit_without_a_decoder(lanes, monkeypatch):
    clock = TestClock()
    lane = lanes(lambda *args, **kwargs: pytest.fail("unregistered source opened"), clock)
    lane.configure(MAIN, 0, registered=False)
    assert lane.status()["fallback_reason"] == "SOURCE_NOT_REGISTERED"
    lane.configure("0", 0, registered=True)
    assert lane.status()["fallback_reason"] == "NO_KNOWN_SUBSTREAM"
    monkeypatch.setattr(cfg, "AI_SUBSTREAM_ENABLED", False)
    lane.configure(MAIN, 0, registered=True)
    lane.start()
    assert lane.status()["fallback_reason"] == "SUBSTREAM_DISABLED"
    assert lane.snapshot(0) is None


@pytest.mark.parametrize("source", ["0", "http://camera.example.test/snapshot", "rtsp://camera.example.test/custom",
                                      "rtsp://camera.example.test/Streaming/Channels/102"])
def test_only_known_main_channel_paths_are_derived(source):
    assert hikvision_ai_substream(source) is None


def test_readiness_requires_decoded_frames_and_status_contains_no_source_secrets(lanes):
    clock = TestClock()
    gate = threading.Event()
    session = FakeSession(clock, ready_gate=gate)
    captured = {}

    def factory(source, **kwargs):
        captured.update(source=source, **kwargs)
        return session

    lane = lanes(factory, clock)
    lane.configure(MAIN, 4, registered=True)
    lane.start()
    assert session.entered.wait(1)
    assert lane.snapshot(4) is None
    assert lane.status()["fallback_reason"] == "SUBSTREAM_CONNECTING"
    assert captured["source"] == MAIN.replace("/101?", "/102?")
    assert captured["output_fps"] == cfg.AI_SUBSTREAM_CAPTURE_FPS
    assert captured["output_max_width"] == cfg.RTSP_AI_WIDTH
    gate.set()
    wait_until(lambda: lane.snapshot(4) is not None)
    assert lane.status()["mode"] == "HIKVISION_SUBSTREAM"
    status = json.dumps(lane.status())
    assert all(secret not in status for secret in ("rtsp://", "test-user", "test%40secret", "private"))


def test_latest_slot_replaces_frames_and_never_republishes_regressed_sequence(lanes):
    clock = TestClock()
    session = FakeSession(clock)
    lane = lanes(lambda *args, **kwargs: session, clock)
    lane.configure(MAIN, 7, registered=True)
    lane.start()
    wait_until(lambda: lane.snapshot(7) is not None)
    session.publish(30)
    wait_until(lambda: lane.snapshot(7).seq == 30)
    session.publish(4)
    time.sleep(.025)
    assert lane.snapshot(7).seq == 30
    assert lane.snapshot(8) is None
    assert lane.status()["queue_depth"] == 0 and lane.status()["latest_slot_capacity"] == 1


def test_capture_fps_measures_ongoing_frames_not_startup_readiness(lanes, monkeypatch):
    clock = TestClock()
    monkeypatch.setattr(cfg, "AI_SUBSTREAM_MAX_AGE_SEC", 5.0)
    session = FakeSession(clock)
    lane = lanes(lambda *args, **kwargs: session, clock)
    lane.configure(MAIN, 7, registered=True)
    lane.start()
    wait_until(lambda: lane.snapshot(7) is not None)
    assert lane.status()["capture_fps"] == 0.0, "startup bursts are not an ongoing FPS measurement"
    clock.value += 1.0
    session.publish(5)
    wait_until(lambda: lane.snapshot(7).seq == 5)
    assert lane.status()["capture_fps"] == 2.0
    clock.value += 1.0
    session.publish(13)
    wait_until(lambda: lane.snapshot(7).seq == 13)
    assert lane.status()["capture_fps"] == 8.0, "count decoder frames skipped by the latest-frame consumer"
    session.publish(12)
    time.sleep(.025)
    assert lane.status()["capture_fps"] == 8.0
    lane.configure(MAIN, 8, registered=True)
    assert lane.status()["capture_fps"] == 0.0


@pytest.mark.parametrize("advance", [1.0, -1.0])
def test_old_or_future_timestamps_cannot_feed_ai(lanes, advance):
    clock = TestClock()
    session = FakeSession(clock)
    lane = lanes(lambda *args, **kwargs: session, clock)
    lane.configure(MAIN, 2, registered=True)
    lane.start()
    wait_until(lambda: lane.snapshot(2) is not None)
    clock.value += advance
    assert lane.snapshot(2) is None
    status = lane.status()
    assert status["mode"] == "MAIN_FALLBACK"
    assert status["fallback_reason"] in {"SUBSTREAM_STALE", "SUBSTREAM_TIMEOUT"}


def test_handover_cancels_readiness_and_retires_previous_before_opening_next(lanes):
    clock = TestClock()
    first = FakeSession(clock, ready_gate=threading.Event())
    second = FakeSession(clock)
    sessions = []

    def factory(source, **kwargs):
        if not sessions:
            sessions.append(first)
            return first
        assert first.closed, "second decoder opened before the previous owner retired"
        sessions.append(second)
        return second

    lane = lanes(factory, clock)
    lane.configure(MAIN, 5, registered=True)
    lane.start()
    assert first.entered.wait(1)
    lane.configure(MAIN.replace("/101?", "/201?"), 6, registered=True)
    assert lane.snapshot(5) is None and lane.snapshot(6) is None
    wait_until(lambda: lane.snapshot(6) is not None)
    assert len(sessions) == 2 and first.closed
    assert lane.snapshot(6).source_epoch == 6 and lane.snapshot(5) is None


def test_revoking_registry_binding_clears_ready_packet_and_retires_decoder(lanes):
    clock = TestClock()
    session = FakeSession(clock)
    lane = lanes(lambda *args, **kwargs: session, clock)
    lane.configure(MAIN, 1, registered=True)
    lane.start()
    wait_until(lambda: lane.snapshot(1) is not None)
    lane.configure(MAIN, 1, registered=False)
    assert lane.snapshot(1) is None
    wait_until(lambda: session.closed)
    assert lane.status()["fallback_reason"] == "SOURCE_NOT_REGISTERED"


def test_stop_during_factory_does_not_spawn_a_second_owner_or_publish_late(lanes):
    clock = TestClock()
    entered, release = threading.Event(), threading.Event()
    first, second = FakeSession(clock), FakeSession(clock)
    calls = []

    def factory(source, **kwargs):
        calls.append(source)
        if len(calls) == 1:
            entered.set()
            release.wait(4)
            return first
        assert first.closed
        return second

    lane = lanes(factory, clock)
    lane.configure(MAIN, 1, registered=True)
    lane.start()
    assert entered.wait(1)
    owner = lane._thread
    lane.stop()
    lane.start()
    assert lane._thread is owner and len(calls) == 1
    assert lane.snapshot(1) is None and lane.status()["fallback_reason"] == "SUBSTREAM_STOPPED"
    release.set()
    wait_until(lambda: not lane.status()["worker_alive"])
    assert first.closed and lane.snapshot(1) is None
    lane.start()
    wait_until(lambda: lane.snapshot(1) is not None)
    assert len(calls) == 2


@pytest.mark.parametrize("code", ["AUTH_FAILED", "PATH_NOT_FOUND", "MASKED_CREDENTIALS", "INVALID_SOURCE"])
def test_permanent_failures_do_not_retry_unchanged_credentials(lanes, code):
    clock = TestClock()
    session = FakeSession(clock, code=code)
    calls = []
    lane = lanes(lambda *args, **kwargs: calls.append(args[0]) or session, clock)
    lane.configure(MAIN, 1, registered=True)
    lane.start()
    wait_until(lambda: session.closed)
    clock.value += 60
    time.sleep(.025)
    assert len(calls) == 1
    assert lane.status()["retry_blocked"]
    assert lane.status()["fallback_reason"] == "SUBSTREAM_" + code


def test_reconnect_obeys_backoff_and_uses_monotonic_frame_ids(lanes):
    clock = TestClock()
    first, second = FakeSession(clock), FakeSession(clock)
    calls = []

    def factory(source, **kwargs):
        calls.append(source)
        assert len(calls) <= 2
        if len(calls) == 2:
            assert first.closed
        return first if len(calls) == 1 else second

    lane = lanes(factory, clock)
    lane.configure(MAIN, 2, registered=True)
    lane.start()
    wait_until(lambda: lane.snapshot(2) is not None)
    first.publish(80)
    wait_until(lambda: lane.snapshot(2).seq == 80)
    first.running = False
    wait_until(lambda: first.closed)
    assert lane.snapshot(2) is None and lane.status()["fallback_reason"] == "SUBSTREAM_READ_FAILED"
    assert len(calls) == 1
    clock.value += 1.1
    second.publish(3)
    wait_until(lambda: lane.snapshot(2) is not None)
    assert lane.snapshot(2).seq > 80 and len(calls) == 2


def test_missing_frames_timeout_even_if_the_decoder_process_is_alive(lanes):
    clock = TestClock()
    session = FakeSession(clock)
    session.packet = FramePacket(None, 0, 0)
    lane = lanes(lambda *args, **kwargs: session, clock)
    lane.configure(MAIN, 3, registered=True)
    lane.start()
    assert session.entered.wait(1)
    time.sleep(.025)
    clock.value += .3
    wait_until(lambda: session.closed)
    assert lane.snapshot(3) is None
    assert lane.status()["fallback_reason"] == "SUBSTREAM_TIMEOUT"


def test_failed_retirement_blocks_new_decoder_until_old_owner_closes(lanes):
    clock = TestClock()
    first, second = FakeSession(clock, close_fails=True), FakeSession(clock)
    calls = []

    def factory(source, **kwargs):
        calls.append(source)
        if len(calls) == 2:
            assert first.closed
        return first if len(calls) == 1 else second

    lane = lanes(factory, clock)
    lane.configure(MAIN, 1, registered=True)
    lane.start()
    wait_until(lambda: lane.snapshot(1) is not None)
    lane.configure(MAIN.replace("/101?", "/201?"), 2, registered=True)
    wait_until(lambda: lane.status()["fallback_reason"] == "SUBSTREAM_RETIRE_FAILED")
    assert lane.status()["retry_blocked"] and lane.snapshot(2) is None and len(calls) == 1
    assert "secret" not in json.dumps(lane.status())
    first.close_fails = False
    clock.value += 1.1
    second.publish(3)
    wait_until(lambda: lane.snapshot(2) is not None)
    assert first.closed and len(calls) == 2 and not lane.status()["retry_blocked"]


def test_arbitrary_decoder_exception_becomes_an_allowlisted_reason(lanes):
    clock = TestClock()

    def factory(*args, **kwargs):
        raise OSError("rtsp://test-user:test%40secret@camera.example.test?test-token=private")

    lane = lanes(factory, clock)
    lane.configure(MAIN, 1, registered=True)
    lane.start()
    wait_until(lambda: lane.status()["reconnect_count"] == 1)
    assert lane.status()["fallback_reason"] == "SUBSTREAM_START_FAILED"
    assert "secret" not in json.dumps(lane.status())


@pytest.mark.parametrize("source,reason", [
    (MAIN.replace("test%40secret", "***"), "MASKED_CREDENTIALS"),
    (MAIN.replace(":8554/", ":99999/"), "INVALID_SOURCE"),
])
def test_actual_constructor_rejects_masked_or_invalid_source_without_retry(lanes, source, reason):
    clock = TestClock()
    lane = lanes(None, clock)
    lane.configure(source, 1, registered=True)
    lane.start()
    wait_until(lambda: lane.status()["retry_blocked"])
    assert lane.status()["fallback_reason"] == "SUBSTREAM_" + reason
    assert lane.snapshot(1) is None and lane.status()["reconnect_count"] == 1
