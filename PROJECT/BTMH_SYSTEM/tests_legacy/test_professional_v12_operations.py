from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend/js/app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend/css/professional_v12_ops.css').read_text(encoding='utf-8')
main=(ROOT/'module_app/main.py').read_text(encoding='utf-8')
ops=(ROOT/'module_app/production_ops.py').read_text(encoding='utf-8')
walk=(ROOT/'module_app/walkby.py').read_text(encoding='utf-8')
cfg=(ROOT/'module_app/config.py').read_text(encoding='utf-8')
assert 'page-ops-center' in html and 'Trung tâm nghiệp vụ' in html
assert 'v12ExceptionList' in html and 'attendanceAdjustModal' in html
assert 'professional_v12_ops.css' in html
for route in ('/api/v1/operations/summary','/api/v1/operations/rules','/api/v1/cameras/devices','/api/v1/exceptions','/api/v1/events/{event_id}/evidence.jpg'):
    assert route in main
for token in ('camera_devices','exception_reviews','attendance_adjustments','attendance_record_events','persist_recognition_evidence','review_exception','adjust_attendance_record'):
    assert token in ops
assert 'persist_recognition_evidence' in walk
assert 'loadOpsCenter' in js and 'reviewOpsException' in js and 'openAttendanceAdjust' in js
assert '1.29.0-v1-face-pro-v12-operations' in cfg
assert 'V9 DYNAMIC UI' not in html
print('[OK] Professional V12 operations contract')
