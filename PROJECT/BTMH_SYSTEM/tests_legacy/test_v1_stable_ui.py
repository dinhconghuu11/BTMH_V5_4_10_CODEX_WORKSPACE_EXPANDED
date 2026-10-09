from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
for token in ('Tổng quan','Sinh viên','Đăng ký FaceID','Nhận diện','Quản lý lớp học','Lịch sử'):
    assert token in html, token
assert html.count('id="page-classroom"')==1
assert 'data-page="classroom"' in html
for token in ('faceidScanner','scanTicks','faceidBiometricOverlay','scanPassPill','v23PassOne','v23PassTwo'):
    assert f'id="{token}"' in html, token
for token in ('buildScanTicks','scan_pass','pass_progress','pass_transition','drawEnrollBiometricOverlay'):
    assert token in js, token
for token in ('classroomVideo','classroomOverlay','classroomStudents','classroomSeated','classroomStanding','classroomRaised','classroomMoving','classroomTracks','classroomEventsBody'):
    assert f'id="{token}"' in html, token
for token in ('/api/v1/camera/stream_raw.mjpg','/api/v1/camera/frame_classroom.jpg','/api/v1/classroom/latest','/api/v1/classroom/events','drawClassroomOverlay'):
    assert token in js, token
assert 'Chưa đăng ký' in js and 'UNREGISTERED' in js
ids=re.findall(r'id="([^"]+)"',html)
assert len(ids)==len(set(ids)), 'duplicate DOM id found'
print('[OK] V1.3 stable UI contract: original shell + easy FaceID scan + visible classroom action live')
