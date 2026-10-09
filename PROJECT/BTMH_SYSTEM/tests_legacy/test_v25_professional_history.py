from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def test_history_has_two_real_workspaces():
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (CORE / "frontend" / "css" / "professional_v16_history_workspaces.css").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="historyRecognitionWorkspace"' in html
    assert 'id="historyHrWorkspace"' in html
    assert 'id="historyRecognitionBody"' in html
    assert 'id="historyHrBody"' in html
    assert 'id="historyCurrentPresence"' in html
    assert 'EVENT + SESSION' in html
    assert 'top:96px!important' in css
    assert "historyHrCurrent=hr.current||[]" in js
    assert "type!=='STATUS_CHANGE'" in js


def test_status_changes_are_not_persisted_by_default():
    src = (CORE / "module_app" / "office_engine.py").read_text(encoding="utf-8")
    assert '"persist_status_changes": False' in src
    assert 'cfg.get("persist_status_changes", False)' in src


def test_successful_recognition_is_session_deduplicated(tmp_path: Path):
    data_root = tmp_path / "data"
    script = r'''
from module_app.db import init_db, execute, utc_now, add_event, open_presence_session
init_db()
now=utc_now()
sid=execute("INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",("NV01","Nhan Vien","Van phong","","","",now,"GRANTED",now,now))
first=add_event(sid,"t1",0.93,{},camera_source="hikvision")
assert first.get("deduplicated") is False
open_presence_session(sid,"t1","hikvision")
second=add_event(sid,"t1",0.94,{},camera_source="hikvision")
assert second.get("deduplicated") is True
assert second.get("duplicate_scope") == "PRESENCE_SESSION"
print("PASS")
'''
    env=os.environ.copy();env.update({"PYTHONPATH":str(CORE),"CAMPUSFACE_DB_MODE":"sqlite","CAMPUSFACE_DATA_ROOT":str(data_root)})
    proc=subprocess.run([sys.executable,"-c",script],env=env,capture_output=True,text=True,timeout=30)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout
