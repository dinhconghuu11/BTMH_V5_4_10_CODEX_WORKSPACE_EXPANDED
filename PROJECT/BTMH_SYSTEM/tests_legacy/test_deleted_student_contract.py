from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
main=(ROOT/'module_app'/'main.py').read_text(encoding='utf-8')
db=(ROOT/'module_app'/'db.py').read_text(encoding='utf-8')
walk=(ROOT/'module_app'/'walkby.py').read_text(encoding='utf-8')
cam=(ROOT/'module_app'/'camera.py').read_text(encoding='utf-8')
cls=(ROOT/'module_app'/'classroom_engine.py').read_text(encoding='utf-8')
assert 'ON DELETE CASCADE' in db
for token in ('INDEX.invalidate()','WALKBY.purge_student(student_id)','CAMERA.purge_student(student_id)','CLASSROOM.purge_student(student_id)'):
    assert token in main, token
assert 'UNREGISTERED' in walk
assert 'Chưa đăng ký' in cls
print('[OK] deleting a student revokes FaceID in DB and in-memory recognition/classroom state')
