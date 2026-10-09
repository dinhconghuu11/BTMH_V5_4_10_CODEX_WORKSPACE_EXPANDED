from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v4_assets_and_pages_present():
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    js = (ROOT / 'frontend' / 'js' / 'btmh_v4.js').read_text(encoding='utf-8')
    css = (ROOT / 'frontend' / 'css' / 'btmh_v4.css').read_text(encoding='utf-8')
    assert 'page-live-grid' in html
    assert 'page-playback' in html
    assert 'Camera đăng ký' in html and 'Camera giám sát' in html
    assert 'Multi-camera' in html
    assert 'startEnrollmentBrowserCamera' in js
    assert '--btmc-red' in css and '--btmc-gold' in css


def test_enrollment_does_not_handover_surveillance_camera():
    js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
    block = js.split('async function prepareEnrollmentLaptopCamera(){',1)[1].split('\n}',1)[0]
    assert 'persistCameraPreset' not in block
    assert 'startEnrollmentBrowserCamera' in block
    assert "enrollmentDataUrl" in js


def test_second_pass_center_antistall_exists():
    code = (ROOT / 'module_app' / 'registry.py').read_text(encoding='utf-8')
    assert 'center_confirmation_needed' in code
    assert 'Permit one additional center sample' in code


def test_v4_camera_and_recording_runtime_exist():
    fleet = (ROOT / 'module_app' / 'camera_fleet_v4.py').read_text(encoding='utf-8')
    rec = (ROOT / 'module_app' / 'recording_runtime_v4.py').read_text(encoding='utf-8')
    main = (ROOT / 'module_app' / 'main.py').read_text(encoding='utf-8')
    assert 'CameraFleetV4' in fleet
    assert 'LocalRecorderSupervisorV4' in rec
    assert '/api/v1/cameras/fleet/v4' in main
    assert '/api/v1/recordings/media' in main


def test_v4_direct_login_and_register_phone_contract():
    main = (ROOT / 'module_app' / 'main.py').read_text(encoding='utf-8')
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    assert '/api/v1/auth/login' in main
    assert '/api/v1/auth/register' in main
    assert 'gateLoginUsername' in html and 'gateLoginPassword' in html
    assert 'gateRegisterUsername' in html and 'gateRegisterPhone' in html
    assert 'gateLoginDestination' not in html
    assert 'gateLoginOtp' not in html
