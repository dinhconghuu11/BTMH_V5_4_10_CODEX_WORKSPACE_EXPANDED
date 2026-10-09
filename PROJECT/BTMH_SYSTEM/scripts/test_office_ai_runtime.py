from __future__ import annotations

import json
import sys

from module_app.gpu_manager import gpu_status
from module_app.office_engine import OFFICE


def main() -> int:
    print("=" * 64)
    print("FACEV1.2 OFFICE AI SELF-TEST")
    print("=" * 64)
    gpu = gpu_status(force=True)
    print(f"[GPU] mode={gpu.get('mode')} name={gpu.get('name')}")
    print(f"[GPU] acceleration={', '.join(gpu.get('acceleration') or []) or 'CPU only'}")
    print(f"[GPU] memory={gpu.get('memory_used_mb', 0)} / {gpu.get('memory_total_mb', 0)} MB")
    cfg = OFFICE.config()
    line = cfg.get('line') or {}
    print(f"[OFFICE] monitoring_enabled={cfg.get('monitoring_enabled')}")
    print(f"[GATE] configured={line.get('configured')} enabled={line.get('enabled')} name={line.get('name')}")
    print(f"[GATE] A=({line.get('x1')},{line.get('y1')}) B=({line.get('x2')},{line.get('y2')}) inside={line.get('inside_side')}")
    # Geometry smoke test independent of physical camera angle.
    probe = {"x1": 0.1, "y1": 0.5, "x2": 0.9, "y2": 0.5}
    a = OFFICE._signed_side((0.5, 0.25), probe)
    b = OFFICE._signed_side((0.5, 0.75), probe)
    if not (a < 0 < b):
        print("[FAIL] Virtual Gate geometry test failed")
        return 2
    print("[OK] Virtual Gate geometry")
    print("[OK] Office AI module loaded")
    print(json.dumps(gpu, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
