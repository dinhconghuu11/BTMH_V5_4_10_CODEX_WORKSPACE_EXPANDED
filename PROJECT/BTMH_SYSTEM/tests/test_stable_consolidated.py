from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_stable_auth_assets_are_consolidated():
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    assert 'btmh_auth_stable.css?v=4.7.0' in html
    for old in ('btmh_auth_v41.css', 'btmh_auth_v46.css', 'btmh_auth_v461.css', 'btmh_auth_v462.css'):
        assert old not in html
    assert '#authGate.btmh-auth-v41.hidden' in (ROOT / 'frontend' / 'css' / 'btmh_auth_stable.css').read_text(encoding='utf-8')


def test_auth_forms_and_session_exit_contract():
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
    assert 'id="gateLoginForm"' in html
    assert 'id="gateRegisterForm"' in html
    assert "'/api/v1/auth/login'" in js
    assert "'/api/v1/auth/register'" in js
    assert 'verifyBrowserSession' in js
    assert 'setAuthGate(status)' in js
    assert "await bootAuthenticated()" in js


def test_no_duplicate_html_ids():
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    ids = re.findall(r'id="([^"]+)"', html)
    dup = sorted({x for x in ids if ids.count(x) > 1})
    assert not dup, dup


def test_hikvision_profile_has_no_plaintext_password():
    text = '\n'.join([
        (ROOT / 'config' / 'cameras.json').read_text(encoding='utf-8'),
        (ROOT / 'config' / 'hikvision_test_camera.json').read_text(encoding='utf-8'),
        (ROOT / 'scripts' / 'configure_hikvision.py').read_text(encoding='utf-8'),
    ])
    assert 'Windows DPAPI' in text
    assert 'password_storage' in text
    # The package must not contain a concrete RTSP password in these deployment configs.
    assert 'rtsp://admin:' not in (ROOT / 'config' / 'cameras.json').read_text(encoding='utf-8')
