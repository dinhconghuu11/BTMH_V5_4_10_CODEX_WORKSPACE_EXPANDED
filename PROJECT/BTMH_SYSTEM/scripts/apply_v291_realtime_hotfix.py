from __future__ import annotations

import os
from pathlib import Path

REV = "V291_CAMERA_REALTIME_HOTFIX"


def _data_root() -> Path:
    raw = os.getenv("CAMPUSFACE_DATA_ROOT", "").strip()
    if raw:
        return Path(os.path.expandvars(os.path.expanduser(raw)))
    if os.name == "nt":
        return Path(os.path.expandvars(r"%LOCALAPPDATA%")) / "CampusFace"
    return Path(__file__).resolve().parents[1] / ".campusface-data"


def main() -> int:
    root = _data_root()
    env_path = root / "config" / "module.env"
    values: dict[str, str] = {}
    order: list[str] = []
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key not in values:
                order.append(key)
            values[key] = value
    if values.get("CAMPUSFACE_V291_REV") == REV:
        return 0

    # Source camera remains 1920x1080/25. Only browser preview and Action AI use
    # bounded lanes so the laptop does less duplicate pixel work.
    values["MODULE_CLASSROOM_PREVIEW_FPS"] = "20"
    values["MODULE_CLASSROOM_PREVIEW_WIDTH"] = "1280"
    values["MODULE_CLASSROOM_JPEG_QUALITY"] = "86"
    values["MODULE_CLASSROOM_ACTION_FRAME_WIDTH"] = "1280"
    values.setdefault("MODULE_CLASSROOM_FACE_AI_WIDTH", "1280")
    values["CAMPUSFACE_V291_REV"] = REV

    for key in values:
        if key not in order:
            order.append(key)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    out = ["# CampusFace V2.9.1 camera stability + office realtime hotfix"]
    out.extend(f"{key}={values[key]}" for key in order)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[OK] CampusFace V2.9.1 realtime policy applied: {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
