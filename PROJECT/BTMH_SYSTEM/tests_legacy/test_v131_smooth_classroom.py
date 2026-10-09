from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
main = (ROOT / 'module_app' / 'main.py').read_text(encoding='utf-8')
camera = (ROOT / 'module_app' / 'camera.py').read_text(encoding='utf-8')
config = (ROOT / 'module_app' / 'config.py').read_text(encoding='utf-8')

assert "if(page==='classroom'){loadStudents();prepareClassroomView();}" in js
assert 'Bật quan sát' in html and 'Tắt quan sát' in html
assert 'Camera lớp học đang tắt' in js
assert '/api/v1/camera/frame_classroom.jpg' in js  # HTTP fallback remains available
assert 'frame_classroom.jpg' in main
assert 'latest_classroom_jpeg' in camera
assert 'classroom_preview_fps' in camera
# V1.7 primary preview is ACK-paced WebSocket; HTTP latest-frame polling remains a fallback.
assert '/api/v1/classroom/preview/ws' in js and '@app.websocket("/api/v1/classroom/preview/ws")' in main
assert "ws.send('next')" in js and 'await websocket.receive_text()' in main
block=js[js.index('function classroomFramePoll()'):js.index('function startClassroomFramePolling()')]
assert 'createObjectURL' not in block
assert 'createImageBitmap' in js
assert 'setTimeout(classroomFramePoll,70)' in block
# Historical literals are retained as comments for diagnostics/backward-compatible docs.
assert 'MODULE_CLASSROOM_AI_FPS", "2"' in config
assert 'MODULE_CLASSROOM_FACE_AI_FPS", "4"' in config
assert 'MODULE_CLASSROOM_PREVIEW_FPS", "12"' in config
assert 'MODULE_CLASSROOM_PREVIEW_WIDTH", "800"' in config
assert 'MODULE_CLASSROOM_JPEG_QUALITY", "65"' in config
assert 'MODULE_CLASSROOM_FACE_AI_WIDTH", "960"' in config
assert 'CLASSROOM_FACE_AI_FPS if classroom_mode else AI_TARGET_FPS' in camera
assert 'work = self._resize_for_ai(frame, AI_WIDTH)' in camera
# V1.10.1 keeps recognition geometry stable across Classroom/UI mode changes.
assert 'CLASSROOM_FACE_AI_WIDTH if classroom_mode else AI_WIDTH' not in camera
assert 'CAMERA.set_classroom_mode(True)' in main
assert 'CAMERA.set_classroom_mode(False)' in main
print('[OK] V1.7 classroom on/off + ACK-paced newest-frame preview contract')
