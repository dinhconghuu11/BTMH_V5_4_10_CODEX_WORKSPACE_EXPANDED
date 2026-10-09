from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CAMPUSFACE_DB_MODE", "sqlite")

from module_app.camera_profiles import load_hikvision_profile, redact_camera_source

profile = load_hikvision_profile()
assert profile is not None, "Missing Hikvision profile"
assert profile.url.startswith("rtsp://")
assert "@192.168.1.200:554/Streaming/Channels/101" in profile.url
assert "%40" in profile.url, "Reserved RTSP credential character must be percent-encoded"
assert redact_camera_source(profile.url).startswith("rtsp://***:***@")

js = (ROOT / "frontend/js/app.js").read_text(encoding="utf-8")
main = (ROOT / "module_app/main.py").read_text(encoding="utf-8")
cam = (ROOT / "module_app/camera.py").read_text(encoding="utf-8")
ops = (ROOT / "module_app/production_ops.py").read_text(encoding="utf-8")

assert "ptz: { label: 'Hikvision Camera', source: 'hikvision' }" in js
assert "ptz: { label: 'Camera PTZ', source: '1' }" not in js
assert "_resolve_camera_selection" in main
assert "CAMERA.configure_source" in main
assert "source_display" in main
assert "load_hikvision_profile" in ops
assert "UPDATE camera_devices SET name=?,source=?,camera_type='RTSP'" in ops
assert "OPENCV_FFMPEG_CAPTURE_OPTIONS" in cam
assert "CAP_PROP_OPEN_TIMEOUT_MSEC" in cam
assert "self._frame = frame" in cam
assert "def _ai_loop" in cam
print("[OK] FaceV1.1 dual camera Hikvision contract")
