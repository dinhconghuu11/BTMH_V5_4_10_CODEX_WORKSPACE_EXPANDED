"""Exercise startup policy and offline discovery without running candidate code."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from module_app import mediamtx_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.delenv("BTMH_MEDIAMTX_BIN", raising=False)
    monkeypatch.delenv("BTMH_MEDIAMTX_BINARY", raising=False)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None)
    monkeypatch.setattr(runtime, "PROJECT_ROOT", tmp_path / "project")
    runtime._archive_executable_hash.cache_clear()
    runtime._executable_hash.cache_clear()
    yield tmp_path
    runtime._archive_executable_hash.cache_clear()
    runtime._executable_hash.cache_clear()


def verified_bundle(path, monkeypatch):
    path.mkdir(parents=True, exist_ok=True)
    binary = path / "mediamtx.exe"
    # This is inert data; fixture pin changes exist only in this process.
    binary.write_bytes(b"verified fixture executable, never executed")
    archive = path / runtime.ARCHIVE_NAME
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr(zipfile.ZipInfo("mediamtx.exe", date_time=(2020, 1, 1, 0, 0, 0)), binary.read_bytes())
    monkeypatch.setattr(runtime, "ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    (path / "VERSION.txt").write_text(runtime.VERSION, encoding="ascii")
    return binary


@pytest.mark.parametrize("environment,allowed", [
    ("development", True), ("production", False), ("", False), ("dev", False),
])
def test_only_explicit_development_allows_missing(monkeypatch, isolated, environment, allowed):
    monkeypatch.setenv("BTMH_ENV", environment)
    if allowed:
        status = runtime.require_mediamtx(isolated)
        assert status.binary is None and status.reason == "MEDIAMTX_NOT_INSTALLED"
    else:
        with pytest.raises(RuntimeError, match="^MEDIAMTX_NOT_INSTALLED$"):
            runtime.require_mediamtx(isolated)


def test_data_root_precedes_env_vendor_and_path(monkeypatch, isolated):
    monkeypatch.setenv("BTMH_ENV", "development")
    binary = verified_bundle(isolated / "runtime" / "mediamtx", monkeypatch)
    vendor = verified_bundle(runtime.PROJECT_ROOT / "tools" / "mediamtx", monkeypatch)
    external = verified_bundle(isolated / "external", monkeypatch)
    monkeypatch.setenv("BTMH_MEDIAMTX_BIN", str(external))
    monkeypatch.setattr(runtime.shutil, "which", lambda name: str(vendor))
    assert runtime.resolve_mediamtx(isolated).binary == binary
    binary.unlink()
    assert runtime.resolve_mediamtx(isolated).binary == external
    external.unlink()
    assert runtime.resolve_mediamtx(isolated).binary == vendor
    monkeypatch.setenv("BTMH_ENV", "production")
    assert runtime.resolve_mediamtx(isolated).binary == vendor  # PATH is supported too.


def test_path_used_when_development_vendor_missing(monkeypatch, isolated):
    monkeypatch.setenv("BTMH_ENV", "development")
    binary = verified_bundle(isolated / "system", monkeypatch)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: str(binary))
    assert runtime.resolve_mediamtx(isolated).binary == binary


def test_legacy_override_and_cached_verified_download(monkeypatch, isolated):
    binary = verified_bundle(isolated / "external", monkeypatch)
    downloads = isolated / "downloads"
    downloads.mkdir()
    (binary.parent / runtime.ARCHIVE_NAME).rename(downloads / runtime.ARCHIVE_NAME)
    monkeypatch.setenv("BTMH_MEDIAMTX_BINARY", str(binary))
    assert runtime.resolve_mediamtx(isolated).binary == binary


def test_unsupported_candidate_skipped_without_execution(monkeypatch, isolated):
    invalid = isolated / "runtime" / "mediamtx" / "mediamtx.exe"
    invalid.parent.mkdir(parents=True)
    invalid.write_bytes(b"unverified executable")
    binary = verified_bundle(isolated / "external", monkeypatch)
    monkeypatch.setenv("BTMH_MEDIAMTX_BIN", str(binary))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("discovery executed code"))
    assert runtime.resolve_mediamtx(isolated).binary == binary
    binary.write_bytes(b"tampered")
    assert runtime.resolve_mediamtx(isolated).reason == "MEDIAMTX_UNSUPPORTED_BINARY"


def test_version_marker_and_archive_hash_are_enforced(monkeypatch, isolated):
    binary = verified_bundle(isolated / "runtime" / "mediamtx", monkeypatch)
    (binary.parent / "VERSION.txt").write_text("0.0.0", encoding="ascii")
    assert runtime.resolve_mediamtx(isolated).reason == "MEDIAMTX_UNSUPPORTED_BINARY"
    (binary.parent / "VERSION.txt").write_text(runtime.VERSION, encoding="ascii")
    monkeypatch.setattr(runtime, "ARCHIVE_SHA256", "0" * 64)
    runtime._archive_executable_hash.cache_clear()
    assert runtime.resolve_mediamtx(isolated).binary is None


def test_startup_rehashes_even_when_file_metadata_is_restored(monkeypatch, isolated):
    binary = verified_bundle(isolated / "runtime" / "mediamtx", monkeypatch)
    monkeypatch.setenv("BTMH_ENV", "production")
    real_signature = runtime._signature
    old_signature = real_signature(binary)
    # Reproduce Windows equal-size/mtime/creation-time spoofing portably.
    monkeypatch.setattr(runtime, "_signature", lambda path:
                        old_signature if path == binary else real_signature(path))
    assert runtime.resolve_mediamtx(isolated).binary == binary
    binary.write_bytes(b"X" * binary.stat().st_size)
    with pytest.raises(RuntimeError, match="^MEDIAMTX_UNSUPPORTED_BINARY$"):
        runtime.require_mediamtx(isolated)


def test_missing_gateway_status_and_spawn_do_not_leak_credentials(monkeypatch, isolated):
    from module_app import media_gateway_v5410 as gateway
    monkeypatch.setenv("BTMH_ENV", "development")
    gw = gateway.NativeMediaGateway()
    gw._runtime_dir = isolated / "runtime" / "mediamtx"
    gw._source = "rtsp://fixture:FakeMissingGatewaySecret@camera.invalid/101"
    gw._source_label = gw._source
    gw._desired = True
    monkeypatch.setattr(gateway.subprocess, "Popen", lambda *a, **kw: pytest.fail("missing binary executed"))
    assert gw._spawn_locked() is False
    status = gw.status()
    assert status["available"] is False
    assert status["native_webrtc"] is False
    assert status["state"] == "UNAVAILABLE"
    assert status["reason"] == "MEDIAMTX_NOT_INSTALLED"
    assert status["transport"] == "NONE"
    assert "FakeMissingGatewaySecret" not in json.dumps(status)
    assert gw._internal_password not in json.dumps(status)


def test_supported_gateway_spawns_native_with_secret_free_argv(monkeypatch, isolated):
    from module_app import media_gateway_v5410 as gateway
    binary = verified_bundle(isolated / "runtime" / "mediamtx", monkeypatch)
    gw = gateway.NativeMediaGateway()
    gw._runtime_dir = binary.parent
    gw._config_dir = isolated / "config"
    gw._config_path = gw._config_dir / "gateway.yml"
    gw._log_path = isolated / "logs" / "gateway.log"
    gw._source = "rtsp://fixture:FakePresentGatewaySecret@camera.invalid/101"
    gw._desired = True
    calls = []
    monkeypatch.setattr(gw, "_port_open", lambda *a, **kw: bool(calls))
    monkeypatch.setattr(gw, "_refresh_diagnostics_locked", lambda: None)
    monkeypatch.setattr(gw, "_start_log_pump", lambda *a: None)
    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(poll=lambda: None, pid=123)
    monkeypatch.setattr(gateway.subprocess, "Popen", spawn)
    assert gw._spawn_locked() is True
    assert calls[0][0][0] == str(binary)
    status = gw.status()
    assert status["available"] and status["native_webrtc"]
    assert status["transport"] == "NATIVE_GATEWAY_WEBRTC"
    assert status["reason"] == ""
    assert "FakePresentGatewaySecret" not in repr(calls[0][0])
    assert "FakePresentGatewaySecret" not in gw._config_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("mode,success", [("development", True), ("production", False)])
def test_actual_app_startup_and_gateway_api_missing(tmp_path, mode, success):
    # Invoke the real FastAPI startup function with worker collaborators replaced
    # so this test never opens cameras or changes a customer database.
    script = r'''
import json
from types import SimpleNamespace
from module_app import main as app
from module_app import mediamtx_runtime as runtime
runtime.shutil.which = lambda _: None
runtime.PROJECT_ROOT = app.DATA_ROOT / 'empty-project'
for name in ('init_db', 'close_all_open_presence_sessions', 'ensure_production_schema',
             'enforce_admin_only', 'provision_release_owner_account', 'ensure_otp_schema',
             'ensure_platform_v5_schema', 'ensure_sync_v5_schema', 'ensure_visitor_schema',
             'ensure_recording_schema', '_configure_ai_registry_source'):
    setattr(app, name, lambda *a, **kw: None)
app.list_camera_devices = lambda: []
app.camera_settings = lambda: {'source': '0'}
app._resolve_camera_selection = lambda value: ('0', 'Fixture')
app._auth_permission = lambda *a: {'id': 1}
app.add_audit_event = lambda *a, **kw: None
app.EDGE_SYNC_WORKER = app.RECORDER_V4 = app.OFFICE = app.PILOT = SimpleNamespace(start=lambda: None)
app.INDEX = SimpleNamespace(load=lambda **kw: None)
app.CAMERA = SimpleNamespace(configure_source=lambda *a: None, start=lambda: None,
                             event_camera_source=lambda: 'Fixture')
app.MEDIA_GATEWAY._ensure_watchdog_locked = lambda: None
try:
    app.startup()
except RuntimeError as exc:
    print('START_BLOCKED:' + str(exc))
else:
    status = app.media_gateway_status(None)
    assert status['available'] is False
    assert status['reason'] == 'MEDIAMTX_NOT_INSTALLED'
    assert status['native_webrtc'] is False
    print('START_OK:' + json.dumps(status))
'''
    env = os.environ.copy()
    env.update(BTMH_ENV=mode, CAMPUSFACE_DATA_ROOT=str(tmp_path / "data"),
               CAMPUSFACE_DB_MODE="sqlite", PYTHONUTF8="1")
    env.pop("BTMH_MEDIAMTX_BIN", None)
    env.pop("BTMH_MEDIAMTX_BINARY", None)
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert ("START_OK:" if success else "START_BLOCKED:MEDIAMTX_NOT_INSTALLED") in proc.stdout
