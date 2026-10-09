from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


CORE = Path(__file__).resolve().parents[1]


def test_v21_history_ui_split_contract():
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'data-history-mode="RECOGNITION"' in html
    assert 'data-history-mode="HR"' in html
    assert 'id="historySessionsPanel"' in html
    assert "/api/v1/history/recognition" in js
    assert "/api/v1/history/hr" in js
    assert "historyHrSessions" in js


def test_v21_hr_db_event_session_roundtrip(tmp_path: Path):
    data_root = tmp_path / "data-root"
    script = r'''
from module_app.db import (
    init_db, execute, utc_now, open_presence_session, add_hr_event,
    close_presence_session, close_all_open_presence_sessions, hr_event_history, hr_presence_history, hr_current_presence,
)
init_db()
now = utc_now()
sid = execute(
    "INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
    ("NV001","Nhan Vien Test","Ky thuat","CNTT","","",now,"GRANTED",now,now),
)
s = open_presence_session(sid, "t1", "hikvision")
assert s["created"] is True
s2 = open_presence_session(sid, "t1", "hikvision")
assert s2["created"] is False
first = add_hr_event(sid, "t1", "PRESENCE_START", detail={"status":"SEATED"}, dedup_seconds=60)
second = add_hr_event(sid, "t1", "PRESENCE_START", detail={"status":"SEATED"}, dedup_seconds=60)
assert first["deduplicated"] is False
assert second["deduplicated"] is True
assert len(hr_current_presence()) == 1
closed = close_presence_session(sid, end_reason="VIRTUAL_GATE_OUT")
assert closed and closed["status"] == "CLOSED"
assert len(hr_current_presence()) == 0
assert len(hr_event_history()) == 1
assert len(hr_presence_history()) == 1
# Restart safety: an open row is closed before the next runtime rebuilds presence.
s3 = open_presence_session(sid, "t2", "hikvision")
assert s3["created"] is True
assert close_all_open_presence_sessions(end_reason="SYSTEM_RESTART") == 1
assert len(hr_current_presence()) == 0
print("PASS")
'''
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(CORE),
        "CAMPUSFACE_DB_MODE": "sqlite",
        "CAMPUSFACE_DATA_ROOT": str(data_root),
    })
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v21_office_hr_state_machine_contract():
    source = (CORE / "module_app" / "office_engine.py").read_text(encoding="utf-8")
    assert "status_debounce_sec" in source
    assert "event_cooldown_sec" in source
    assert "min_stable_dwell_sec" in source
    assert '"NOT_VISIBLE"' in source
    assert '"STATUS_CHANGE"' in source
    assert '"EXIT"' in source
    assert '"RETURN"' in source
    assert "_outside_students" in source
