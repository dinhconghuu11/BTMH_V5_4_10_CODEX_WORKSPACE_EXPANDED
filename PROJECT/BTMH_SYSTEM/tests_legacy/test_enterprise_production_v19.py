from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_app.action_engine import SmoothActionState, extract_pose_features
from module_app.walkby import Track, WalkByEngine


def test_hand_raise_accepts_clear_wrist_even_with_weak_elbow():
    # COCO17 synthetic upper body: right wrist well above right shoulder, elbow visibility weak.
    kp = np.zeros((17, 2), np.float32)
    conf = np.zeros(17, np.float32)
    kp[5] = [200, 250]; kp[6] = [300, 250]
    kp[11] = [215, 420]; kp[12] = [285, 420]
    kp[8] = [310, 180]; kp[10] = [320, 80]
    conf[[5, 6, 11, 12, 10]] = [0.95, 0.95, 0.90, 0.90, 0.82]
    conf[8] = 0.10  # weak elbow should not erase an obvious raised wrist
    feat = extract_pose_features(kp, conf, (140, 40, 240, 500), (720, 1280, 3))
    assert feat['right_hand_raised'] is True, feat


def test_sit_stand_transition_is_not_classroom_translation():
    st = SmoothActionState(posture='STANDING', standing_score=0.9)
    base = dict(hand_raised=False, left_hand_raised=False, right_hand_raised=False,
                head_down=None, sleeping_hint=None, phone_near=None, pose_quality=.9,
                posture_source='LEG_ANGLE', body_scale_norm=.28)
    # establish motion history around one seat
    t = 1.0
    for i in range(5):
        st.update(raw_posture='STANDING', anchor_norm=(.5, .35+i*.002), dt=.18, now=t, **base); t += .18
    # strong vertical posture transition at same horizontal seat location
    r = None
    for i in range(5):
        r = st.update(raw_posture='SEATED', anchor_norm=(.5, .48+i*.002), dt=.18, now=t, **base); t += .18
    assert r is not None
    assert r['moving'] is False, r


def test_tracker_reassociates_large_vertical_change_with_short_gap():
    eng = WalkByEngine()
    now = 10.0
    tr = Track(1, (250, 80, 90, 110), now-.4, now-.4, (295, 135), recognized=True, recognized_student_id=7)
    tracks = {1: tr}
    # face drops substantially when person sits; within grace it should keep Track 1.
    obs = SimpleNamespace(bbox=(250, 245, 95, 115), quality={'score': .9})
    out = eng._assign(tracks, [obs], now)
    assert out and out[0][0].id == 1, [x[0].id for x in out]
    assert tracks[1].recognized_student_id == 7


def test_history_ui_and_security_semantics_are_present():
    html = (ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
    js = (ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
    main = (ROOT/'module_app'/'main.py').read_text(encoding='utf-8')
    db = (ROOT/'module_app'/'db.py').read_text(encoding='utf-8')
    cfg = (ROOT/'module_app'/'config.py').read_text(encoding='utf-8')
    assert '1.9.0-enterprise-production' in cfg
    for token in ('CHECK-IN THÀNH CÔNG','CHECK-IN THẤT BẠI','ĐĂNG KÝ FACEID','GIẢ MẠO BỊ CHẶN','Phương thức bị phát hiện'):
        assert token in html, token
    assert '/api/v1/history/feed' in main
    assert 'CHECKIN_FAILED' in main and 'PHONE_SCREEN' in main and 'FACE_REGISTER_SUCCESS' in main
    assert 'checkin_result": "FAILED"' in db
    assert ("setEntryBadge('Check-in thất bại','bad')" in js) or ("setEntryBadge('Nghi giả mạo','bad')" in js)
    assert ("full_name:unregistered?'Chưa đăng ký':(s.full_name||'')" in js) or ("full_name:blocked?'Nghi giả mạo'" in js)


if __name__ == '__main__':
    tests=[
        test_hand_raise_accepts_clear_wrist_even_with_weak_elbow,
        test_sit_stand_transition_is_not_classroom_translation,
        test_tracker_reassociates_large_vertical_change_with_short_gap,
        test_history_ui_and_security_semantics_are_present,
    ]
    for fn in tests:
        fn(); print('[PASS]', fn.__name__)
    print('[OK] V1.9 Enterprise Production contract')
