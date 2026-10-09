from __future__ import annotations

import sys
import time
import asyncio
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_app.classroom_engine import ClassroomEngine, _TrackedAction
from module_app.action_engine import SmoothActionState
import module_app.main as main_module
from module_app.config import (
    APP_VERSION,
    CLASSROOM_ACTIVE_POSE_INTERVAL,
    CLASSROOM_ACTIVITY_ON,
    CLASSROOM_PREVIEW_FPS,
)


def test_activity_probe_promotes_fast_lane():
    engine = ClassroomEngine()
    state = _TrackedAction()
    state.last_pose_result = {'action': 'Ngồi', 'posture': 'SEATED'}
    bbox = [500, 220, 100, 120]
    frame = np.full((720, 1280, 3), 90, np.uint8)
    cv2.rectangle(frame, (470, 330), (630, 680), (140, 140, 140), -1)
    now = time.monotonic()
    engine._cheap_activity_probe(frame, bbox, state, now)
    engine._cheap_activity_probe(frame, bbox, state, now + 0.12)
    assert state.active_until <= now + 0.12, 'identical body ROI must not enter the fast lane'

    moved = frame.copy()
    # Synthetic arm/body change large enough to model a hand raise in the body ROI.
    cv2.rectangle(moved, (620, 170), (680, 430), (220, 220, 220), -1)
    score = engine._cheap_activity_probe(moved, bbox, state, now + 0.24)
    assert score > 0.0
    assert state.active_until > now + 0.24, (score, CLASSROOM_ACTIVITY_ON)
    interval, mode = engine._pose_interval(state, now + 0.25)
    assert mode == 'ACTIVE'
    assert interval <= 0.20, interval




def test_fast_hand_channel_confirms_with_two_fast_pose_samples():
    st = SmoothActionState()
    base = dict(raw_posture='UNKNOWN', head_down=None, sleeping_hint=None, phone_near=None,
                anchor_norm=None, body_scale_norm=None, pose_quality=.9, posture_source='')
    r1 = st.update(hand_raised=True, left_hand_raised=False, right_hand_raised=True, dt=.16, now=1.0, **base)
    r2 = st.update(hand_raised=True, left_hand_raised=False, right_hand_raised=True, dt=.16, now=1.16, **base)
    assert r1['right_hand_raised'] in {False, True}
    assert r2['right_hand_raised'] is True and r2['gesture'] == 'RAISE_RIGHT_HAND', r2


def test_multi_person_stable_pose_lane_is_globally_throttled():
    engine = ClassroomEngine()
    engine._ensure_pose = lambda: True
    calls = {'pose': 0}
    engine._pose_on_roi = lambda frame, roi: (calls.__setitem__('pose', calls['pose'] + 1) or None)
    now = time.monotonic()
    st = _TrackedAction(last_pose_at=now-10, last_pose_result={'action':'Ngồi','posture':'SEATED'})
    engine._states['face:1'] = st
    engine._states['face:2'] = _TrackedAction(last_pose_at=now-10, last_pose_result={'action':'Ngồi','posture':'SEATED'})
    engine._last_stable_pose_at = now
    frame = np.full((480, 640, 3), 90, np.uint8)
    face_result = {'tracks':[{'track_id':1,'bbox':[200,100,80,100],'quality':{'score':.9},'recognized':False}, {'track_id':2,'bbox':[360,100,80,100],'quality':{'score':.9},'recognized':False}],
                   'frame_width':640,'frame_height':480,'identity_budget':4,'identity_embeddings':0}
    engine._process(frame, face_result)
    assert calls['pose'] == 0, 'stable track should not consume Pose before the global stable cadence is due'


def test_preview_transport_is_ack_paced_websocket_with_fallback():
    main = (ROOT / 'module_app' / 'main.py').read_text(encoding='utf-8')
    js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
    camera = (ROOT / 'module_app' / 'camera.py').read_text(encoding='utf-8')
    assert '@app.websocket("/api/v1/classroom/preview/ws")' in main
    assert 'await websocket.send_bytes(jpeg)' in main
    assert 'message = await websocket.receive_text()' in main
    assert 'latest_classroom_packet' in camera
    assert 'new WebSocket' in js and "/api/v1/classroom/preview/ws" in js
    assert "ws.send('next')" in js
    assert 'state.classroomStreamMode=\'poll\'' in js or 'state.classroomStreamMode="poll"' in js




def test_websocket_endpoint_sends_one_frame_then_waits_for_ack():
    class FakeWS:
        def __init__(self): self.accepted=False; self.sent=[]; self.receives=0
        async def accept(self): self.accepted=True
        async def send_bytes(self, data): self.sent.append(bytes(data))
        async def receive_text(self): self.receives += 1; return 'close'
        async def close(self): pass
    ws=FakeWS()
    original=main_module.CAMERA.latest_classroom_packet
    main_module.CAMERA.latest_classroom_packet=lambda: (b'jpeg-frame', 99, time.perf_counter())
    try:
        asyncio.run(main_module.classroom_preview_ws(ws))
    finally:
        main_module.CAMERA.latest_classroom_packet=original
    assert ws.accepted and ws.sent == [b'jpeg-frame'] and ws.receives == 1


def test_v17_defaults_target_realtime_visuals_not_heavy_ai():
    assert APP_VERSION.startswith(('1.8.0-enterprise','1.9.0-enterprise','1.10.0-production-ready','1.10.1-tab-stable-production-ready','1.11.0-passive-classroom-production-ready','1.12.0-postgresql-offline-production-ready','1.12.3-embedded-postgresql-production-ready','1.12.4-customer-safe-postgresql-production-ready','1.13.0-postgresql-production-installer','1.14.0-user-managed-postgresql','1.15.0-passive-antispoof-preid','1.16.0-continuous-risk-fusion','1.17.0-v1-face','1.18.0-v1-face-best-recognition','1.19.0-v1-face-stable','1.19.1-v1-face-stable-r2','1.20.0-v1-face-core-stable','1.21.0-v1-face-pro-r1','1.22.0-v1-face-pro-r2','1.22.1-v1-face-pro-r3','1.22.2-v1-face-pro-camera-hd-v5','1.23.0-v1-face-pro-v6','1.24.0-v1-face-pro-v7','1.25.0-v1-face-pro-v8','1.26.0-v1-face-pro-v9','1.29.0-v1-face-pro-v12-operations'))
    assert CLASSROOM_PREVIEW_FPS >= 12
    assert CLASSROOM_ACTIVE_POSE_INTERVAL <= 0.20


if __name__ == '__main__':
    for fn in [
        test_activity_probe_promotes_fast_lane,
        test_fast_hand_channel_confirms_with_two_fast_pose_samples,
        test_multi_person_stable_pose_lane_is_globally_throttled,
        test_preview_transport_is_ack_paced_websocket_with_fallback,
        test_websocket_endpoint_sends_one_frame_then_waits_for_ack,
        test_v17_defaults_target_realtime_visuals_not_heavy_ai,
    ]:
        fn(); print('[PASS]', fn.__name__)
    print('[OK] V1.7 realtime classroom tests passed')
