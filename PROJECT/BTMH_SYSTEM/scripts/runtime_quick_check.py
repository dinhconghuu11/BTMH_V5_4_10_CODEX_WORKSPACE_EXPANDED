from __future__ import annotations

import importlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import sys

REQUIRED = ("fastapi", "uvicorn", "pydantic", "numpy", "cv2", "cryptography", "mediapipe", "psycopg", "imageio_ffmpeg", "onnxruntime", "argon2")
OPTIONAL = ("websockets", "aiortc", "av")


def main() -> int:
    missing = []
    for line in (Path(__file__).resolve().parents[1] / "requirements-runtime.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([\w.-]+)(?:\[[\w,.-]+\])?==([\w.+-]+)", line.strip())
        if not match:
            continue
        name, expected = match.groups()
        try:
            if version(name) != expected:
                missing.append(f"{name}: pinned version {expected} required")
        except PackageNotFoundError:
            missing.append(f"{name}: missing")
    for name in REQUIRED:
        try:
            importlib.import_module(name)
        except Exception as exc:
            missing.append(f"{name}: {exc}")
    if missing:
        print("[NEED-INSTALL] " + " | ".join(missing))
        return 2
    optional = []
    for name in OPTIONAL:
        try:
            importlib.import_module(name)
        except Exception:
            optional.append(name)
    print("[OK] Core Python runtime is already ready.")
    if optional:
        print("[INFO] Optional enhancement missing: " + ", ".join(optional))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
