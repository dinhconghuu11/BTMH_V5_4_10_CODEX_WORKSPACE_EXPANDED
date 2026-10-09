"""Association geometry only; no camera, model, DB or recognition events."""
import numpy as np

from module_app.face_core import FaceObservation
from module_app.walkby import WalkByEngine


def observation(x, *, quality=.8):
    box = (x, 40, 100, 100)
    return FaceObservation(np.zeros(15, np.float32), box, None, {"score": quality}, "center", 0., 0.)


def test_clearer_observation_cannot_steal_a_stationary_persons_unique_best_track():
    engine = WalkByEngine()
    tracks = {}
    left, right = engine._assign(tracks, [observation(100), observation(200)], 100.)
    left[0].recognized_student_id, right[0].recognized_student_id = 11, 22
    result = engine._assign(tracks, [observation(140, quality=.99), observation(100, quality=.7)], 100.1)
    associated = {track.recognized_student_id: obs.bbox[0] for track, obs in result}
    assert associated == {11: 100, 22: 140}
    assert len(tracks) == 2


def test_crossing_motion_uses_predicted_geometry_instead_of_previous_overlap():
    engine = WalkByEngine()
    tracks = {}
    left, right = engine._assign(tracks, [observation(100), observation(200)], 100.)
    left[0].recognized_student_id, right[0].recognized_student_id = 11, 22
    left[0].velocity, right[0].velocity = (400., 0.), (-400., 0.)
    result = engine._assign(tracks, [observation(95, quality=.99), observation(205, quality=.7)], 100.25)
    associated = {track.recognized_student_id: obs.bbox[0] for track, obs in result}
    assert associated == {11: 205, 22: 95}
    assert len(tracks) == 2


def test_velocity_uses_capture_interval_instead_of_inference_completion_jitter():
    engine = WalkByEngine()
    tracks = {}
    track = engine._assign(tracks, [observation(100)], 100., capture_at=10.)[0][0]
    engine._assign(tracks, [observation(120)], 100.8, capture_at=10.1)
    assert abs(track.velocity[0] - 110.) < .001
    assert track.last_capture_at == 10.1
    assert track.last_seen == 100.8, 'business absence continues to use its existing wall clock'


def test_unmatched_distant_face_gets_new_track_without_reusing_identity():
    engine = WalkByEngine()
    tracks = {}
    original = engine._assign(tracks, [observation(100)], 100.)[0][0]
    original.recognized_student_id = 11
    new = engine._assign(tracks, [observation(2000)], 100.1)[0][0]
    assert new.id != original.id
    assert new.recognized_student_id is None


def test_tracking_capacity_and_empty_observations_do_not_spawn_extra_tracks():
    engine = WalkByEngine(max_tracks=1)
    tracks = {}
    engine._assign(tracks, [observation(100)], 100.)
    assert engine._assign(tracks, [], 100.1) == []
    assert engine._assign(tracks, [observation(2000)], 100.2) == []
    assert len(tracks) == 1
