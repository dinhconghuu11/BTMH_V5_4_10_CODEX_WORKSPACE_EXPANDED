from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def test_v28_media_transport_contract():
    camera = (CORE / "module_app" / "camera.py").read_text(encoding="utf-8")
    media = (CORE / "module_app" / "media_webrtc.py").read_text(encoding="utf-8")
    main = (CORE / "module_app" / "main.py").read_text(encoding="utf-8")
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    css = (CORE / "frontend" / "css" / "professional_v21_media_realtime.css").read_text(encoding="utf-8")

    assert "def latest_media_packet" in camera
    assert "RTCPeerConnection" in media
    assert "VideoFrame.from_ndarray" in media
    assert '"zero_backlog": True' in media
    assert '"native_frame": True' in media
    assert '"BROWSER_CANVAS"' in media
    assert 'video/h264' in media.lower()
    assert '/api/v1/media/capabilities' in main
    assert '/api/v1/media/webrtc/offer' in main
    assert '/api/v1/media/webrtc/close' in main
    assert '/api/v1/media/metadata/ws' in main
    assert 'id="officeWebrtcVideo"' in html
    assert 'id="officeOverlayCanvas"' in html
    assert "RTCPeerConnection" in js
    assert "getStats()" in js
    assert "/api/v1/media/metadata/ws" in js
    assert "requestAnimationFrame(drawOfficeOverlayFrame)" in js
    assert "startOfficeWsBitmapPreview" in js
    assert "startOfficeMjpegFallback" in js
    assert "officeOverlayCanvas" in css


def test_v28_optional_runtime_falls_back_without_aiortc(tmp_path: Path):
    script = r'''
from module_app.media_webrtc import MEDIA
caps = MEDIA.capabilities()
assert caps["ok"] is True
assert caps["metadata"]["overlay"] == "BROWSER_CANVAS"
assert caps["metadata"]["zero_backlog"] is True
assert caps["fallback"] == "WEBSOCKET_ACK_BITMAP"
print("WEBRTC_AVAILABLE", caps["webrtc"]["available"])
print("PASS")
'''
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(CORE),
        "CAMPUSFACE_DATA_ROOT": str(tmp_path / "data"),
        "CAMPUSFACE_DB_MODE": "sqlite",
        "MODULE_WEBRTC_ENABLED": "0",
    })
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v28_media_packet_is_latest_frame_and_does_not_request_jpeg(tmp_path: Path):
    script = r'''
import time
import numpy as np
from module_app.camera import CAMERA
frame = np.full((12, 20, 3), 123, dtype=np.uint8)
with CAMERA._lock:
    CAMERA._frame = frame
    CAMERA._frame_seq = 77
    CAMERA._frame_at = time.perf_counter()
    CAMERA._classroom_requested_at = 0.0
packet, seq, captured_at = CAMERA.latest_media_packet()
assert seq == 77
assert captured_at > 0
assert packet is not frame
assert packet.shape == frame.shape
packet[0,0,0] = 1
assert frame[0,0,0] == 123
assert CAMERA._classroom_requested_at == 0.0
print("PASS")
'''
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(CORE),
        "CAMPUSFACE_DATA_ROOT": str(tmp_path / "data"),
        "CAMPUSFACE_DB_MODE": "sqlite",
    })
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v28_install_and_start_contracts():
    req = (CORE / "requirements-media.txt").read_text(encoding="utf-8")
    install = (CORE / "INSTALL_CURRENT_PC_WINDOWS.bat").read_text(encoding="utf-8")
    start = (CORE / "START_CAMPUSFACE.bat").read_text(encoding="utf-8")
    portable = (CORE / "PREPARE_PORTABLE_OFFLINE_WINDOWS.bat").read_text(encoding="utf-8")
    checker = (CORE / "scripts" / "check_v28_media_runtime.py").read_text(encoding="utf-8")
    assert "aiortc" in req
    assert "requirements-media.txt" in install
    assert "check_v28_media_runtime.py" in install
    assert "check_v28_media_runtime.py" in start
    assert "?ui=v2.8" in start
    assert "requirements-media.txt" in portable
    assert 'for name in ("aiortc", "av")' in checker
    assert 'importlib.import_module(name)' in checker
