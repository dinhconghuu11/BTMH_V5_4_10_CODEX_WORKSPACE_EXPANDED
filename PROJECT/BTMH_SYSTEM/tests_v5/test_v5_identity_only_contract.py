from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
MOD = CORE / "module_app"
FRONT = CORE / "frontend"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_action_and_classroom_engines_are_not_shipped():
    assert not (MOD / "action_engine.py").exists()
    assert not (MOD / "classroom_engine.py").exists()
    runtime = "\n".join(_text(p) for p in MOD.glob("*.py"))
    assert "from .action_engine" not in runtime
    assert "from .classroom_engine" not in runtime


def test_backend_has_no_classroom_action_api_surface():
    main = _text(MOD / "main.py")
    assert "/api/v1/classroom/" not in main
    assert "ClassroomReviewPayload" not in main
    assert "latest_classroom_jpeg" not in main
    assert "latest_observation_jpeg" in main


def test_frontend_has_no_hidden_action_ai_pages_or_calls():
    html = _text(FRONT / "index.html")
    js = _text(FRONT / "js" / "app.js")
    for forbidden in (
        'id="page-classroom"', 'id="page-office"', "Action AI", "Giơ tay",
        "Nghi điện thoại", "Cúi đầu",
    ):
        assert forbidden not in html
    assert "/api/v1/classroom/" not in js
    assert "studentActivity" not in js
    assert "prepareClassroomView" not in js
    assert "startOfficeView" not in js
    assert "Action AI" not in js


def test_identity_observer_keeps_tracking_without_behavior_inference():
    office = _text(MOD / "office_engine.py")
    assert "CAMERA.latest_result()" in office
    assert "from .classroom_engine" not in office
    assert '"IDENTITY_TRACK"' in office
    assert '"PRESENT"' in office


def test_action_tuning_constants_are_removed():
    cfg = _text(MOD / "config.py")
    for forbidden in (
        "CLASSROOM_ACTION_HAND_CONFIRM_SEC", "CLASSROOM_ACTION_PHONE_CONFIRM_SEC",
        "CLASSROOM_ACTION_HEAD_DOWN_CONFIRM_SEC", "CLASSROOM_POSE_BUDGET",
        "CLASSROOM_ACTIVITY_ON", "CLASSROOM_AI_FPS",
    ):
        assert forbidden not in cfg
    assert "OBSERVATION_FACE_AI_FPS" in cfg
    assert "OBSERVATION_PREVIEW_FPS" in cfg


def test_camera_runtime_has_no_classroom_compat_accessors():
    camera = (MOD / "camera.py").read_text(encoding="utf-8")
    assert "latest_classroom_jpeg" not in camera
    assert "latest_classroom_packet" not in camera
    assert "set_classroom_mode" not in camera
    assert "_classroom_" not in camera
    assert "latest_observation_jpeg" in camera
    assert "latest_observation_packet" in camera
