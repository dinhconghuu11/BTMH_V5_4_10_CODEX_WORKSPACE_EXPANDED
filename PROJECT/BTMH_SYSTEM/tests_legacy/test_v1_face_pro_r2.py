from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np

_ROOT_TMP = tempfile.TemporaryDirectory(prefix='cf-pro-r2-test-')
os.environ.setdefault('CAMPUSFACE_DB_MODE', 'sqlite')
os.environ.setdefault('CAMPUSFACE_DATA_ROOT', _ROOT_TMP.name)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_app.camera import StaticCameraService, CapturePlan
from module_app.walkby import Track, WalkByEngine
from module_app.classroom_engine import ClassroomEngine
from module_app.config import APP_VERSION


def test_camera_quality_watchdog_flags_blur_and_exposure():
    dark = np.zeros((480, 640, 3), np.uint8)
    poor = StaticCameraService._quality_metrics(dark)
    assert poor['camera_quality'] == 'POOR', poor
    assert 'Thiếu sáng' in poor['quality_warning'], poor

    # High-frequency checkerboard gives deterministic sharpness without camera I/O.
    grid = (np.indices((480, 640)).sum(axis=0) % 2 * 255).astype(np.uint8)
    crisp = np.dstack([grid, grid, grid])
    good = StaticCameraService._quality_metrics(crisp)
    assert good['camera_quality'] in {'GOOD', 'FAIR'}, good
    assert good['sharpness_score'] > poor['sharpness_score'], (good, poor)


def test_camera_rejects_driver_that_ignores_requested_mode():
    plan = CapturePlan('dshow', None, 1920, 1080, 30, 'MJPG')
    assert StaticCameraService._mode_matches_plan(1920, 1080, plan)
    assert StaticCameraService._mode_matches_plan(1600, 900, plan)
    assert not StaticCameraService._mode_matches_plan(640, 480, plan)


def _track(tid: int, now: float) -> Track:
    return Track(tid, (100, 100, 80, 100), now - .5, now, (140, 150))


def test_identity_owner_prevents_duplicate_live_name():
    now = 100.0
    owner = _track(1, now)
    owner.recognized = True
    owner.recognized_student_id = 77
    contender = _track(2, now)
    tracks = {1: owner, 2: contender}
    found = WalkByEngine._identity_owner(tracks, 77, 2, now)
    assert found is owner
    assert WalkByEngine._identity_owner(tracks, 88, 2, now) is None


def test_identity_mismatch_release_requires_reacquire():
    now = 200.0
    tr = _track(5, now)
    tr.recognized = True
    tr.recognized_student_id = 10
    tr.recognized_confidence = .81
    tr.candidate_student_id = 10
    tr.samples.append({'student_id': 10, 'score': .81})
    WalkByEngine._drop_locked_identity(tr, now=now, conflict_sid=11)
    assert not tr.recognized and tr.recognized_student_id is None
    assert tr.candidate_student_id is None and len(tr.samples) == 0
    assert tr.identity_guard_state == 'REACQUIRE'
    assert tr.identity_conflict_student_id == 11
    assert tr.last_sample_at == now



def test_action_phone_device_near_student_is_detected_without_geometry_fallback():
    frame_shape = (1080, 1920, 3)
    face = [800, 210, 120, 140]
    # Explicit phone detector box inside the face-guided body region.
    nearby = [{"name": "cell phone", "confidence": 0.78, "box": (850, 520, 70, 120)}]
    hit, conf = ClassroomEngine._phone_device_near_face(nearby, face, frame_shape)
    assert hit and conf == 0.78, (hit, conf)

    # A phone on the other side of the frame must not label this student.
    far = [{"name": "cell phone", "confidence": 0.91, "box": (80, 650, 70, 120)}]
    hit, conf = ClassroomEngine._phone_device_near_face(far, face, frame_shape)
    assert not hit, (hit, conf)


def test_action_phone_device_ignores_non_phone_screens_and_huge_boxes():
    frame_shape = (1080, 1920, 3)
    face = [800, 210, 120, 140]
    laptop = [{"name": "laptop", "confidence": 0.95, "box": (835, 510, 150, 120)}]
    hit, _ = ClassroomEngine._phone_device_near_face(laptop, face, frame_shape)
    assert not hit

    # A giant screen covering most of the body is not a credible handheld phone.
    huge = [{"name": "cell phone", "confidence": 0.99, "box": (720, 250, 430, 650)}]
    hit, _ = ClassroomEngine._phone_device_near_face(huge, face, frame_shape)
    assert not hit

def test_r2_release_contract_exposes_camera_quality_and_identity_guard():
    assert APP_VERSION.startswith(('1.22.0-v1-face-pro-r2','1.22.1-v1-face-pro-r3','1.22.2-v1-face-pro-camera-hd-v5','1.23.0-v1-face-pro-v6','1.24.0-v1-face-pro-v7','1.25.0-v1-face-pro-v8','1.26.0-v1-face-pro-v9','1.29.0-v1-face-pro-v12-operations'))
    cam = (ROOT / 'module_app' / 'camera.py').read_text(encoding='utf-8')
    walk = (ROOT / 'module_app' / 'walkby.py').read_text(encoding='utf-8')
    main = (ROOT / 'module_app' / 'main.py').read_text(encoding='utf-8')
    js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
    starter = (ROOT / 'START_CAMPUSFACE.bat').read_text(encoding='utf-8')
    migration = (ROOT / 'scripts' / 'apply_pro_r2_config.py').read_text(encoding='utf-8')
    assert 'camera_quality' in cam and 'sharpness_score' in cam
    assert 'resolution_fallback' in cam and '_mode_matches_plan' in cam
    assert 'identity_guard_state' in walk and 'VERIFYING_MISMATCH' in walk
    classroom = (ROOT / 'module_app' / 'classroom_engine.py').read_text(encoding='utf-8')
    devices = (ROOT / 'module_app' / 'device_context.py').read_text(encoding='utf-8')
    assert '_phone_device_near_face' in classroom and 'phone_source' in classroom
    assert 'def detect_devices' in devices and 'geometry fallback' in devices
    assert 'camera_quality' in main and 'Chất lượng camera' in main
    assert 'Camera quality' in js and 'Sharpness' in js
    assert 'apply_pro_r2_config.py' in starter and 'PRO_R2' in migration


if __name__ == '__main__':
    tests = [
        test_camera_quality_watchdog_flags_blur_and_exposure,
        test_camera_rejects_driver_that_ignores_requested_mode,
        test_identity_owner_prevents_duplicate_live_name,
        test_identity_mismatch_release_requires_reacquire,
        test_action_phone_device_near_student_is_detected_without_geometry_fallback,
        test_action_phone_device_ignores_non_phone_screens_and_huge_boxes,
        test_r2_release_contract_exposes_camera_quality_and_identity_guard,
    ]
    for fn in tests:
        fn(); print('[PASS]', fn.__name__)
    print('[OK] V1 FACE PRO R2 regression passed')
