from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import module_app.anti_spoof as anti
from module_app.anti_spoof import AntiSpoofEngine
from module_app.device_context import DeviceEvidence, DeviceContextEngine
from module_app.passive_pad import PadResult, PassivePadEngine


class Obs:
    bbox = (210, 120, 120, 160)
    yaw = 0.12
    pitch = -0.08


class PadSeq:
    def __init__(self, rows):
        self.rows = list(rows)
        self.i = 0

    def predict(self, image, bbox):
        row = self.rows[min(self.i, len(self.rows) - 1)]
        self.i += 1
        return PadResult(True, **row)


class PadMissing:
    def predict(self, image, bbox):
        return PadResult(False, reason="model missing")


class DeviceHint:
    def __init__(self, risk=0.52):
        self.risk = risk

    def evaluate_face(self, image, bbox, now=None):
        return DeviceEvidence(
            risk=self.risk,
            hard=False,
            reason="SCREEN_GEOMETRY_HINT",
            source="geometry_hint",
            device="screen/photo-hint",
            geometry_score=self.risk,
        )


class DeviceClean:
    def evaluate_face(self, image, bbox, now=None):
        return DeviceEvidence(risk=0.05, hard=False, source="none")


def test_geometry_requires_strict_closed_carrier_for_hard_block():
    eng = DeviceContextEngine()
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = 120
    import cv2
    # Background lines alone should not become a strict carrier.
    cv2.line(img, (120, 40), (120, 440), (240, 240, 240), 5)
    cv2.line(img, (520, 40), (520, 440), (240, 240, 240), 5)
    ev = eng._geometry_carrier(img, Obs.bbox)
    assert not ev.hard, ev.public()
    assert ev.source in {"geometry_hint", "none"}, ev.public()


def test_genuine_face_can_pass_despite_geometry_hint():
    original_pad, original_device = anti.PAD, anti.DEVICE_CONTEXT
    try:
        anti.PAD = PadSeq([
            dict(live_score=.91, spoof_score=.09, print_score=.04, replay_score=.05, label="REAL"),
            dict(live_score=.90, spoof_score=.10, print_score=.05, replay_score=.05, label="REAL"),
            dict(live_score=.93, spoof_score=.07, print_score=.03, replay_score=.04, label="REAL"),
            dict(live_score=.89, spoof_score=.11, print_score=.05, replay_score=.06, label="REAL"),
            dict(live_score=.92, spoof_score=.08, print_score=.03, replay_score=.05, label="REAL"),
        ])
        anti.DEVICE_CONTEXT = DeviceHint(.52)
        eng = AntiSpoofEngine()
        eng._face_mesh_attempted = True
        eng._face_mesh = False
        frame = np.zeros((480, 640, 3), np.uint8)
        decision = None
        for i in range(5):
            decision = eng.update("real", frame, Obs(), now=100 + i * .15)
        assert decision is not None
        assert decision.status == "PASS", decision.public()
        assert decision.spoof_method == ""
        assert decision.signals.get("geometry_is_hint_only") is True
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = original_pad, original_device


def test_repeated_pad_replay_blocks_before_faceid():
    original_pad, original_device = anti.PAD, anti.DEVICE_CONTEXT
    try:
        anti.PAD = PadSeq([
            dict(live_score=.08, spoof_score=.92, print_score=.15, replay_score=.77, label="REPLAY"),
            dict(live_score=.06, spoof_score=.94, print_score=.12, replay_score=.82, label="REPLAY"),
            dict(live_score=.05, spoof_score=.95, print_score=.10, replay_score=.85, label="REPLAY"),
            dict(live_score=.07, spoof_score=.93, print_score=.13, replay_score=.80, label="REPLAY"),
        ])
        anti.DEVICE_CONTEXT = DeviceClean()
        eng = AntiSpoofEngine()
        eng._face_mesh_attempted = True
        eng._face_mesh = False
        frame = np.zeros((480, 640, 3), np.uint8)
        decision = None
        for i in range(4):
            decision = eng.update("phone", frame, Obs(), now=200 + i * .15)
        assert decision is not None
        assert decision.status == "BLOCKED", decision.public()
        assert decision.spoof_method == "REPLAY_SCREEN", decision.public()
        assert decision.risk_score >= .90
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = original_pad, original_device


def test_missing_pad_uses_context_fallback_before_faceid():
    original_pad, original_device = anti.PAD, anti.DEVICE_CONTEXT
    try:
        anti.PAD = PadMissing()
        anti.DEVICE_CONTEXT = DeviceClean()
        eng = AntiSpoofEngine()
        eng._face_mesh_attempted = True
        eng._face_mesh = False
        frame = np.zeros((480, 640, 3), np.uint8)
        d = None
        for i in range(3):
            d = eng.update("missing", frame, Obs(), now=300 + i * .2)
        assert d is not None
        assert d.status == "PASS", d.public()
        assert d.signals.get("fallback") is True, d.public()
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = original_pad, original_device


def test_pad_preprocessing_contract_and_release_source():
    probs = PassivePadEngine._softmax(np.asarray([[1.0, 0.0, -1.0]], np.float32))
    assert probs.shape == (3,)
    assert abs(float(probs.sum()) - 1.0) < 1e-5

    config = (ROOT / "module_app" / "config.py").read_text(encoding="utf-8")
    walk = (ROOT / "module_app" / "walkby.py").read_text(encoding="utf-8")
    registry = (ROOT / "module_app" / "registry.py").read_text(encoding="utf-8")
    downloader = (ROOT / "scripts" / "download_models.py").read_text(encoding="utf-8")
    assert 'PAD_MODEL_V2 = MODELS_DIR / "minifasnet_v2.onnx"' in config
    assert 'MODULE_ONE_SHOT_CONF", "0.72"' in config
    assert 'live_status == "PASS"' in walk
    assert '0.60 * best + 0.24 * top_mean + 0.16 * centroid_score' in registry
    assert 'd7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b' in downloader


if __name__ == "__main__":
    tests = [
        test_geometry_requires_strict_closed_carrier_for_hard_block,
        test_genuine_face_can_pass_despite_geometry_hint,
        test_repeated_pad_replay_blocks_before_faceid,
        test_missing_pad_uses_context_fallback_before_faceid,
        test_pad_preprocessing_contract_and_release_source,
    ]
    for fn in tests:
        fn()
        print("[PASS]", fn.__name__)
    print("[OK] V1 FACE Best Recognition PAD + FaceID consensus contract passed")
