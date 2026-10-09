from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def test_v291_decoder_shutdown_is_capture_thread_owned():
    camera = (CORE / "module_app" / "camera.py").read_text(encoding="utf-8")
    assert "CAPTURE_THREAD_ONLY" in camera
    assert "fctx->async_lock" in camera
    assert "Never force-release an FFmpeg decoder" in camera
    assert "CAP_PROP_READ_TIMEOUT_MSEC" in camera


def test_v291_local_preview_avoids_second_webrtc_codec_pipeline():
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    media = (CORE / "module_app" / "media_webrtc.py").read_text(encoding="utf-8")
    assert "127.0.0.1" in js and "startOfficeWsBitmapPreview();return" in js
    assert "preferred_local_transport" in media
    assert "video/vp8" in media.lower()


def test_v291_office_preview_and_action_are_bounded_without_lowering_source_camera():
    config = (CORE / "module_app" / "config.py").read_text(encoding="utf-8")
    classroom = (CORE / "module_app" / "classroom_engine.py").read_text(encoding="utf-8")
    migrate = (CORE / "scripts" / "apply_v291_realtime_hotfix.py").read_text(encoding="utf-8")
    assert "CLASSROOM_ACTION_FRAME_WIDTH" in config
    assert "action_frame = cv2.resize" in classroom
    assert 'MODULE_CLASSROOM_PREVIEW_FPS"] = "20"' in migrate
    assert 'MODULE_CLASSROOM_PREVIEW_WIDTH"] = "1280"' in migrate
    assert "Source camera remains 1920x1080/25" in migrate


def test_v291_camera_overlay_geometry_uses_one_contain_viewport():
    css = (CORE / "frontend" / "css" / "professional_v21_media_realtime.css").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert "V2.9.1 camera geometry hotfix" in css
    assert "aspect-ratio:16/9!important" in css
    assert "object-fit:contain!important" in css
    assert "officeContainGeometry(bitmap.width,bitmap.height" in js
    assert "officeOverlayLastDraw" in js
    assert "V2.9.1 entrance camera" in css
    assert "fit:'contain'" in js


def test_v291_preserves_v29_verification_evidence_contract():
    production = (CORE / "module_app" / "production_ops.py").read_text(encoding="utf-8")
    office = (CORE / "module_app" / "office_engine.py").read_text(encoding="utf-8")
    main = (CORE / "module_app" / "main.py").read_text(encoding="utf-8")
    assert "def _verification_cases" in production
    assert "def persist_hr_evidence" in production
    assert "persist_hr_evidence" in office
    assert "/api/v1/history/hr/{event_id}/evidence.jpg" in main
