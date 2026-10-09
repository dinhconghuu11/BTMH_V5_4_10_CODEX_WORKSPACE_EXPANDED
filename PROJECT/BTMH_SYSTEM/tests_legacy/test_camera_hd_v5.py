from __future__ import annotations
from pathlib import Path
import os, sys, tempfile, subprocess
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.camera import StaticCameraService
from module_app.config import APP_VERSION, CLASSROOM_PREVIEW_WIDTH, CLASSROOM_JPEG_QUALITY, CLASSROOM_PREVIEW_ENHANCE

assert APP_VERSION.startswith(("1.22.2-v1-face-pro-camera-hd-v5","1.23.0-v1-face-pro-v6","1.24.0-v1-face-pro-v7","1.25.0-v1-face-pro-v8","1.26.0-v1-face-pro-v9","1.29.0-v1-face-pro-v12-operations"))
assert CLASSROOM_PREVIEW_WIDTH == 1920
assert CLASSROOM_JPEG_QUALITY >= 94
assert CLASSROOM_PREVIEW_ENHANCE is True
frame=np.full((720,1280,3),105,dtype=np.uint8)
frame[220:500,420:860]=135
out=StaticCameraService._enhance_classroom_preview(frame)
assert out.shape == frame.shape
assert out.dtype == frame.dtype
assert np.mean(np.abs(out.astype(np.int16)-frame.astype(np.int16))) > 0.05

js=(ROOT/'frontend/js/app.js').read_text(encoding='utf-8')
html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
assert 'classroomHdResolution' in js and 'classroomHdQuality' in js
assert 'classroom-hd-status' in html
assert 'camera_hd_v5.css' in html
assert 'apply_camera_hd_v5_config.py' in (ROOT/'START_CAMPUSFACE.bat').read_text(encoding='utf-8')
print('[OK] Camera HD V5 preview + migration contract')
