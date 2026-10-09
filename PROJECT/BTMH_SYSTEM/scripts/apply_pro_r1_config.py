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
    comments: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            comments.append(raw)
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in values:
            order.append(key)
        values[key] = value.strip()

    if values.get("CAMPUSFACE_CONFIG_REV", "").upper() == "PRO_R1":
        return 0

    # Upgrade the old default capture mode once. If a customer later deliberately
    # selects 720p, the revision marker prevents this migration from changing it.
    if values.get("MODULE_CAMERA_WIDTH", "1280") == "1280" and values.get("MODULE_CAMERA_HEIGHT", "720") == "720":
        values["MODULE_CAMERA_WIDTH"] = "1920"
        values["MODULE_CAMERA_HEIGHT"] = "1080"
    values.setdefault("MODULE_CAMERA_AUTOFOCUS", "1")
    values.setdefault("MODULE_CAMERA_AUTO_EXPOSURE", "1")
    values.setdefault("MODULE_AI_NATIVE_FRAME", "1")
    values.setdefault("MODULE_AI_NATIVE_MAX_WIDTH", "1920")
    values.setdefault("MODULE_ANTI_SPOOF_RECOVERY_SEC", "0.55")
    values.setdefault("MODULE_ANTI_SPOOF_RECOVERY_CLEAN_FRAMES", "3")
    values.setdefault("MODULE_ANTI_SPOOF_RECOVERY_CONTEXT_MAX", "0.35")
    values["CAMPUSFACE_CONFIG_REV"] = "PRO_R1"

    for key in values:
        if key not in order:
            order.append(key)
    out = ["# CampusFace PRO R1 runtime configuration (migrated in place)"]
    out.extend(f"{key}={values[key]}" for key in order)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[OK] PRO R1 config applied: {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
