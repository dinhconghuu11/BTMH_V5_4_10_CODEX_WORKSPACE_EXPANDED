from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v5410_native_gateway_frontend_is_primary():
    media = (ROOT / "frontend" / "js" / "btmh_media_v5410.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "btmh_media_v5410.js?v=5.4.10" in html
    assert "btmh_media_v5410.css?v=5.4.10" in html
    assert "startNativeGateway" in media
    assert "application/sdp" in media
    assert "NATIVE_GATEWAY_WEBRTC" in media
    assert "const order = ['native', 'webrtc', 'ws', 'mjpeg', 'poll']" in media


def test_v5410_gateway_config_is_secret_free(tmp_path: Path):
    from module_app.media_gateway_v5410 import NativeMediaGateway

    gw = NativeMediaGateway()
    gw._runtime_dir = tmp_path / "runtime"
    gw._config_dir = tmp_path / "config"
    gw._config_path = gw._config_dir / "mediamtx.yml"
    gw._log_path = tmp_path / "logs" / "mediamtx.log"
    gw._source = "rtsp://admin:SuperSecret123@192.168.10.200:554/Streaming/Channels/101"
    gw._source_label = "Hikvision"
    gw._desired = True
    gw._write_config()
    text = gw._config_path.read_text(encoding="utf-8")
    assert "SuperSecret123" not in text
    assert "192.168.10.200" not in text
    assert "source: publisher" in text
    assert "sourceOnDemand: true" in text
    assert "webrtcAddress:" in text


def test_v5410_gateway_status_never_exposes_rtsp_secret():
    from module_app.media_gateway_v5410 import NativeMediaGateway

    gw = NativeMediaGateway()
    gw._source = "rtsp://admin:NeverExposeThis@192.168.10.200:554/Streaming/Channels/101"
    gw._source_label = "Hikvision"
    status = gw.status()
    serialized = repr(status)
    assert "NeverExposeThis" not in serialized
    assert "rtsp://" not in serialized
    assert status["source_kind"] == "rtsp"
    assert status["secret_on_disk"] is False
    assert status["ai_independent"] is True


def test_v5410_main_uses_gateway_and_permission_map(tmp_path: Path):
    script = r'''
from module_app.main import _api_permission_for, media_capabilities
assert _api_permission_for('/api/v1/media/gateway/status', 'GET') == 'camera.live'
assert _api_permission_for('/api/v1/media/gateway/restart', 'POST') == 'camera.configure'
caps = media_capabilities()
assert caps['policy'] == 'NATIVE_GATEWAY_FIRST'
assert caps['fallback_chain'][0] == 'MEDIAMTX_WHEP_WEBRTC'
assert 'native_gateway' in caps
assert 'whep_url' in caps['native_gateway']
print('PASS')
'''
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "CAMPUSFACE_DATA_ROOT": str(tmp_path / "data"),
            "CAMPUSFACE_DB_MODE": "sqlite",
            "MODULE_WEBRTC_ENABLED": "0",
            "BTMH_MEDIA_GATEWAY_ENABLED": "0",
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v5410_installer_pins_and_verifies_mediamtx():
    ps = (ROOT / "scripts" / "ensure_mediamtx_v5410.ps1").read_text(encoding="utf-8")
    assert 'Version = "1.21.1"' in ps
    assert "faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23" in ps
    assert "Get-FileHash -Algorithm SHA256" in ps
    assert "github.com/bluenviron/mediamtx/releases/download" in ps
    install = (ROOT / "INSTALL_CURRENT_PC_WINDOWS.bat").read_text(encoding="utf-8")
    assert "ensure_mediamtx_v5410.ps1" in install


def test_v5410_camera_handover_syncs_native_gateway():
    main = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
    assert "MEDIA_GATEWAY.start(resolved_source, resolved_label)" in main
    assert "MEDIA_GATEWAY.sync_source(source, label)" in main
    assert "MEDIA_GATEWAY.shutdown()" in main


def test_v5410_gateway_log_redacts_rtsp_credentials():
    from module_app.media_gateway_v5410 import NativeMediaGateway

    source = "rtsp://admin:SuperSecret123@192.168.10.200:554/Streaming/Channels/101"
    line = f"ERR source failed: {source}\n"
    safe = NativeMediaGateway._redact_gateway_log_line(line, source)
    assert "SuperSecret123" not in safe
    assert "admin:" not in safe
    assert "[RTSP_SOURCE_REDACTED]" in safe


def test_v5410_gateway_config_routes_logs_through_redaction(tmp_path: Path):
    from module_app.media_gateway_v5410 import NativeMediaGateway

    gw = NativeMediaGateway()
    gw._config_dir = tmp_path / "config"
    gw._config_path = gw._config_dir / "mediamtx.yml"
    gw._log_path = tmp_path / "logs" / "mediamtx.log"
    gw._write_config()
    text = gw._config_path.read_text(encoding="utf-8")
    assert "logDestinations: [stdout]" in text
    assert "logFile:" not in text
