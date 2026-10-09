from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import module_app.walkby as wb
from module_app.anti_spoof import AntiSpoofEngine, LivenessDecision
from module_app.face_core import FaceObservation


class DummyObs:
    bbox = (100, 100, 120, 160)
    yaw = 0.0
    pitch = 0.0


def test_pass_is_revoked_and_phone_is_blocked_on_same_track():
    eng = AntiSpoofEngine()
    eng._face_mesh_attempted = True
    eng._face_mesh = False
    seq = iter([0.10] * 7 + [0.92, 0.93])
    eng._rectangular_carrier_score = lambda *a, **k: next(seq)  # type: ignore[attr-defined]
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    t0 = 1000.0
    decision = None
    for i in range(7):
        decision = eng.update("track-1", frame, DummyObs(), now=t0 + i * 0.12)
    assert decision is not None and decision.status == "PASS", decision

    suspicious = eng.update("track-1", frame, DummyObs(), now=t0 + 0.90)
    assert suspicious.status == "CHECKING", suspicious
    assert suspicious.context_score >= 0.90
    assert suspicious.score <= 0.30

    blocked = eng.update("track-1", frame, DummyObs(), now=t0 + 1.02)
    assert blocked.status == "BLOCKED", blocked
    assert blocked.spoof_method == "FACE_INSIDE_PHONE_SCREEN"
    assert blocked.risk_score >= 0.90


def _install_walkby_mocks():
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


def test_live_identity_is_hidden_when_context_becomes_suspicious():
    _install_walkby_mocks()
    calls = {"live": 0, "success": 0}

    def live(*a, **k):
        calls["live"] += 1
        if calls["live"] == 1:
            return LivenessDecision("PASS", .82, "pass", risk_score=.05, context_score=.08)
        return LivenessDecision(
            "CHECKING", .28, "screen check", risk_score=.78, context_score=.91,
            signals={"screen_current": .91},
        )

    wb.ANTI_SPOOF.update = live
    wb.INDEX.rank = lambda *a, **k: [(7, .94), (8, .31)]
    wb.add_event = lambda *a, **k: (
        calls.__setitem__("success", calls["success"] + 1)
        or {"id": 31, "event_at": "now", "status": "RECOGNIZED", "anti_spoof_passed": True}
    )
    wb.add_spoof_event = lambda *a, **k: {"id": 99, "event_at": "now", "status": "SPOOF_BLOCKED"}
    wb.add_unknown_event = lambda *a, **k: {"id": 32, "event_at": "now", "status": "UNREGISTERED"}
    wb.apply_successful_checkin = lambda *a, **k: None

    engine = wb.WalkByEngine()
    frame = np.zeros((480, 640, 3), np.uint8)
    first = engine.process("v116-revoke", frame)
    assert first["tracks"][0]["recognized"] is True, first
    assert calls["success"] == 1

    second = engine.process("v116-revoke", frame)
    tr = second["tracks"][0]
    assert tr["recognized"] is False, tr
    assert tr["student_id"] is None, tr
    assert tr["status"] == "VERIFYING_PASSIVE", tr


def test_block_event_does_not_expose_identity_candidate():
    _install_walkby_mocks()
    captured = {}
    wb.INDEX.rank = lambda *a, **k: [(7, .94)]
    wb.ANTI_SPOOF.update = lambda *a, **k: LivenessDecision(
        "BLOCKED", .08, "phone", screen_score=.91,
        spoof_method="FACE_INSIDE_PHONE_SCREEN", risk_score=.97, context_score=.93,
    )

    def add_spoof(*args, **kwargs):
        captured.update(kwargs)
        return {"id": 44, "event_at": "now", "status": "SPOOF_BLOCKED"}

    wb.add_spoof_event = add_spoof
    wb.add_unknown_event = lambda *a, **k: (_ for _ in ()).throw(AssertionError("unknown should not fire"))
    wb.add_event = lambda *a, **k: (_ for _ in ()).throw(AssertionError("success should not fire"))
    result = wb.WalkByEngine().process("v116-private-block", np.zeros((480, 640, 3), np.uint8))
    tr = result["tracks"][0]
    assert tr["status"] == "SPOOF_BLOCKED"
    assert tr["candidate_student_id"] is None
    assert captured.get("student_id") is None
    assert float(captured.get("confidence") or 0.0) == 0.0


def test_v116_source_contract():
    anti = (ROOT / "module_app" / "anti_spoof.py").read_text(encoding="utf-8")
    walk = (ROOT / "module_app" / "walkby.py").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert "PASS is intentionally *not terminal*" in anti
    assert "continuous guard" in walk
    assert "risk_score" in anti
    assert "context_score" in anti
    assert "Context anti-spoof" in js


if __name__ == "__main__":
    tests = [
        test_pass_is_revoked_and_phone_is_blocked_on_same_track,
        test_live_identity_is_hidden_when_context_becomes_suspicious,
        test_block_event_does_not_expose_identity_candidate,
        test_v116_source_contract,
    ]
    for fn in tests:
        fn()
        print("[PASS]", fn.__name__)
    print("[OK] V1.16 continuous passive risk-fusion anti-spoof contract passed")
