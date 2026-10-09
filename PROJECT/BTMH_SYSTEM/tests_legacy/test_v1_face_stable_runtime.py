from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_app.passive_pad import PassivePadEngine

HF = "d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b"
YAKHYO = "b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907"


def test_pad_supports_both_verified_exports():
    assert PassivePadEngine.profile_for_hash(HF) == "hf_live0_norm01"
    assert PassivePadEngine.profile_for_hash(YAKHYO) == "yakhyo_live1_raw255"
    assert PassivePadEngine.profile_for_hash("0" * 64) == ""



def test_pad_decode_contracts_are_not_mixed():
    eng = PassivePadEngine()
    eng._profile = "hf_live0_norm01"
    live, spoof, p0, p1, label = eng._decode(__import__("numpy").array([0.90, 0.06, 0.04], dtype="float32"))
    assert live > 0.89 and spoof < 0.11 and label == "REAL"
    eng._profile = "yakhyo_live1_raw255"
    live, spoof, p0, p1, label = eng._decode(__import__("numpy").array([0.04, 0.91, 0.05], dtype="float32"))
    assert live > 0.90 and spoof < 0.10 and label == "REAL"

def test_downloader_has_windows_friendly_pad_mirrors_and_aliases():
    text = (ROOT / "scripts" / "download_models.py").read_text(encoding="utf-8")
    assert "github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx" in text
    assert "github.com/leandroveronezi/go-onnxface/releases/download/models-v1/minifasnet_v2.onnx" in text
    assert "MiniFASNetV2.onnx" in text
    assert YAKHYO in text and HF in text


def test_ready_check_keeps_pad_optional_and_requires_pose_backend():
    text = (ROOT / "scripts" / "check_ready.py").read_text(encoding="utf-8")
    assert "Passive PAD enhancement" in text
    assert "context fallback" in text.lower()
    assert "self_test_pose_backend" in text
    assert "START is intentionally blocked" in text


def test_classroom_single_person_uses_full_frame_pose_fallback():
    text = (ROOT / "module_app" / "classroom_engine.py").read_text(encoding="utf-8")
    assert "def _pose_on_full_frame" in text
    assert "if len(prepared) == 1" in text
    assert "model_complexity=1" in text


if __name__ == "__main__":
    tests = [
        test_pad_supports_both_verified_exports,
        test_pad_decode_contracts_are_not_mixed,
        test_downloader_has_windows_friendly_pad_mirrors_and_aliases,
        test_ready_check_keeps_pad_optional_and_requires_pose_backend,
        test_classroom_single_person_uses_full_frame_pose_fallback,
    ]
    for fn in tests:
        fn()
        print("[PASS]", fn.__name__)
    print("[OK] V1 FACE STABLE runtime contract passed")
