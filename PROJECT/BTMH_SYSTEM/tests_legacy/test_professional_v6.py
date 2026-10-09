from __future__ import annotations
import os, sys, tempfile
from pathlib import Path

_TMP=tempfile.TemporaryDirectory(prefix='cf-v6-test-')
os.environ.setdefault('CAMPUSFACE_DB_MODE','sqlite')
os.environ.setdefault('CAMPUSFACE_DATA_ROOT',_TMP.name)
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from module_app.config import APP_VERSION
from module_app.db import init_db, execute, utc_now
from module_app.production_ops import ensure_production_schema
from module_app.auth import create_user

assert APP_VERSION.startswith(('1.23.0-v1-face-pro-v6','1.24.0-v1-face-pro-v7','1.25.0-v1-face-pro-v8','1.26.0-v1-face-pro-v9','1.29.0-v1-face-pro-v12-operations'))
init_db(); ensure_production_schema()
now=utc_now()
sid=execute("INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,biometric_consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('V6001','Sinh Vien V6','8B1','CNTT','','',now,'GRANTED',now,now,now))
execute("INSERT INTO face_templates(student_id,embedding_blob,pose_count,created_at,updated_at) VALUES(?,?,?,?,?)",(sid,b'v6',8,now,now))
execute("INSERT INTO recognition_events(student_id,track_id,camera_source,direction,confidence,liveness_score,anti_spoof_passed,status,event_at,detail_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(sid,'1','static-camera','IN',.93,.98,1,'RECOGNIZED',now,'{}',now))

from module_app import main
students=main.students()
assert students and students[0]['face_pose_count']==8 and students[0]['recognition_count']==1
assert students[0]['last_seen_at']
profile=main.get_student(sid)
assert profile['enrolled']==1 and profile['last_confidence']>.9
timeline=main.student_timeline(sid,20)
assert timeline['items'] and timeline['items'][0]['kind']=='RECOGNITION'
summary=main.dashboard_summary()
assert summary['students']['total']==1 and summary['students']['faceid']==1
assert summary['today']['recognized_events']==1
viewer=create_user('viewer1','Nguoi xem','VIEWER','password123')
assert viewer['role']=='VIEWER'

# Static release contract: V6 must expose professional camera/system/student features.
main_src=(ROOT/'module_app/main.py').read_text(encoding='utf-8')
cam=(ROOT/'module_app/camera.py').read_text(encoding='utf-8')
html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend/js/app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend/css/professional_v6.css').read_text(encoding='utf-8')
for route in ['/api/v1/dashboard/summary','/api/v1/system/audit','/api/v1/camera/reconnect','/api/v1/students/{student_id}/timeline','/api/v1/exports/students.csv']:
    assert route in main_src, route
assert 'def restart(self)' in cam
assert 'data-page="system"' in html and 'id="page-system"' in html and 'CAMERA CENTER' in html
assert 'professional_v6.css' in html and '.v6-camera-center' in css
assert 'renderProfessionalSummary' in js and 'loadStudentTimeline' in js and 'reconnectCamera' in js
assert 'face_pose_count' in main_src and 'recognition_count' in main_src and 'last_seen_at' in main_src
print('[OK] Professional V6 system/camera/student runtime + UI contract')
