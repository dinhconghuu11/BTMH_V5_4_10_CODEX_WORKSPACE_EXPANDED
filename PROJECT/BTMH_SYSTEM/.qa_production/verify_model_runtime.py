"""Actual local model/load evidence; no camera, recognition or PAD accuracy claim."""
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".qa_production" / "model-runtime"
os.environ["CAMPUSFACE_DATA_ROOT"] = str(DATA)
os.environ["CAMPUSFACE_DB_MODE"] = "sqlite"
os.environ["MODULE_PAD_ENABLED"] = "1"
os.environ["BTMH_ENV"] = "production"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
(DATA / "models").mkdir(parents=True, exist_ok=True)
for name in ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx", "minifasnet_v2.onnx"):
    shutil.copyfile(ROOT / "models" / name, DATA / "models" / name)

from module_app.face_core import CORE
from module_app.passive_pad import PAD
from module_app.rtsp_native_v545 import resolve_ffmpeg

CORE.ensure()
pad = PAD.status()
ffmpeg = resolve_ffmpeg()
result = {"yunet_sface_load": "PASS", "passive_pad_model_probe": "PASS" if pad.get("ready") else "FAIL",
          "passive_pad": pad, "ffmpeg_resolved": bool(ffmpeg), "python": sys.version.split()[0],
          "real_face_spoof_camera_gpu_acceptance": "NOT_RUN"}
(ROOT / ".qa_production" / "model-runtime-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
raise SystemExit(0 if pad.get("ready") and ffmpeg else 2)
