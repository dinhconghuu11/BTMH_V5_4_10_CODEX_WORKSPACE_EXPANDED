"""Launcher preflight with the same offline discovery as the native gateway."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_app.mediamtx_runtime import VERSION, is_development, require_mediamtx  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = os.getenv("CAMPUSFACE_DATA_ROOT", "").strip()
    if not default_root:
        default_root = str(Path(os.getenv("LOCALAPPDATA", str(ROOT))) / "CampusFace")
    parser.add_argument("--data-root", default=default_root)
    args = parser.parse_args()
    data_root = Path(os.path.expandvars(os.path.expanduser(args.data_root)))
    try:
        result = require_mediamtx(data_root)
    except RuntimeError as exc:
        print(f"[ERROR] Native Gateway: UNAVAILABLE; Reason: {exc}")
        if is_development():
            print("[ERROR] Development media preflight failed unexpectedly.")
        else:
            print("[ACTION] Production requires a supported verified MediaMTX runtime. Install a pinned local ZIP.")
        return 6
    if result.binary is None:
        print(f"[WARN] Native MediaMTX unavailable: {result.reason}")
        print("[INFO] Development fallback transport enabled")
        print("[INFO] Backend/frontend startup continues. Live View explicitly negotiates PYTHON_WEBRTC -> WEBSOCKET -> MJPEG -> POLLING.")
    else:
        print(f"[OK] MediaMTX {VERSION} verified. Native WebRTC remains the primary transport.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
