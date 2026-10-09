from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_contract():
    html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
    js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
    css=(ROOT/'frontend'/'css'/'production_ready_v110.css').read_text(encoding='utf-8')
    assert 'Phiên điểm danh' in html
    assert 'data-page="platform"' not in html and 'id="page-platform"' not in html
    assert 'Passive anti-spoof' in js
    for token in ('/api/v1/attendance/sessions','/api/v1/backups','/api/v1/settings/camera','campusface_token'):
        assert token in js, token
    assert '#page-operations' in css


def test_backend_contract():
    main=(ROOT/'module_app'/'main.py').read_text(encoding='utf-8')
    ops=(ROOT/'module_app'/'production_ops.py').read_text(encoding='utf-8')
    auth=(ROOT/'module_app'/'auth.py').read_text(encoding='utf-8')
    walk=(ROOT/'module_app'/'walkby.py').read_text(encoding='utf-8')
    cfg=(ROOT/'module_app'/'config.py').read_text(encoding='utf-8')
    assert '1.12.0-postgresql-offline-production-ready' in cfg
    for token in ('/api/v1/attendance/sessions','/api/v1/system/diagnostics','/api/v1/system/self-test','/api/v1/backups','/api/v1/settings/camera','/api/v1/auth/bootstrap'):
        assert token in main, token
    assert 'attendance_sessions' in ops and 'attendance_records' in ops
    assert 'apply_successful_checkin' in walk and 'apply_rejected_checkin' in walk
    assert 'pbkdf2_hmac' in auth and 'ADMIN' in auth and 'OPERATOR' in auth


def test_attendance_backup_auth_smoke_in_clean_process():
    code=r'''
import os,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
root=Path(os.environ['CF_ROOT'])
sys.path.insert(0,str(root))
from module_app.db import init_db,execute,utc_now
from module_app.production_ops import ensure_production_schema,create_session,apply_successful_checkin,apply_rejected_checkin,session_ledger,create_backup,validate_backup
from module_app.auth import bootstrap_admin,login,create_user,list_users
init_db();ensure_production_schema()
now=utc_now()
sid=execute("INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,biometric_consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('SV001','Nguyen Van A','21-05','CNTT','','',now,'GRANTED',now,now,now))
t=datetime.now(timezone.utc)
s=create_session('Ca sang','21-05','A203',(t-timedelta(minutes=1)).isoformat(),(t+timedelta(hours=1)).isoformat(),5,'admin')
ev=execute("INSERT INTO recognition_events(student_id,track_id,camera_source,direction,confidence,liveness_score,anti_spoof_passed,status,event_at,detail_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(sid,'t1','static-camera','IN',0.9,0.9,1,'RECOGNIZED',utc_now(),'{}',utc_now()))
apply_successful_checkin(ev,sid,utc_now())
apply_rejected_checkin(sid,utc_now())
rows=session_ledger(s['id'])
assert len(rows)==1 and rows[0]['final_status']=='PRESENT' and rows[0]['rejected_attempts']==1,rows
admin=bootstrap_admin('admin','Admin','Password123!')
a=login('admin','Password123!'); assert a['user']['role']=='ADMIN'
create_user('operator','Nhan vien','OPERATOR','Operator123!')
assert len(list_users())==2
b=create_backup('test'); assert Path(b['path']).exists(); validate_backup(Path(b['path']))
print('OK')
'''
    with tempfile.TemporaryDirectory() as td:
        env=os.environ.copy();env['CAMPUSFACE_DATA_ROOT']=td;env['CF_ROOT']=str(ROOT)
        p=subprocess.run([sys.executable,'-c','import sys;'+code],env=env,cwd=ROOT,capture_output=True,text=True)
        assert p.returncode==0,(p.stdout,p.stderr)
        assert 'OK' in p.stdout


if __name__=='__main__':
    tests=[test_frontend_contract,test_backend_contract,test_attendance_backup_auth_smoke_in_clean_process]
    for fn in tests:
        fn();print('[PASS]',fn.__name__)
    print('[OK] V1.10 Production Ready contract')
