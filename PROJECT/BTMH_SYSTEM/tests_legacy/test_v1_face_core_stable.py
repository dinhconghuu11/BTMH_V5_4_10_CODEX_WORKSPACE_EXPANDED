from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import module_app.anti_spoof as anti
from module_app.anti_spoof import AntiSpoofEngine
from module_app.device_context import DeviceEvidence
from module_app.passive_pad import PadResult
from module_app.action_engine import vietnamese_action_label


class MissingPad:
    def predict(self, image, bbox):
        return PadResult(False, reason="optional PAD absent")


class CleanDevice:
    def evaluate_face(self, image, bbox, now=None):
        return DeviceEvidence(risk=.10, hard=False, source="none")


class PhoneCarrier:
    def evaluate_face(self, image, bbox, now=None):
        return DeviceEvidence(
            risk=.96, hard=True, reason="FACE_INSIDE_PHONE_OR_PHOTO",
            source="geometry_carrier", device="phone/photo-carrier",
            confidence=.96, inside_ratio=.97,
        )


OBS = SimpleNamespace(bbox=(120, 100, 130, 170), yaw=0.0, pitch=0.0)
FRAME = np.zeros((480, 640, 3), np.uint8)


def test_missing_pad_does_not_kill_faceid_gate():
    op, od = anti.PAD, anti.DEVICE_CONTEXT
    try:
        anti.PAD, anti.DEVICE_CONTEXT = MissingPad(), CleanDevice()
        eng = AntiSpoofEngine(); eng._face_mesh_attempted = True; eng._face_mesh = False
        d = None
        for i in range(3):
            d = eng.update("real", FRAME, OBS, now=10 + i * .2)
        assert d is not None and d.status == "PASS", d.public()
        assert d.signals.get("fallback") is True
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = op, od


def test_phone_carrier_blocks_before_faceid_without_pad():
    op, od = anti.PAD, anti.DEVICE_CONTEXT
    try:
        anti.PAD, anti.DEVICE_CONTEXT = MissingPad(), PhoneCarrier()
        eng = AntiSpoofEngine(); eng._face_mesh_attempted = True; eng._face_mesh = False
        d1 = eng.update("phone", FRAME, OBS, now=20.0)
        d2 = eng.update("phone", FRAME, OBS, now=20.2)
        assert d1.status == "CHECKING", d1.public()
        assert d2.status == "BLOCKED", d2.public()
        assert "PHONE" in (d2.spoof_method + d2.reason).upper() or "ẢNH" in d2.reason.upper()
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = op, od


def test_phone_action_has_customer_label():
    assert vietnamese_action_label({"using_phone": True, "hand_raised": True, "posture": "STANDING"}) == "Sử dụng điện thoại"


def test_smart_installer_reuses_runtime():
    text = (ROOT / "INSTALL_CURRENT_PC_WINDOWS.bat").read_text(encoding="utf-8", errors="ignore").lower()
    assert "runtime_quick_check.py" in text
    assert "no pip reinstall" in text
    assert "prepare_core_models.py" in text
    assert "pg_version" in text


if __name__ == "__main__":
    for fn in (
        test_missing_pad_does_not_kill_faceid_gate,
        test_phone_carrier_blocks_before_faceid_without_pad,
        test_phone_action_has_customer_label,
        test_smart_installer_reuses_runtime,
    ):
        fn(); print("[PASS]", fn.__name__)
    print("[OK] V1 FACE CORE STABLE regression passed")
