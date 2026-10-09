from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from download_models import (  # type: ignore
    MODEL_SPECS,
    MODELS,
    SOURCE_MODELS,
    copy_verified,
    download_verified,
    find_existing,
    valid,
    valid_variant,
)

CORE = ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx")
PAD = "minifasnet_v2.onnx"


def prepare_required(name: str) -> bool:
    spec = MODEL_SPECS[name]
    dst = MODELS / name
    if valid(dst, spec):
        print(f"[OK] {name} already available")
        return True
    for alias in [name, *spec.get("aliases", [])]:
        src = SOURCE_MODELS / alias
        if valid(src, spec) and copy_verified(src, dst, spec):
            print(f"[OK] {name} copied from bundled package")
            return True
    if os.getenv("CAMPUSFACE_OFFLINE") == "1":
        print(f"[ERROR] Verified bundled model is missing: {name}; offline setup never downloads.")
        return False
    existing = find_existing(name, spec)
    if existing is not None and copy_verified(existing, dst, spec):
        print(f"[RECOVERED] {name} from {existing}")
        return True
    # Fresh PC only: short, one-pass download attempts for mandatory FaceID models.
    print(f"[INFO] {name} is missing; trying short download mirrors...")
    for idx, url in enumerate(spec.get("urls", [])[:3], 1):
        print(f"[DOWNLOAD] {name} source {idx}/3")
        ok, detail = download_verified(url, dst, spec)
        if ok:
            print(f"[OK] {name} downloaded and verified")
            return True
        print(f"[WARN] {detail}")
    print(f"[ERROR] Required FaceID model is unavailable: {name}")
    return False


def recover_optional_pad() -> None:
    spec = MODEL_SPECS[PAD]
    dst = MODELS / PAD
    if valid(dst, spec):
        v = valid_variant(dst, spec) or {}
        print(f"[OK] Optional Passive PAD enhancement ready ({v.get('name','verified')})")
        return
    for alias in [PAD, *spec.get("aliases", [])]:
        src = SOURCE_MODELS / alias
        if valid(src, spec) and copy_verified(src, dst, spec):
            print("[OK] Optional PAD copied from bundled package")
            return
    existing = find_existing(PAD, spec)
    if existing is not None and copy_verified(existing, dst, spec):
        print(f"[RECOVERED] Optional PAD from {existing}")
        return
    print("[INFO] Optional MiniFASNet PAD is not present. No network wait will occur.")
    print("[INFO] CampusFace will use built-in multi-frame phone/photo context anti-spoof fallback.")


def main() -> int:
    MODELS.mkdir(parents=True, exist_ok=True)
    for name in CORE:
        if not prepare_required(name):
            return 2
    if os.getenv("BTMH_ENV", "").lower() == "production" or os.getenv("CAMPUSFACE_OFFLINE") == "1":
        if not prepare_required(PAD):
            return 2
    else:
        recover_optional_pad()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
