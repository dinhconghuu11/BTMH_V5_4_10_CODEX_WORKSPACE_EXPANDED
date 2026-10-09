from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def all_text():
    """Read production-relevant source only, excluding tests, reports and logs."""
    chunks = []
    excluded_parts = {
        "tests", "tests_v5", "tests_v54", "docs", "logs", "backups",
        "__pycache__", ".pytest_cache",
    }
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".py", ".js", ".html", ".css", ".txt", ".bat", ".json", ".env"}:
            continue
        if any(part in excluded_parts for part in p.parts):
            continue
        if p.name.startswith("VERIFY_RELEASE"):
            continue
        chunks.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)

def test_no_fixed_customer_credentials():
    text = all_text()
    assert ("cong" + "huu24") not in text
    assert ("Dinh" + "conghuu" + "@05") not in text
    assert not re.search(r'_RELEASE_OWNER_PASSWORD_HASH\s*=\s*[\"\']\$argon2', text)

def test_security_hardening_installed():
    assert "install_v54_hardening(app)" in all_text()

def test_rtsp_redaction_utility_present():
    text = (ROOT / "module_app" / "security_hardening_v54.py").read_text(encoding="utf-8")
    assert "redact_uri" in text
    assert "***:***@" in text

def test_mcp_is_disabled_by_default():
    text = (ROOT / ".env.customer.example").read_text(encoding="utf-8")
    assert "MCP_ENABLED=false" in text
    assert "MCP_MODE=read_only" in text

def test_auth_brand_assets_present():
    assert list(ROOT.rglob("btmh_auth_v54.css"))
    assert list(ROOT.rglob("btmh_auth_v54.js"))

def test_csv_export_request_fix():
    text = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
    assert "rows = students(request)" in text

def test_production_local_default():
    launchers = list(ROOT.rglob("START_CAMPUSFACE.bat"))
    assert launchers
    text = launchers[0].read_text(encoding="utf-8", errors="ignore")
    assert "MODULE_HOST=127.0.0.1" in text

def test_redact_uri_masks_rtsp_credentials():
    from module_app.security_hardening_v54 import redact_uri
    value = redact_uri("rtsp://admin:secret@192.168.1.200:554/Streaming/Channels/101")
    assert "admin" not in value
    assert "secret" not in value
    assert "***:***@192.168.1.200" in value


def test_all_declared_sensitive_routes_have_server_permission_check():
    from module_app.main import _api_permission_for

    paths = [
        ("GET", "/api/v1/students/{student_id}/photo"),
        ("GET", "/api/v1/events"),
        ("GET", "/api/v1/history/feed"),
        ("GET", "/api/v1/history/recognition"),
        ("GET", "/api/v1/history/hr"),
        ("GET", "/api/v1/history/technical"),
        ("GET", "/api/v1/camera/status"),
        ("GET", "/api/v1/camera/frame.jpg"),
        ("GET", "/api/v1/camera/frame_raw.jpg"),
        ("GET", "/api/v1/camera/stream.mjpg"),
        ("GET", "/api/v1/camera/stream_raw.mjpg"),
        ("GET", "/api/v1/events/{event_id}/evidence.jpg"),
        ("GET", "/api/v1/operations/summary"),
        ("GET", "/api/v1/operations/rules"),
        ("GET", "/api/v1/system/diagnostics"),
        ("POST", "/api/v1/system/self-test"),
    ]
    for method, path in paths:
        assert _api_permission_for(path, method) is not None, path


def test_first_run_owner_fallback_is_explicitly_guarded():
    auth = (ROOT / "module_app" / "auth.py").read_text(encoding="utf-8")
    assert 'BTMH_ALLOW_FIRST_RUN_OWNER' in auth
    assert '_RELEASE_OWNER_USERNAME = ""' in auth
    assert '_RELEASE_OWNER_PASSWORD_HASH = ""' in auth
    assert (ROOT / "CREATE_OWNER_FIRST_RUN.py").exists()
    assert (ROOT / "CREATE_OWNER_FIRST_RUN.bat").exists()
