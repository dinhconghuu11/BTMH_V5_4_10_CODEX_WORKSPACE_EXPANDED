from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_recognition_page_syncs_from_current_live_track():
    js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
    assert "recognitionProfileKey" in js
    assert "active?.recognized" in js
    assert "active.student||active.candidate_student" in js
    assert "renderLatestRecognition({" in js
    assert "},false);" in js
    assert "function renderLatestRecognition(ev,recordHistory=true)" in js
    assert "if(recordHistory){" in js


def test_enrollment_preview_is_sharpened_without_touching_ai_capture():
    cam = (ROOT / 'module_app' / 'camera.py').read_text(encoding='utf-8')
    assert "def _enhance_enrollment_preview" in cam
    assert "enroll_preview = self._enhance_enrollment_preview(frame)" in cam
    assert "enroll_quality = max(90, int(JPEG_QUALITY))" in cam
    publish = cam.split("def _publish_frame", 1)[1].split("def _capture_loop", 1)[0]
    assert "_enhance_enrollment_preview" not in publish


if __name__ == '__main__':
    tests = [
        test_recognition_page_syncs_from_current_live_track,
        test_enrollment_preview_is_sharpened_without_touching_ai_capture,
    ]
    for fn in tests:
        fn(); print('[PASS]', fn.__name__)
    print('[OK] V1 FACE PRO R3 recognition + enrollment-camera hotfix passed')
