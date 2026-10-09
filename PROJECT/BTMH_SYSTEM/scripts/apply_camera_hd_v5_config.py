from __future__ import annotations

import os
from pathlib import Path


def _data_root() -> Path:
    raw = os.getenv("CAMPUSFACE_DATA_ROOT", "").strip()
    if raw:
        return Path(os.path.expandvars(os.path.expanduser(raw)))
    if os.name == "nt":
        local = Path(os.path.expandvars(r"%LOCALAPPDATA%"))
        stable = local / "CampusFace"
        legacy = local / "CampusFaceV1142"
        if (stable / "config" / "module.env").exists() or (stable / "PostgreSQL" / "data" / "PG_VERSION").exists():
            return stable
        if (legacy / "config" / "module.env").exists() or (legacy / "PostgreSQL" / "data" / "PG_VERSION").exists():
            return legacy
        return stable
    return Path(__file__).resolve().parents[1] / ".campusface-data"


def main() -> int:
    root = _data_root()
    env_path = root / "config" / "module.env"
    if not env_path.exists():
        return 0
    lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    values: dict[str, str] = {}
    order: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in values:
            order.append(key)
        values[key] = value
    if values.get("CAMPUSFACE_CAMERA_HD_REV", "").upper() == "HD_V5":
        return 0

    # Upgrade only known legacy/default values. Custom installer choices outside
    # these values are preserved. No database, FaceID template or student data is touched.
    if values.get("MODULE_CAMERA_WIDTH", "") in {"", "1280"} and values.get("MODULE_CAMERA_HEIGHT", "") in {"", "720"}:
        values["MODULE_CAMERA_WIDTH"] = "1920"
        values["MODULE_CAMERA_HEIGHT"] = "1080"
    if values.get("MODULE_CLASSROOM_PREVIEW_WIDTH", "") in {"", "640", "800", "1280"}:
        values["MODULE_CLASSROOM_PREVIEW_WIDTH"] = "1920"
    if values.get("MODULE_CLASSROOM_JPEG_QUALITY", "") in {"", "52", "65", "90"}:
        values["MODULE_CLASSROOM_JPEG_QUALITY"] = "94"
    if values.get("MODULE_CLASSROOM_PREVIEW_FPS", "") in {"", "12", "14"}:
        values["MODULE_CLASSROOM_PREVIEW_FPS"] = "20"
    values.setdefault("MODULE_CLASSROOM_PREVIEW_ENHANCE", "1")
    values.setdefault("MODULE_CLASSROOM_PREVIEW_SHARPEN", "0.18")
    values.setdefault("MODULE_CLASSROOM_PREVIEW_CONTRAST", "1.045")
    values.setdefault("MODULE_CLASSROOM_PREVIEW_BRIGHTNESS_TARGET", "128")
    values["CAMPUSFACE_CAMERA_HD_REV"] = "HD_V5"

    for key in values:
        if key not in order:
            order.append(key)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    out = ["# CampusFace Camera HD V5 runtime configuration (migrated in place)"]
    out.extend(f"{key}={values[key]}" for key in order)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[OK] Camera HD V5 config applied: {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
