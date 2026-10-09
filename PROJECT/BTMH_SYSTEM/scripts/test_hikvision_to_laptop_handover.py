from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from module_app.camera import StaticCameraService
from module_app.camera_profiles import load_hikvision_profile


def wait_online(svc: StaticCameraService, source: str, timeout: float = 20.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        st = svc.status()
        if str(st.get("source") or "") == str(source) and st.get("opened") and str(st.get("state") or "") == "online":
            return True
        time.sleep(0.15)
    return False


def idle_worker(svc: StaticCameraService, generation: int | None = None) -> None:
    while svc._run_is_active(generation):
        time.sleep(0.05)


def main() -> int:
    profile = load_hikvision_profile()
    if profile is None:
        print("[FAIL] Khong tim thay profile Hikvision.")
        return 2

    svc = StaticCameraService()
    # This test targets camera handover only. Keep AI/preview workers idle so they
    # cannot affect the physical camera timing on a slower PC.
    svc._ai_loop = lambda generation=None: idle_worker(svc, generation)  # type: ignore[attr-defined]
    svc._preview_loop = lambda generation=None: idle_worker(svc, generation)  # type: ignore[attr-defined]

    print("=== CAMPUSFACE HANDOVER TEST: LAPTOP -> HIKVISION -> LAPTOP ===")
    try:
        svc.configure_source("0", "Camera laptop")
        svc.start()
        if not wait_online(svc, "0", 20.0):
            print("[FAIL] Camera laptop khong ONLINE luc khoi dong:", svc.status().get("error"))
            return 3
        st = svc.status()
        print(f"[PASS] Laptop start: {st.get('actual_width')}x{st.get('actual_height')} via {st.get('backend')}")

        r1 = svc.safe_select_source(profile.url, source_label=profile.name, stable_frames=5, timeout_sec=15.0)
        if not r1.get("ok"):
            print("[FAIL] Laptop -> Hikvision:", r1.get("message"), r1.get("error"))
            return 4
        st = svc.status()
        print(f"[PASS] Hikvision: {st.get('actual_width')}x{st.get('actual_height')} via {st.get('backend')}")

        r2 = svc.safe_select_source("0", source_label="Camera laptop", stable_frames=4, timeout_sec=18.0)
        if not r2.get("ok"):
            print("[FAIL] Hikvision -> Laptop:", r2.get("message"), r2.get("error"))
            print("[STATUS]", svc.status())
            return 5
        st = svc.status()
        print(f"[PASS] Laptop return: {st.get('actual_width')}x{st.get('actual_height')} via {st.get('backend')}")
        print("\nRESULT: PASS - Hikvision -> Camera laptop handover hoat dong.")
        return 0
    finally:
        svc.stop()


if __name__ == "__main__":
    raise SystemExit(main())
