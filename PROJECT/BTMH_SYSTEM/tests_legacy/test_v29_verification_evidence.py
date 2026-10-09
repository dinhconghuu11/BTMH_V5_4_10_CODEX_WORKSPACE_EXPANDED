from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def _run(script: str, data_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(CORE),
        "CAMPUSFACE_DB_MODE": "sqlite",
        "CAMPUSFACE_DATA_ROOT": str(data_root),
    })
    return subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=40)


def test_v29_static_contracts():
    production = (CORE / "module_app" / "production_ops.py").read_text(encoding="utf-8")
    office = (CORE / "module_app" / "office_engine.py").read_text(encoding="utf-8")
    main = (CORE / "module_app" / "main.py").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "def _verification_cases" in production
    assert "observation_count" in production
    assert "def persist_hr_evidence" in production
    assert "def hr_event_evidence_path" in production
    assert "persist_hr_evidence" in office
    assert 'meaningful = {"PRESENCE_START", "PRESENCE_END", "ENTRY", "RETURN", "EXIT"}' in office
    assert '/api/v1/history/hr/{event_id}/evidence.jpg' in main
    assert '"snapshot_url": f"/api/v1/history/hr/' in main
    assert "Case đang chờ xử lý" in html
    assert "Quan sát <b>${count}</b>" in js
    assert "previewImg.onerror" in js


def test_v29_verification_case_aggregation_and_case_review(tmp_path: Path):
    script = r'''
import json
from datetime import datetime, timezone, timedelta
from module_app.db import init_db, execute, utc_now
from module_app.production_ops import ensure_production_schema, exception_queue, review_exception, operations_summary
init_db(); ensure_production_schema(); now=utc_now()
execute("INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",('E001','Emp One','IT','Dev','','',now,'GRANTED',now,now))
base=datetime.now(timezone.utc)-timedelta(minutes=4)
for i in range(20):
    t=(base+timedelta(seconds=i*7)).isoformat(); d={'bbox':[100+i,100,160,180],'frame_width':1280,'frame_height':720,'reason':'no-match'}
    execute("INSERT INTO recognition_events(student_id,track_id,camera_source,direction,confidence,liveness_score,anti_spoof_passed,status,event_at,detail_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(None,f'A{i}','cam01','IN',0,0,0,'UNREGISTERED',t,json.dumps(d),t))
for i in range(7):
    t=(base+timedelta(seconds=i*9)).isoformat(); d={'bbox':[900+i,100,150,180],'frame_width':1280,'frame_height':720,'reason':'no-match'}
    execute("INSERT INTO recognition_events(student_id,track_id,camera_source,direction,confidence,liveness_score,anti_spoof_passed,status,event_at,detail_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(None,f'B{i}','cam01','IN',0,0,0,'UNREGISTERED',t,json.dumps(d),t))
cases=exception_queue(limit=80,decision='PENDING')
assert len(cases)==2, cases
assert sorted(c['observation_count'] for c in cases)==[7,20], cases
assert operations_summary()['pending_exceptions']==2
case=max(cases,key=lambda c:c['observation_count'])
r=review_exception(case['id'],'MARKED_UNKNOWN',None,'admin','visitor')
assert r['case_event_count']==20, r
left=exception_queue(limit=80,decision='PENDING')
assert len(left)==1 and left[0]['observation_count']==7, left
print('PASS')
'''
    proc = _run(script, tmp_path / "case_data")
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v29_hr_event_evidence(tmp_path: Path):
    script = r'''
from module_app.db import init_db, execute, utc_now, add_hr_event
from module_app.production_ops import ensure_production_schema, persist_hr_evidence, hr_event_evidence_path
init_db(); ensure_production_schema(); now=utc_now()
sid=execute("INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",('E001','Emp One','IT','Dev','','',now,'GRANTED',now,now))
ev=add_hr_event(sid,'track-1','PRESENCE_START',camera_source='cam01',detail={'session_id':1})
blob=b'\xff\xd8\xff\xe0CampusFaceV29\xff\xd9'
rel=persist_hr_evidence(ev['id'],blob)
path=hr_event_evidence_path(ev['id'])
assert rel.startswith('Snapshots/HR/'), rel
assert path and path.exists() and path.read_bytes()==blob, path
print('PASS')
'''
    proc = _run(script, tmp_path / "hr_data")
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout
