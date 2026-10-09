from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cam = (ROOT / "module_app/camera.py").read_text(encoding="utf-8")
cfg = (ROOT / "module_app/config.py").read_text(encoding="utf-8")
script = (ROOT / "scripts/test_hikvision_to_laptop_handover.py").read_text(encoding="utf-8")

assert "self._capture_plan_cache" in cam
assert "plans = [cached_plan]" in cam
assert "timeout_sec = max(float(timeout_sec), 16.0)" in cam
assert "time.sleep(0.65)" in cam
assert "thử mở lại webcam lần 2" in cam
assert "timeout_sec=1.4 if self._is_network_source(source) else 2.8" in cam
assert "1.42.0-facev1.3.2-laptop-return-stable-fix" in cfg
assert "LAPTOP -> HIKVISION -> LAPTOP" in script
print("[OK] FaceV1.3.2 laptop return stable contract")
