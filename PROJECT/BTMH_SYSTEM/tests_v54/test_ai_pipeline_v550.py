"""Phase 1 inference concurrency/security contracts, using no camera or model."""
import threading
import time

import numpy as np
import pytest

from module_app import walkby
from module_app.ai_pipeline_v550 import InferenceJob, LatestBatchLane
from module_app.anti_spoof import LivenessDecision
from module_app.face_core import FaceObservation


def wait_for(predicate, timeout=2.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "worker did not make the expected bounded progress"


def job(seq, epoch=1):
    return InferenceJob("camera", epoch, 1, seq, time.perf_counter(), time.time(), None, None)


def test_lane_replaces_one_waiting_batch_and_keeps_results_bounded():
    entered, release = threading.Event(), threading.Event()
    seen = []

    def infer(packet):
        seen.append(packet.seq)
        if packet.seq == 1:
            entered.set()
            assert release.wait(2)
        return packet.seq

    lane = LatestBatchLane("test", infer)
    try:
        assert lane.status()["last_queue_wait_ms"] is None
        lane.submit([job(1)])
        assert entered.wait(1)
        lane.submit([job(2)])
        lane.submit([job(3)])
        assert lane.status()["pending"] == 1
        time.sleep(.025)
        release.set()
        wait_for(lambda: lane.status()["completed"] == 2)
        assert seen == [1, 3]
        assert lane.status()["last_queue_wait_ms"] >= 15
        assert [r.value for r in lane.drain("camera", 1)] == [3]
        assert not lane.drain("camera", 1)
    finally:
        release.set()
        lane.shutdown()


def test_shutdown_and_restart_never_duplicate_a_blocked_model_owner():
    entered, release = threading.Event(), threading.Event()
    seen = []

    def infer(packet):
        seen.append(packet.seq)
        if packet.seq == 1:
            entered.set()
            release.wait(2)
        return packet.seq

    lane = LatestBatchLane("test", infer)
    try:
        lane.submit([job(1)])
        assert entered.wait(1)
        first_thread = lane._thread
        lane.invalidate("camera", 1)
        lane.shutdown(0)
        lane.submit([job(2, 2)])
        assert lane._thread is first_thread and seen == [1]
        release.set()
        first_thread.join(1)
        assert not lane.drain("camera", 1)
        lane.submit([job(3, 2)])
        wait_for(lambda: lane.status()["completed"] == 2)
        assert seen == [1, 3] and lane.status()["restarts"] == 1
    finally:
        release.set()
        lane.shutdown()


@pytest.fixture
def engine(monkeypatch):
    obj = walkby.WalkByEngine()
    events = []
    face = np.asarray([40, 40, 90, 100, 60, 65, 100, 65, 80, 85, 65, 110, 95, 110, .99], np.float32)
    observation = FaceObservation(face, (40, 40, 90, 100), None,
        {"score": .9, "face_px": 90, "usable": True, "sharpness": 80, "brightness": 128},
        "center", 0.0, 0.0)
    monkeypatch.setattr(walkby, "ANTI_SPOOF_ENABLED", True)
    monkeypatch.setattr(walkby.CORE, "detect", lambda *a, **kw: [face])
    monkeypatch.setattr(walkby.CORE, "observe", lambda *a, **kw: observation)
    monkeypatch.setattr(walkby.CORE, "encode_jpeg_data_url", lambda *a, **kw: "data:image/jpeg;base64,TEST")
    monkeypatch.setattr(walkby.CORE, "embedding", lambda *a: np.asarray([1, 0], np.float32))
    monkeypatch.setattr(walkby.ANTI_SPOOF, "update", lambda *a: LivenessDecision("PASS", .99, "test"))
    monkeypatch.setattr(walkby.INDEX, "rank", lambda *a, **kw: [(7, .999), (8, .01)])
    monkeypatch.setattr(walkby, "fetchone", lambda *a: {"id": 7, "full_name": "Test Person"})

    def add_event(*a, **kw):
        events.append((a, kw))
        return {"id": len(events), "event_at": "2026-10-07T00:00:00"}

    monkeypatch.setattr(walkby, "add_event", add_event)
    monkeypatch.setattr(walkby, "add_spoof_event", lambda *a, **kw: {"id": 99, "deduplicated": True})
    monkeypatch.setattr(walkby, "persist_recognition_evidence", lambda *a: None)
    monkeypatch.setattr(walkby, "apply_successful_checkin", lambda *a: None)
    obj.test_events = events
    obj.test_observation = observation
    try:
        yield obj
    finally:
        obj.shutdown()


def process(engine, seq, epoch=1, **kwargs):
    image = np.full((180, 240, 3), seq, np.uint8)
    return engine.process("camera", image, async_mode=True, source_epoch=epoch,
                          frame_seq=seq, capture_at=time.perf_counter(), **kwargs)


def test_slow_identity_does_not_block_detection_and_newer_pad_blocks_old_pass(engine, monkeypatch):
    identity_entered, identity_release = threading.Event(), threading.Event()
    pad_entered, pad_release = threading.Event(), threading.Event()

    def identity(*a):
        identity_entered.set()
        assert identity_release.wait(2)
        return np.asarray([1, 0], np.float32)

    def pad(key, image, observation, now):
        if image[0, 0, 0] >= 3:
            pad_entered.set()
            assert pad_release.wait(2)
        return LivenessDecision("PASS", .99, "test")

    monkeypatch.setattr(walkby.CORE, "embedding", identity)
    monkeypatch.setattr(walkby.ANTI_SPOOF, "update", pad)
    try:
        process(engine, 1)
        wait_for(lambda: engine._pipeline.pad.status()["completed"] == 1)
        process(engine, 2)
        assert identity_entered.wait(1)
        wait_for(lambda: engine._pipeline.pad.status()["completed"] == 2)
        began = time.perf_counter()
        result = process(engine, 3)
        assert time.perf_counter() - began < .25
        assert result["face_count"] == 1 and not result["events"]
        assert pad_entered.wait(1)
        identity_release.set()
        wait_for(lambda: engine._pipeline.faceid.status()["completed"] >= 1)
        assert not process(engine, 4)["events"] and not engine.test_events
        pad_release.set()
        wait_for(lambda: not engine._pipeline.pad.status()["busy"]
                          and not engine._pipeline.pad.status()["pending"])
        result = process(engine, 5)
        assert len(result["events"]) == 1 and len(engine.test_events) == 1
        assert result["tracks"][0]["recognized"]
    finally:
        identity_release.set()
        pad_release.set()


def test_completed_blocked_pad_erases_a_waiting_identity(engine, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def identity(*a):
        entered.set()
        assert release.wait(2)
        return np.asarray([1, 0], np.float32)

    monkeypatch.setattr(walkby.CORE, "embedding", identity)
    process(engine, 1)
    wait_for(lambda: engine._pipeline.pad.status()["completed"] == 1)
    process(engine, 2)
    assert entered.wait(1)
    wait_for(lambda: engine._pipeline.pad.status()["completed"] == 2)
    monkeypatch.setattr(walkby.ANTI_SPOOF, "update", lambda *a: LivenessDecision("BLOCKED", .99, "test attack"))
    process(engine, 3)
    wait_for(lambda: engine._pipeline.pad.status()["completed"] == 3)
    release.set()
    wait_for(lambda: engine._pipeline.faceid.status()["completed"] == 1)
    result = process(engine, 4)
    assert not engine.test_events and not result["tracks"][0]["recognized"]
    assert result["tracks"][0]["spoof_blocked"]
    assert result["tracks"][0]["candidate_student_id"] is None


@pytest.mark.parametrize("invalidate", ["reset", "source", "delete", "absence"])
def test_old_identity_completion_cannot_cross_presence_generation(engine, monkeypatch, invalidate):
    entered, release = threading.Event(), threading.Event()

    def identity(*a):
        entered.set()
        assert release.wait(2)
        return np.asarray([1, 0], np.float32)

    monkeypatch.setattr(walkby.CORE, "embedding", identity)
    try:
        process(engine, 1)
        wait_for(lambda: engine._pipeline.pad.status()["completed"] == 1)
        process(engine, 2)
        assert entered.wait(1)
        original = next(iter(engine._sessions["camera"]["tracks"].values()))
        if invalidate == "reset":
            engine.reset("camera")
        elif invalidate == "delete":
            engine.purge_student(7)
            monkeypatch.setattr(walkby, "fetchone", lambda *a: None)
        elif invalidate == "absence":
            original.last_seen = time.time() - walkby.QUICK_REARM_SEC - .1
        result = process(engine, 3, epoch=2 if invalidate == "source" else 1)
        release.set()
        wait_for(lambda: engine._pipeline.faceid.status()["completed"] >= 1)
        result = process(engine, 4, epoch=2 if invalidate == "source" else 1)
        assert not engine.test_events and not result["events"]
        assert not any(t["recognized"] for t in result["tracks"])
    finally:
        release.set()


def test_model_and_evidence_work_do_not_hold_central_track_lock(engine, monkeypatch):
    observed = []
    evidence_entered, evidence_release = threading.Event(), threading.Event()
    caller = threading.get_ident()

    def check_lock(label):
        assert threading.get_ident() != caller
        # Submission briefly holds the lock. Permit that bounded bookkeeping to
        # finish, then prove the model callback can acquire it independently.
        acquired = engine._lock.acquire(timeout=1)
        assert acquired, label + " held the central tracker lock"
        if acquired:
            engine._lock.release()
        observed.append(label)

    def pad(*args):
        check_lock("pad")
        return LivenessDecision("PASS", .99, "test")

    def identity(*args):
        check_lock("faceid")
        return np.asarray([1, 0], np.float32)

    def evidence(**kwargs):
        check_lock("evidence")
        evidence_entered.set()
        assert evidence_release.wait(2)
        return None

    monkeypatch.setattr(walkby.ANTI_SPOOF, "update", pad)
    monkeypatch.setattr(walkby.CORE, "embedding", identity)
    process(engine, 1, evidence_provider=evidence)
    wait_for(lambda: engine._pipeline.pad.status()["completed"] == 1)
    process(engine, 2, evidence_provider=evidence)
    assert evidence_entered.wait(1)
    reset_done = threading.Event()
    reset_thread = threading.Thread(target=lambda: (engine.reset("camera"), reset_done.set()))
    reset_thread.start()
    try:
        assert reset_done.wait(1), "reset waited for a blocked evidence detector"
    finally:
        evidence_release.set()
        reset_thread.join(1)
    wait_for(lambda: engine._pipeline.faceid.status()["completed"] == 1)
    assert "pad" in observed and "faceid" in observed and "evidence" in observed
    assert engine._pipeline.pad.status()["errors"] == 0
    assert engine._pipeline.faceid.status()["errors"] == 0


def test_same_captured_frame_never_adds_duplicate_pad_votes(engine, monkeypatch):
    votes = []
    monkeypatch.setattr(walkby.ANTI_SPOOF, "update", lambda *a:
                        votes.append(a[0]) or LivenessDecision("CHECKING", .5, "test"))
    process(engine, 1)
    wait_for(lambda: engine._pipeline.pad.status()["completed"] == 1)
    for _ in range(4):
        process(engine, 1)
    assert len(votes) == 1 and engine._pipeline.pad.status()["completed"] == 1


def test_bestshot_revision_only_advances_when_the_image_set_improves(engine):
    image = np.zeros((180, 240, 3), np.uint8)
    obs = engine.test_observation
    track = walkby.Track(1, obs.bbox, 0, 0, (80, 80))
    engine._update_best_shots(track, image, obs, 10)
    first = track.best_shots_revision
    obs.quality = {**obs.quality, "score": .8}
    engine._update_best_shots(track, image, obs, 11)
    assert track.best_shots_revision == first
    obs.quality = {**obs.quality, "score": .99}
    engine._update_best_shots(track, image, obs, 12)
    assert track.best_shots_revision == first + 1


def test_reset_while_detector_runs_discards_old_frame(engine, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = walkby.CORE.detect

    def detect(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(walkby.CORE, "detect", detect)
    results = []
    thread = threading.Thread(target=lambda: results.append(process(engine, 1)))
    try:
        thread.start()
        assert entered.wait(1)
        engine.reset("camera")
        release.set()
        thread.join(1)
        assert not thread.is_alive()
        assert results[0]["discarded_generation"] and not engine._sessions
    finally:
        release.set()
        thread.join(1)


def test_undrained_newer_blocked_pad_is_an_authorization_barrier(engine, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    process(engine, 1)
    wait_for(lambda: engine._pipeline.pad.status()["completed"] == 1)
    # Consume the first PASS, with an identity call still waiting independently.
    process(engine, 1)
    wait_for(lambda: engine._pipeline.faceid.status()["completed"] == 1)
    state = engine._sessions["camera"]
    track = next(iter(state["tracks"].values()))
    track.candidate_student_id = 7
    track.candidate_confidence = .999
    track.candidate_student = {"id": 7, "full_name": "Test Person"}
    track.candidate_seq = 1

    def pad(*args):
        entered.set()
        assert release.wait(2)
        return LivenessDecision("BLOCKED", .99, "new attack")

    monkeypatch.setattr(walkby.ANTI_SPOOF, "update", pad)
    image = np.zeros((180, 240, 3), np.uint8)
    newer = InferenceJob("camera", state["generation"], track.id, 2, time.perf_counter(),
                         time.time(), image, engine.test_observation, source_epoch=1)
    engine._pipeline.pad.submit([newer])
    assert entered.wait(1)
    original_drain = engine._pipeline.pad.drain

    def drain_then_complete(*args):
        results = original_drain(*args)
        release.set()
        wait_for(lambda: engine._pipeline.pad.status()["completed"] == 2)
        return results

    monkeypatch.setattr(engine._pipeline.pad, "drain", drain_then_complete)
    try:
        result = process(engine, 3)
        assert not result["events"] and not engine.test_events
        assert not result["tracks"][0]["recognized"]
    finally:
        release.set()


def test_future_capture_never_schedules_pad_or_identity(engine):
    image = np.zeros((180, 240, 3), np.uint8)
    result = engine.process("camera", image, async_mode=True, source_epoch=1,
                            frame_seq=1, capture_at=time.perf_counter() + 30)
    assert not result["events"]
    assert engine._pipeline.pad.status()["completed"] == 0
    assert not engine._pipeline.pad.status()["alive"]
    assert not engine._pipeline.faceid.status()["alive"]


def test_detector_misses_report_recovery_without_scheduling_verification(engine, monkeypatch):
    monkeypatch.setattr(walkby.CORE, "detect", lambda *a, **kw: [])
    monkeypatch.setattr(walkby, "LONG_RANGE_EVERY", 2)
    first = process(engine, 1)
    second = process(engine, 2)
    assert first["detection"]["no_face_streak"] == 1
    assert not first["detection"]["recovery_attempted"]
    assert second["detection"] == {"detected_faces": 0, "observed_faces": 0,
                                   "observation_errors": 0, "no_face_streak": 2,
                                   "recovery_attempted": True}
    assert not second["tracks"] and not second["events"] and not engine.test_events
    assert not engine._pipeline.pad.status()["alive"]
    assert not engine._pipeline.faceid.status()["alive"]


def test_observation_failure_is_distinct_from_a_detector_miss_and_fails_closed(engine, monkeypatch):
    def fail_observation(*args, **kwargs):
        raise ValueError("private diagnostic must not be returned")
    monkeypatch.setattr(walkby.CORE, "observe", fail_observation)
    result = process(engine, 1)
    assert result["detection"] == {"detected_faces": 1, "observed_faces": 0,
                                   "observation_errors": 1, "no_face_streak": 0,
                                   "recovery_attempted": False}
    assert not result["tracks"] and not result["events"] and not engine.test_events
    assert "private" not in str(result)
    assert not engine._pipeline.pad.status()["alive"]
    assert not engine._pipeline.faceid.status()["alive"]


def test_expired_model_completion_cleans_temporal_state_before_next_job(monkeypatch):
    from module_app import ai_pipeline_v550 as pipeline
    discarded = []
    monkeypatch.setattr(pipeline, "MAX_RESULT_AGE_SEC", .02)

    def slow(packet):
        time.sleep(.04)
        return "PASS"

    lane = LatestBatchLane("test", slow, on_discard=lambda packet: discarded.append(packet.seq))
    try:
        lane.submit([job(1)])
        wait_for(lambda: lane.status()["completed"] == 1)
        assert lane.drain("camera", 1) == []
        wait_for(lambda: discarded == [1])
    finally:
        lane.shutdown()


def test_cancelled_pad_late_state_is_purged(engine, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    keys = []

    def delayed_update(key, *args):
        keys.append(key)
        entered.set()
        assert release.wait(2)
        # Model calls may create state only after reset has already purged it.
        with walkby.ANTI_SPOOF._lock:
            walkby.ANTI_SPOOF._states[key] = object()
        return LivenessDecision("PASS", .99, "late completion")

    monkeypatch.setattr(walkby.ANTI_SPOOF, "update", delayed_update)
    try:
        process(engine, 1)
        assert entered.wait(1)
        engine.reset("camera")
        release.set()
        wait_for(lambda: engine._pipeline.pad.status()["completed"] == 1)
        wait_for(lambda: keys[0] not in walkby.ANTI_SPOOF._states)
        assert not engine._pipeline.pad.drain("camera", 1)
    finally:
        release.set()
