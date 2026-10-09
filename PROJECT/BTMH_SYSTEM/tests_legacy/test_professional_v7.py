from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path

_TMP=tempfile.TemporaryDirectory(prefix='cf-v7-test-')
os.environ.setdefault('CAMPUSFACE_DB_MODE','sqlite')
os.environ.setdefault('CAMPUSFACE_DATA_ROOT',_TMP.name)
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from module_app.config import APP_VERSION
from module_app.db import init_db, execute, utc_now
from module_app.production_ops import (
    ensure_production_schema, classroom_review_queue, review_classroom_event,
    classroom_review_counts, classroom_report_csv,
)

assert APP_VERSION.startswith(('1.24.0-v1-face-pro-v7','1.25.0-v1-face-pro-v8','1.26.0-v1-face-pro-v9','1.29.0-v1-face-pro-v12-operations'))
init_db(); ensure_production_schema(); now=utc_now()
sid=execute("INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,biometric_consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('V7001','Sinh Vien V7','8B1','CNTT','','',now,'GRANTED',now,now,now))
detail={'using_phone':True,'phone_confidence':0.88,'pose_quality':0.72,'snapshot_path':'Snapshots/Classroom/classroom_1.jpg'}
eid=execute("INSERT INTO classroom_events(student_id,track_id,action,confidence,event_at,detail_json,created_at) VALUES(?,?,?,?,?,?,?)",(sid,'face:1','Sử dụng điện thoại',0.94,now,json.dumps(detail,ensure_ascii=False),now))
q=classroom_review_queue(limit=10,status='PENDING',class_name='8B1',attention_only=True)
assert len(q)==1 and q[0]['id']==eid
assert q[0]['attention_kind']=='PHONE' and q[0]['severity']=='HIGH'
assert q[0]['display_label']=='Nghi sử dụng điện thoại'
assert abs(q[0]['observation_confidence']-0.88)<1e-6
assert classroom_review_counts('8B1')['pending']==1
r=review_classroom_event(eid,'CONFIRMED','teacher01','Đã xem lại ảnh')
assert r['review_status']=='CONFIRMED' and r['reviewed_by']=='teacher01'
assert classroom_review_counts('8B1')['pending']==0
csv_data=classroom_report_csv('8B1',100).decode('utf-8-sig')
assert 'Báo cáo quan sát lớp học có xác nhận của giáo viên' in csv_data
assert 'Nghi sử dụng điện thoại' in csv_data and 'CONFIRMED' in csv_data

from module_app import main
main_src=(ROOT/'module_app/main.py').read_text(encoding='utf-8')
engine=(ROOT/'module_app/classroom_engine.py').read_text(encoding='utf-8')
html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend/js/app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend/css/professional_v7.css').read_text(encoding='utf-8')
for route in ['/api/v1/classroom/classes','/api/v1/classroom/pro-summary','/api/v1/classroom/review','/api/v1/classroom/evidence/{event_id}.jpg','/api/v1/classroom/report.csv']:
    assert route in main_src, route
assert '_save_event_evidence' in engine and 'snapshot_path' in engine
assert 'PRO CLASSROOM V7' in html and 'classroomReviewBody' in html and 'professional_v7.css' in html
assert 'renderClassroomReviewQueue' in js and 'reviewClassroomObservation' in js and 'downloadClassroomReport' in js
assert '.v7-classroom-kpis' in css and '.v7-review-table' in css
print('[OK] Professional V7 classroom review/evidence/report contract')
