from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_app.action_engine import SmoothActionState, extract_pose_features, vietnamese_action_label
import module_app.anti_spoof as anti
from module_app.anti_spoof import AntiSpoofEngine
from module_app.passive_pad import PadResult
from module_app.device_context import DeviceEvidence




class _PadFixed:
    def __init__(self, live, spoof, label):
        self.live=float(live); self.spoof=float(spoof); self.label=str(label)
    def predict(self, image, bbox):
        if self.label == 'REAL':
            return PadResult(True, live_score=self.live, spoof_score=self.spoof, print_score=self.spoof*0.5, replay_score=self.spoof*0.5, label='REAL')
        if self.label == 'REPLAY':
            return PadResult(True, live_score=self.live, spoof_score=self.spoof, print_score=0.08, replay_score=max(0.0,self.spoof-0.08), label='REPLAY')
        return PadResult(True, live_score=self.live, spoof_score=self.spoof, print_score=max(0.0,self.spoof-0.08), replay_score=0.08, label='PRINT')


class _DeviceClean:
    def evaluate_face(self, image, bbox, now=None):
        return DeviceEvidence(risk=0.04, hard=False, source='none')


def fake_obs(bbox=(535, 195, 210, 290), yaw=0.0, pitch=0.0):
    return SimpleNamespace(bbox=bbox, yaw=yaw, pitch=pitch)


def test_phone_or_print_rectangle_is_blocked():
    original_pad, original_device = anti.PAD, anti.DEVICE_CONTEXT
    try:
        anti.PAD = _PadFixed(.05, .95, 'REPLAY')
        anti.DEVICE_CONTEXT = _DeviceClean()
        eng = AntiSpoofEngine()
        eng._blink_observation = lambda *a, **k: None
        img = np.full((720, 1280, 3), 180, np.uint8)
        cv2.rectangle(img, (390, 90), (890, 650), (10, 10, 10), 18)
        cv2.rectangle(img, (420, 120), (860, 620), (220, 220, 220), -1)
        cv2.ellipse(img, (640, 340), (105, 145), 0, 0, 360, (150, 160, 170), -1)
        decision = None
        for i in range(4):
            decision = eng.update('screen', img, fake_obs(), now=1.0+i*.2)
        assert decision and decision.blocked, decision.public() if decision else None
        assert decision.risk_score >= 0.90
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = original_pad, original_device


def test_natural_multiframe_face_passes_without_active_challenge():
    original_pad, original_device = anti.PAD, anti.DEVICE_CONTEXT
    try:
        anti.PAD = _PadFixed(.91, .09, 'REAL')
        anti.DEVICE_CONTEXT = _DeviceClean()
        eng = AntiSpoofEngine()
        eng._blink_observation = lambda *a, **k: None
        rng = np.random.default_rng(4)
        decision = None
        for i, yaw in enumerate([0.00, 0.04, 0.09, 0.14, 0.18, 0.12, 0.06]):
            img = np.full((720, 1280, 3), 127, np.uint8)
            patch = rng.normal(128 + i * 2, 14, (240, 180, 3)).clip(0, 255).astype(np.uint8)
            img[220:460, 550:730] = patch
            decision = eng.update('real', img, fake_obs((550, 220, 180, 240), yaw, (i % 3 - 1) * 0.025), now=1 + i * 0.15)
        assert decision is not None and decision.passed, decision.public() if decision else None
        assert decision.challenge == '' and decision.challenge_text == ''
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = original_pad, original_device


def test_static_real_face_can_pass_passively_without_blink_or_turn():
    original_pad, original_device = anti.PAD, anti.DEVICE_CONTEXT
    try:
        anti.PAD = _PadFixed(.92, .08, 'REAL')
        anti.DEVICE_CONTEXT = _DeviceClean()
        eng = AntiSpoofEngine()
        eng._blink_observation = lambda *a, **k: None
        img = np.full((720, 1280, 3), 132, np.uint8)
        decision = None
        for i in range(6):
            decision = eng.update('still', img, fake_obs((550, 220, 180, 240), 0.0, 0.0), now=1 + i * 0.15)
        assert decision is not None and decision.passed, decision.public()
        assert decision.challenge == ''
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = original_pad, original_device


def base_pose():
    kp = np.zeros((17, 2), dtype=np.float32)
    conf = np.zeros(17, dtype=np.float32)
    points = {
        0: (250, 80), 5: (210, 150), 6: (290, 150), 7: (205, 230), 8: (295, 230),
        9: (205, 310), 10: (295, 310), 11: (220, 300), 12: (280, 300),
        13: (220, 430), 14: (280, 430), 15: (220, 550), 16: (280, 550),
    }
    for i, p in points.items():
        kp[i] = p
        conf[i] = 0.95
    return kp, conf


def test_left_right_hand_are_independent():
    kp, conf = base_pose()
    # COCO left wrist/elbow/shoulder 9/7/5 raised, right remains down.
    kp[7] = (210, 125)
    kp[9] = (210, 65)
    f = extract_pose_features(kp, conf, (100, 40, 300, 540), (720, 1280, 3))
    assert f['left_hand_raised'] is True
    assert f['right_hand_raised'] is False
    st = SmoothActionState()
    out = None
    for i in range(12):
        out = st.update(
            raw_posture='STANDING', hand_raised=f['hand_raised'],
            left_hand_raised=f['left_hand_raised'], right_hand_raised=f['right_hand_raised'],
            head_down=False, sleeping_hint=False, phone_near=False,
            anchor_norm=(0.5, 0.35), body_scale_norm=0.30,
            pose_quality=0.9, dt=0.1, now=i * 0.1,
            posture_source='LEG_ANGLE',
        )
    assert out and out['left_hand_raised'] and not out['right_hand_raised']
    label = vietnamese_action_label(out)
    assert label == 'Giơ tay', label


def test_pose_jitter_does_not_become_movement():
    st = SmoothActionState()
    rng = np.random.default_rng(8)
    out = None
    for i in range(25):
        jitter = rng.normal(0.0, 0.0015, 2)
        out = st.update(
            raw_posture='STANDING', hand_raised=False, left_hand_raised=False, right_hand_raised=False,
            head_down=False, sleeping_hint=False, phone_near=False,
            anchor_norm=(0.5 + float(jitter[0]), 0.35 + float(jitter[1])), body_scale_norm=0.30,
            pose_quality=0.9, dt=0.1, now=i * 0.1, posture_source='LEG_ANGLE',
        )
    assert out and not out['moving'], out


def test_real_translation_becomes_movement():
    st = SmoothActionState()
    out = None
    for i in range(24):
        x = 0.35 + min(0.18, i * 0.012)
        out = st.update(
            raw_posture='STANDING', hand_raised=False, left_hand_raised=False, right_hand_raised=False,
            head_down=False, sleeping_hint=False, phone_near=False,
            anchor_norm=(x, 0.35), body_scale_norm=0.30,
            pose_quality=0.9, dt=0.1, now=i * 0.1, posture_source='LEG_ANGLE',
        )
    assert out and out['moving'], out


if __name__ == '__main__':
    tests = [
        test_phone_or_print_rectangle_is_blocked,
        test_natural_multiframe_face_passes_without_active_challenge,
        test_static_real_face_can_pass_passively_without_blink_or_turn,
        test_left_right_hand_are_independent,
        test_pose_jitter_does_not_become_movement,
        test_real_translation_becomes_movement,
    ]
    for fn in tests:
        fn()
        print('[PASS]', fn.__name__)
    print('[OK] V1.5 security + Action Engine V2 regression passed')
