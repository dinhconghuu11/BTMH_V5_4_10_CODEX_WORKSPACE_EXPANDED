from __future__ import annotations

import os
from pathlib import Path


REV = "V27_PERF_EVENT_AGG"


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


def _float(value: str, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _int(value: str, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def main() -> int:
    root = _data_root()
    env_path = root / "config" / "module.env"
    if not env_path.exists():
        # Fresh installs receive these defaults from module.env.example/config.py.
        return 0

    raw_lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    values: dict[str, str] = {}
    order: list[str] = []
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in values:
            order.append(key)
        values[key] = value

    if values.get("CAMPUSFACE_V27_REV", "") == REV:
        return 0

    # Preserve camera source/resolution/FPS. V2.7 only removes software bottlenecks.
    # Known V2.6 defaults are migrated; deliberate custom values outside these ranges
    # remain untouched.
    if _int(values.get("MODULE_CLASSROOM_PREVIEW_FPS", "20"), 20) <= 20:
        values["MODULE_CLASSROOM_PREVIEW_FPS"] = "25"
    if _int(values.get("MODULE_CLASSROOM_JPEG_QUALITY", "95"), 95) >= 94:
        values["MODULE_CLASSROOM_JPEG_QUALITY"] = "92"
    if _float(values.get("MODULE_QUICK_REARM_SEC", "1.25"), 1.25) <= 1.5:
        values["MODULE_QUICK_REARM_SEC"] = "2.60"
    if _float(values.get("MODULE_IDENTITY_REVERIFY_SEC", "0.85"), 0.85) <= 0.9:
        values["MODULE_IDENTITY_REVERIFY_SEC"] = "1.20"
    if _float(values.get("MODULE_DEVICE_CONTEXT_INTERVAL_SEC", "0.14"), 0.14) <= 0.14:
        values["MODULE_DEVICE_CONTEXT_INTERVAL_SEC"] = "0.18"

    # Meaningful-event policy: database writes are by physical episode/identity,
    # while AI can continue evaluating frames in memory.
    if _float(values.get("CAMPUSFACE_SAME_CAMERA_DEDUP_SEC", "60"), 60) <= 60:
        values["CAMPUSFACE_SAME_CAMERA_DEDUP_SEC"] = "300"
    values.setdefault("CAMPUSFACE_RECOGNITION_SESSION_DEDUP", "1")
    if _float(values.get("CAMPUSFACE_UNKNOWN_EVENT_DEDUP_SEC", "0"), 0) < 180:
        values["CAMPUSFACE_UNKNOWN_EVENT_DEDUP_SEC"] = "180"
    if _float(values.get("CAMPUSFACE_SPOOF_EVENT_DEDUP_SEC", "0"), 0) < 180:
        values["CAMPUSFACE_SPOOF_EVENT_DEDUP_SEC"] = "180"
    values.setdefault("CAMPUSFACE_SPOOF_PROMOTE_UNKNOWN_SEC", "90")
    values.setdefault("CAMPUSFACE_UNKNOWN_AFTER_SPOOF_HOLD_SEC", "60")
    values["CAMPUSFACE_V27_REV"] = REV

    for key in values:
        if key not in order:
            order.append(key)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    out = ["# CampusFace V2.7 performance + recognition event aggregation (migrated in place)"]
    out.extend(f"{key}={values[key]}" for key in order)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[OK] CampusFace V2.7 runtime policy applied: {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
