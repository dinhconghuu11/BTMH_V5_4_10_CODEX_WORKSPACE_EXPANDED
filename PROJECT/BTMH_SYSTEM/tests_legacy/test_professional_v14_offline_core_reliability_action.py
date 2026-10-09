from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = tempfile.TemporaryDirectory(prefix="campusface-v14-test-")
os.environ["CAMPUSFACE_DB_MODE"] = "sqlite"
os.environ["CAMPUSFACE_DATA_ROOT"] = _tmp.name
os.environ["CAMPUSFACE_SAME_CAMERA_DEDUP_SEC"] = "6"
os.environ["CAMPUSFACE_CROSS_CAMERA_DEDUP_SEC"] = "8"
os.environ["CAMPUSFACE_CLASSROOM_EVENT_DEDUP_SEC"] = "6"

from module_app.classroom_engine import ClassroomEngine, _TrackedAction
from module_app.config import (
    APP_VERSION,
    CLASSROOM_ACTION_HAND_CONFIRM_SEC,
    CLASSROOM_ACTION_PHONE_CONFIRM_SEC,
    CLASSROOM_ACTION_HEAD_DOWN_CONFIRM_SEC,
)
from module_app.db import add_classroom_event, add_event, execute, init_db, utc_now


def _base_item(**overrides):
    item = {
        "student_id": 1,
        "confidence": 0.93,
        "posture": "UNKNOWN",
        "posture_confidence": 0.0,
        "posture_label": "Chưa xác định",
        "activity_label": "Ổn định",
        "hand_raised": False,
        "left_hand_raised": False,
        "right_hand_raised": False,
        "hand_side": "NONE",
        "gesture": "NONE",
        "moving": False,
        "motion": "STILL",
        "movement_score": 0.0,
        "head_down": False,
        "sleeping": False,
        "using_phone": False,
        "phone_source": "",
        "phone_confidence": 0.0,
        "pose_quality": 0.9,
        "bbox": [10, 10, 100, 180],
    }
    item.update(overrides)
    return item


def test_temporal_episode_gate():
    eng = ClassroomEngine()
    captured = []

    def capture(**kwargs):
        captured.append({k: kwargs.get(k) for k in ("kind", "label", "phase", "episode_id", "duration_sec")})

    eng._emit_episode_record = capture  # type: ignore[method-assign]
    st = _TrackedAction()
    hand = _base_item(hand_raised=True)
    eng._emit_if_changed("face:1", hand, st, 10.0)
    eng._emit_if_changed("face:1", hand, st, 10.0 + CLASSROOM_ACTION_HAND_CONFIRM_SEC * 0.75)
    assert not [x for x in captured if x["kind"] == "HAND_RAISED"], captured
    eng._emit_if_changed("face:1", hand, st, 10.0 + CLASSROOM_ACTION_HAND_CONFIRM_SEC + 0.02)
    hand_starts = [x for x in captured if x["kind"] == "HAND_RAISED" and x["phase"] == "START"]
    assert len(hand_starts) == 1, captured
    eng._emit_if_changed("face:1", hand, st, 11.5)
    assert len([x for x in captured if x["kind"] == "HAND_RAISED" and x["phase"] == "START"]) == 1
    off = _base_item(hand_raised=False)
    eng._emit_if_changed("face:1", off, st, 11.6)
    eng._emit_if_changed("face:1", off, st, 12.5)
    assert len([x for x in captured if x["kind"] == "HAND_RAISED" and x["phase"] == "END"]) == 1, captured

    st2 = _TrackedAction()
    captured.clear()
    phone = _base_item(using_phone=True, phone_source="DEVICE_DETECTOR", phone_confidence=.88)
    eng._emit_if_changed("face:2", phone, st2, 20.0)
    eng._emit_if_changed("face:2", phone, st2, 20.0 + CLASSROOM_ACTION_PHONE_CONFIRM_SEC - .05)
    assert not captured
    eng._emit_if_changed("face:2", phone, st2, 20.0 + CLASSROOM_ACTION_PHONE_CONFIRM_SEC + .05)
    assert len([x for x in captured if x["kind"] == "PHONE_USE" and x["phase"] == "START"]) == 1, captured

    st3 = _TrackedAction()
    captured.clear()
    down = _base_item(head_down=True)
    eng._emit_if_changed("face:3", down, st3, 30.0)
    eng._emit_if_changed("face:3", down, st3, 30.0 + CLASSROOM_ACTION_HEAD_DOWN_CONFIRM_SEC - .1)
    assert not captured
    eng._emit_if_changed("face:3", down, st3, 30.0 + CLASSROOM_ACTION_HEAD_DOWN_CONFIRM_SEC + .1)
    assert len([x for x in captured if x["kind"] == "HEAD_DOWN" and x["phase"] == "START"]) == 1, captured


def test_load_policy():
    eng = ClassroomEngine()
    fps, budget, load = eng._runtime_policy({"performance": {"load_state": "HIGH"}})
    assert load == "HIGH" and fps <= 2.0 and budget == 1, (fps, budget, load)
    eng._last_result = {"tracks": [{} for _ in range(50)]}
    fps, budget, _ = eng._runtime_policy({"performance": {"load_state": "NORMAL"}})
    assert fps <= 3.0 and budget == 1, (fps, budget)


def test_db_duplicate_guards():
    init_db()
    now = utc_now()
    execute(
        "INSERT INTO students(student_code,full_name,class_name,faculty,consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        ("V14-001", "Test Student", "A", "", now, now, now),
    )
    first = add_event(1, "service:1", .92, {"reason": "test"}, camera_source="Camera laptop")
    same = add_event(1, "service:2", .91, {"reason": "track churn"}, camera_source="Camera laptop")
    cross = add_event(1, "service:3", .90, {"reason": "handover"}, camera_source="Camera PTZ")
    assert not first.get("deduplicated")
    assert same.get("deduplicated") and same.get("duplicate_scope") == "SAME_CAMERA", same
    assert cross.get("deduplicated") and cross.get("duplicate_scope") == "CROSS_CAMERA", cross

    a = add_classroom_event(1, "face:1", "Giơ tay", .9, {"event_phase": "START", "episode_id": "x", "event_dedup_sec": 6})
    b = add_classroom_event(1, "face:99", "Giơ tay", .9, {"event_phase": "START", "episode_id": "y", "event_dedup_sec": 6})
    c = add_classroom_event(1, "face:99", "Giơ tay", .9, {"event_phase": "END", "episode_id": "y", "event_dedup_sec": 6})
    assert not a.get("deduplicated")
    assert b.get("deduplicated"), b
    assert not c.get("deduplicated"), c


def test_offline_contract_files():
    assert APP_VERSION.startswith("1.31.") and "v1-face-pro-v14" in APP_VERSION
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    main = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
    engine = (ROOT / "module_app" / "classroom_engine.py").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html
    assert "cdn.jsdelivr.net" not in html
    assert "unpkg.com" not in html
    assert '"cloud_ai_used": False' in main
    assert "PTZ_MOVING" in engine and "LATEST_FRAME_DROP_STALE" in engine
    assert "event_phase" in js


if __name__ == "__main__":
    test_temporal_episode_gate()
    test_load_policy()
    test_db_duplicate_guards()
    test_offline_contract_files()
    print("[OK] Professional V14 offline core reliability + temporal action contract")
