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
        key = key.strip()
        if key not in values:
            order.append(key)
        values[key] = value.strip()

    if values.get("CAMPUSFACE_CONFIG_REV", "").upper() == "PRO_R2":
        return 0

    # Keep every customer-selected camera/data option. R2 only adds defaults for
    # quality diagnostics and identity revalidation; it does not reset the database,
    # model paths, camera index, resolution or prior anti-spoof tuning.
    defaults = {
        "MODULE_CAMERA_QUALITY_INTERVAL_SEC": "0.65",
        "MODULE_CAMERA_SHARPNESS_WARN": "55",
        "MODULE_CAMERA_SHARPNESS_GOOD": "105",
        "MODULE_CAMERA_BRIGHTNESS_LOW": "42",
        "MODULE_CAMERA_BRIGHTNESS_HIGH": "218",
        "MODULE_CAMERA_CONTRAST_WARN": "24",
        "MODULE_CAMERA_MODE_ACCEPT_RATIO": "0.82",
        "MODULE_IDENTITY_REVERIFY_SEC": "0.85",
        "MODULE_IDENTITY_REVERIFY_SCORE": "0.58",
        "MODULE_IDENTITY_REVERIFY_MARGIN": "0.055",
        "MODULE_IDENTITY_REVERIFY_MISMATCHES": "2",
        "MODULE_IDENTITY_OWNER_GRACE_SEC": "0.75",
    }
    for key, value in defaults.items():
        values.setdefault(key, value)
    values["CAMPUSFACE_CONFIG_REV"] = "PRO_R2"

    for key in values:
        if key not in order:
            order.append(key)
    out = ["# CampusFace PRO R2 runtime configuration (migrated in place)"]
    out.extend(f"{key}={values[key]}" for key in order)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[OK] PRO R2 config applied: {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
