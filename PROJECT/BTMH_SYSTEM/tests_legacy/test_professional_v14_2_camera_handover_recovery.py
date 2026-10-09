from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
js = (ROOT / "frontend/js/app.js").read_text(encoding="utf-8")
cam = (ROOT / "module_app/camera.py").read_text(encoding="utf-8")
cfg = (ROOT / "module_app/config.py").read_text(encoding="utf-8")

assert "const inHandover=!!(c.handover_active||handover.active);" in js
assert "c.handover_active||handover.active||c.recognition_paused" not in js
assert "def _reconcile_stale_pause" in cam
assert "self._recognition_paused = False" in cam
assert 'state="RECOVERED"' in cam or '"state": "RECOVERED"' in cam
assert "1.31.2-v1-face-pro-v14-2-camera-handover-recovery" in cfg
print("[OK] V14.2 camera handover recovery hotfix contract")
