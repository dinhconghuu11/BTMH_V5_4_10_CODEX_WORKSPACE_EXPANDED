from __future__ import annotations

import sys
import time
from pathlib import Path

# When this file is executed as scripts\test_dual_camera_runtime.py, Python
# puts the scripts directory (not app\core) on sys.path. Add the CampusFace
# core directory explicitly so module_app is always importable from the
# one-click Windows self-test.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from module_app.camera import StaticCameraService
from module_app.camera_profiles import load_hikvision_profile, redact_camera_source


def test_source(label: str, source) -> bool:
    svc = StaticCameraService()
    print(f"[TEST] {label}: {redact_camera_source(str(source))}")
    cap, frame, plan = svc._open_best_capture(source)
    if cap is None or frame is None:
        status = svc.status()
        print(f"[FAIL] {label}: {status.get('error') or 'no stable frame'}")
        return False
    h, w = frame.shape[:2]
    print(f"[OK] {label}: {w}x{h} via {getattr(plan, 'backend_name', 'auto')}")
    svc._release_capture()
    time.sleep(0.15)
    return True


def main() -> int:
    profile = load_hikvision_profile()
    if profile is None:
        print("[FAIL] Khong tim thay Hikvision profile.")
        return 2
    laptop_ok = test_source("Camera laptop", 0)
    hik_ok = test_source(profile.name, profile.url)
    print("\nRESULT:")
    print(f"- Laptop: {'PASS' if laptop_ok else 'FAIL'}")
    print(f"- Hikvision RTSP: {'PASS' if hik_ok else 'FAIL'}")
    return 0 if laptop_ok and hik_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
