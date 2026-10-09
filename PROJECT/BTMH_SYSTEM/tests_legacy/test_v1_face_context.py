from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np

from module_app.anti_spoof import AntiSpoofEngine
from module_app.device_context import DeviceContextEngine


def _synthetic_phone() -> tuple[np.ndarray, tuple[int, int, int, int]]:
    img = np.full((540, 880, 3), 55, np.uint8)
    # phone body/screen
    cv2.rectangle(img, (270, 70), (590, 520), (18, 18, 18), 16)
    cv2.rectangle(img, (286, 92), (574, 502), (220, 220, 220), -1)
    # UI header and fake face patch
    cv2.rectangle(img, (300, 105), (560, 205), (242, 242, 242), -1)
    cv2.rectangle(img, (350, 315), (478, 492), (110, 125, 145), -1)
    cv2.circle(img, (390, 380), 10, (30, 30, 30), -1)
    cv2.circle(img, (438, 380), 10, (30, 30, 30), -1)
    cv2.line(img, (395, 445), (440, 445), (35, 35, 35), 3)
    return img, (350, 315, 128, 177)


def _synthetic_real() -> tuple[np.ndarray, tuple[int, int, int, int]]:
    img = np.full((540, 880, 3), 165, np.uint8)
    # textured classroom background behind a real face, deliberately with some lines
    for x in range(80, 820, 80):
        cv2.line(img, (x, 0), (x, 540), (145, 145, 145), 2)
    cv2.ellipse(img, (440, 280), (80, 110), 0, 0, 360, (105, 125, 150), -1)
    cv2.circle(img, (410, 260), 7, (25, 25, 25), -1)
    cv2.circle(img, (465, 260), 7, (25, 25, 25), -1)
    cv2.line(img, (415, 335), (462, 335), (40, 40, 40), 3)
    return img, (360, 170, 160, 220)


def test_context_phone_vs_real_contract():
    eng = DeviceContextEngine()
    phone, phone_box = _synthetic_phone()
    real, real_box = _synthetic_real()
    pe = eng.evaluate_face(phone, phone_box, now=100.0)
    re = eng.evaluate_face(real, real_box, now=101.0)
    assert pe.risk >= 0.80, pe.public()
    assert pe.hard, pe.public()
    assert re.risk < 0.58, re.public()
    assert not re.hard, re.public()


def test_phone_blocks_before_faceid_contract():
    img, bbox = _synthetic_phone()
    obs = SimpleNamespace(bbox=bbox, yaw=0.0, pitch=0.0)
    eng = AntiSpoofEngine()
    d1 = eng.update('t', img, obs, now=200.0)
    d2 = eng.update('t', img, obs, now=200.2)
    assert d1.status in {'CHECKING', 'BLOCKED'}
    assert d2.status == 'BLOCKED', d2.public()
    assert 'SCREEN' in (d2.spoof_method or d2.reason).upper() or 'PHONE' in (d2.spoof_method or d2.reason).upper()
