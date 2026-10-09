from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import module_app.walkby as wb
from module_app.anti_spoof import LivenessDecision
from module_app.face_core import FaceObservation


def install_common_mocks():
    fake_face = np.zeros(15, dtype=np.float32)
    fake_face[:4] = [100, 100, 150, 180]
    fake_face[14] = .99
    obs = FaceObservation(
        face=fake_face,
        bbox=(100, 100, 150, 180),
        embedding=np.ones(16, dtype=np.float32),
        quality={"score": .90, "face_px": 150, "usable": True},
        pose="center", yaw=.04, pitch=.01,
    )
    wb.CORE.detect = lambda *a, **k: [fake_face]
    wb.CORE.observe = lambda *a, **k: obs
    wb.CORE.face_crop = lambda *a, **k: np.zeros((64, 64, 3), np.uint8)
    wb.CORE.encode_jpeg_data_url = lambda *a, **k: "data:image/jpeg;base64,AA=="
    wb.fetchone = lambda *a, **k: {
        "id": 7, "student_code": "SV007", "full_name": "Test Student",
        "class_name": "A", "faculty": "F",
    }
    return obs


def test_phone_photo_is_blocked_before_faceid_even_without_registration():
    install_common_mocks()
    calls = {"rank": 0, "unknown": 0, "spoof": 0, "success": 0}

    def rank(*a, **k):
        calls["rank"] += 1
        return [(7, .94), (8, .31)]

    wb.INDEX.rank = rank
    wb.ANTI_SPOOF.update = lambda *a, **k: LivenessDecision(
        "BLOCKED", .04,
        "Phát hiện khuôn mặt nằm trong màn hình/điện thoại hoặc ảnh phẳng qua nhiều khung hình",
        screen_score=.96, spoof_method="PHONE_SCREEN",
    )
    wb.add_spoof_event = lambda *a, **k: (
        calls.__setitem__("spoof", calls["spoof"] + 1)
        or {"id": 21, "event_at": "now", "status": "SPOOF_BLOCKED", "anti_spoof_passed": False}
    )
    wb.add_unknown_event = lambda *a, **k: (
        calls.__setitem__("unknown", calls["unknown"] + 1)
        or {"id": 22, "event_at": "now", "status": "UNREGISTERED"}
    )
    wb.add_event = lambda *a, **k: (
        calls.__setitem__("success", calls["success"] + 1) or {"id": 23}
    )

    result = wb.WalkByEngine().process("v115-preid-block", np.zeros((480, 640, 3), np.uint8))
    tr = result["tracks"][0]
    assert calls["rank"] == 0, calls
    assert calls["unknown"] == 0, calls
    assert calls["success"] == 0, calls
    assert calls["spoof"] == 1, calls
    assert tr["status"] == "SPOOF_BLOCKED", tr
    assert tr["spoof_blocked"] is True
    assert tr["candidate_student_id"] is None
    assert tr["liveness"]["spoof_method"] == "PHONE_SCREEN"


def test_faceid_waits_until_passive_gate_passes_without_active_challenge():
    install_common_mocks()
    calls = {"live": 0, "rank": 0, "success": 0, "unknown": 0}

    def live(*a, **k):
        calls["live"] += 1
        if calls["live"] == 1:
            return LivenessDecision("CHECKING", .46, "Đang xác minh thụ động · không cần nhìn camera")
        return LivenessDecision("PASS", .84, "Xác minh thụ động đa khung đạt · không cần nhìn camera")

    def rank(*a, **k):
        calls["rank"] += 1
        return [(7, .94), (8, .31)]

    wb.ANTI_SPOOF.update = live
    wb.INDEX.rank = rank
    wb.add_event = lambda *a, **k: (
        calls.__setitem__("success", calls["success"] + 1)
        or {"id": 31, "event_at": "now", "status": "RECOGNIZED", "anti_spoof_passed": True}
    )
    wb.add_spoof_event = lambda *a, **k: (_ for _ in ()).throw(AssertionError("spoof event should not fire"))
    wb.add_unknown_event = lambda *a, **k: (
        calls.__setitem__("unknown", calls["unknown"] + 1)
        or {"id": 32, "event_at": "now", "status": "UNREGISTERED"}
    )

    engine = wb.WalkByEngine()
    frame = np.zeros((480, 640, 3), np.uint8)
    first = engine.process("v115-preid-pass", frame)
    assert first["tracks"][0]["status"] == "VERIFYING_PASSIVE", first
    assert calls["rank"] == 0, calls
    assert calls["unknown"] == 0, calls

    second = engine.process("v115-preid-pass", frame)
    assert calls["rank"] == 1, calls
    assert calls["success"] == 1, calls
    assert second["tracks"][0]["recognized"] is True
    assert second["tracks"][0]["liveness"]["status"] == "PASS"


def test_v115_source_contract_has_no_active_liveness_prompt():
    anti = (ROOT / "module_app" / "anti_spoof.py").read_text(encoding="utf-8")
    walk = (ROOT / "module_app" / "walkby.py").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert "V1.15 Stage 0" in walk
    assert "before FaceID" in walk
    assert "no active" not in anti.lower() or "never asks" in anti.lower()
    for token in ("Chớp mắt một lần", "Quay nhẹ đầu sang trái", "Quay nhẹ đầu sang phải"):
        assert token not in anti
    assert "Passive anti-spoof trước FaceID" in js
    assert "Nghi giả mạo" in js


if __name__ == "__main__":
    tests = [
        test_phone_photo_is_blocked_before_faceid_even_without_registration,
        test_faceid_waits_until_passive_gate_passes_without_active_challenge,
        test_v115_source_contract_has_no_active_liveness_prompt,
    ]
    for fn in tests:
        fn()
        print("[PASS]", fn.__name__)
    print("[OK] V1.15 passive anti-spoof pre-FaceID contract passed")
