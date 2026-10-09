from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
main=(ROOT/'module_app'/'main.py').read_text(encoding='utf-8')
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend'/'css'/'v1_2_faceid_student_activity.css').read_text(encoding='utf-8')
for token in ('/api/v1/students/{student_id}/activity-live','CLASSROOM.latest()','classroom_events'):
    assert token in main, token
for token in ('studentActivityShell','startStudentActivityView','pollStudentActivity','drawStudentActivityOverlay','/api/v1/camera/stream_raw.mjpg','/api/v1/classroom/start'):
    assert token in js, token
for token in ('.student-live-activity','.student-live-camera-wrap','.student-current-action-card'):
    assert token in css, token
print('[OK] student profile activity tab is wired to the shared static camera + local action AI')
