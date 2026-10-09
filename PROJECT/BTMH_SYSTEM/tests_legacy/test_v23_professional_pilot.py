from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parents[1]


def test_v23_professional_pilot_ui_security_contract():
    html = (CORE / "frontend/index.html").read_text(encoding="utf-8")
    js = (CORE / "frontend/js/app.js").read_text(encoding="utf-8")
    main = (CORE / "module_app/main.py").read_text(encoding="utf-8")
    auth = (CORE / "module_app/auth.py").read_text(encoding="utf-8")
    assert 'id="authGate"' in html
    assert "Professional Pilot" in html
    assert "professional_v16_pilot.css?v=2.3.0" in html
    assert "setAuthGate" in js and "gateLogin" in js and "bootAuthenticated" in js
    assert "let detail=x.reason" in js
    assert 'AUTH_COOKIE = "campusface_session"' in main
    assert "X-Content-Type-Options" in main and "X-Frame-Options" in main
    assert "CAMERA_CONNECTION_TEST" in main
    assert "_LOGIN_MAX_FAILURES = 5" in auth and "_LOGIN_LOCK_SEC = 60" in auth


def test_v23_camera_handover_core_untouched():
    expected = {
        "camera.py": "086838fce8dbd3623e9cdd631c10a338444806f75a2043f2d1540ab7417799a6",
        "camera_profiles.py": "9ae23d1833bc8f9e25c84da4a6489398e7f92a7bbfa23e68dc05a287ef4bfefd",
    }
    for name, digest in expected.items():
        got = hashlib.sha256((CORE / "module_app" / name).read_bytes()).hexdigest()
        assert got == digest, (name, got)


def test_v23_auth_lockout_roundtrip(tmp_path: Path):
    data_root = tmp_path / "data-root"
    code = """
from module_app.db import init_db
from module_app.auth import bootstrap_admin, login, login_lock_status
from module_app.production_ops import ensure_production_schema
init_db(); ensure_production_schema()
bootstrap_admin('admin','Admin','12345678')
for _ in range(5):
    try:
        login('admin','wrong-password')
    except ValueError:
        pass
st = login_lock_status('admin')
assert st['locked'] is True and st['retry_after'] > 0, st
try:
    login('admin','12345678')
    raise AssertionError('login should be locked')
except ValueError as e:
    assert 'tạm khóa' in str(e)
print('PASS')
"""
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(CORE),
        "CAMPUSFACE_DB_MODE": "sqlite",
        "CAMPUSFACE_DATA_ROOT": str(data_root),
    })
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v23_packaging_has_operations_tools():
    assert (ROOT / "tools/install/ENABLE_AUTO_START_WINDOWS.bat").exists()
    assert (ROOT / "tools/install/DISABLE_AUTO_START_WINDOWS.bat").exists()
    assert (ROOT / "tools/operations/START_CAMPUSFACE_24X7.bat").exists()
    assert (ROOT / "tools/operations/watchdog.ps1").exists()
