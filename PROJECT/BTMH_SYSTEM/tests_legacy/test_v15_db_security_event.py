from __future__ import annotations
import os, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

with tempfile.TemporaryDirectory(prefix='cf-v15-db-') as td:
    os.environ['CAMPUSFACE_DATA_ROOT']=td
    from module_app.db import init_db, execute, utc_now, add_event, add_spoof_event, fetchall
    init_db()
    now=utc_now()
    sid=execute('''INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,biometric_consent_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)''',('SV1','Student One','A','F','','',now,'GRANTED',now,now,now))
    add_event(sid,'t:1',.88,{'liveness':{'status':'PASS'}},liveness_score=.82,anti_spoof_passed=True)
    add_spoof_event('t:2',{'reason':'screen'},student_id=sid,confidence=.91,liveness_score=.09)
    rows=fetchall('SELECT status,anti_spoof_passed,liveness_score FROM recognition_events ORDER BY id')
    assert rows[0]['status']=='RECOGNIZED' and rows[0]['anti_spoof_passed']==1 and rows[0]['liveness_score']>.8, rows
    assert rows[1]['status']=='SPOOF_BLOCKED' and rows[1]['anti_spoof_passed']==0 and rows[1]['liveness_score']<.2, rows
print('[OK] DB stores verified vs blocked anti-spoof events distinctly')
