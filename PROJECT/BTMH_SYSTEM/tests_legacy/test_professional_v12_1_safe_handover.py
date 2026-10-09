from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cam_text = (ROOT / 'module_app' / 'camera.py').read_text(encoding='utf-8')
db_text = (ROOT / 'module_app' / 'db.py').read_text(encoding='utf-8')
walk_text = (ROOT / 'module_app' / 'walkby.py').read_text(encoding='utf-8')
main_text = (ROOT / 'module_app' / 'main.py').read_text(encoding='utf-8')
html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')

for token in (
    'safe_select_source', '_wait_for_stable_source', 'recognition_paused',
    'ROLLBACK', 'stable_frames', '_clear_transient_recognition',
):
    assert token in cam_text, token
assert 'camera_source=self.event_camera_source()' in cam_text
assert 'cross_camera_dedup_seconds' in db_text
assert 'deduplicated' in db_text and 'previous_source != source' in db_text
assert 'camera_source=camera_source' in walk_text
assert 'CROSS_CAMERA_DEDUP' in walk_text
assert 'CAMERA_HANDOVER_STARTED' in main_text
assert 'CAMERA_HANDOVER_COMPLETED' in main_text
assert 'CAMERA_HANDOVER_FAILED' in main_text
assert 'safe_select_source' in main_text
assert 'SAFE CAMERA HANDOVER' in html
assert 'v121HandoverState' in html
assert 'setCameraHandoverUi' in js
assert 'FaceID đang tạm dừng' in js
print('[OK] Professional V12.1 safe camera handover contract')
