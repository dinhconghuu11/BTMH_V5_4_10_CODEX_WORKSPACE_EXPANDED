from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cam = (ROOT / "module_app/camera.py").read_text(encoding="utf-8")
js = (ROOT / "frontend/js/app.js").read_text(encoding="utf-8")
cfg = (ROOT / "module_app/config.py").read_text(encoding="utf-8")

assert "self._run_generation" in cam
assert "def _run_is_active" in cam
assert "args=(generation,)" in cam
assert "if not self._run_is_active(generation)" in cam
assert "async function prepareEnrollmentLaptopCamera" in js
assert "const cameraReady=await prepareEnrollmentLaptopCamera();" in js
assert "if(page==='register'){loadStudents();prepareEnrollmentLaptopCamera();}" in js
assert "return true;" in js and "return false;" in js
assert "1.41.0-facev1.3.1-enrollment-laptop-handover-fix" in cfg
print("[OK] FaceV1.3.1 enrollment laptop handover contract")
