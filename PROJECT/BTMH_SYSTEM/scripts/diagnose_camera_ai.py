"""Read-only local AI configuration audit; never starts cameras or writes a DB.

Run with the installed runtime on the Windows host. Output contains no camera
sources, passwords, sessions, user names, face images or recognition identities.
Worker memory/model inference requires the authenticated website runtime status;
file presence or registry settings alone do not prove inference is running.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
MODEL_PINS = {
    "face_detection_yunet_2023mar.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "face_recognition_sface_2021dec.onnx": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    "minifasnet_v2.onnx": ("b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907",
                           "d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b"),
}
FLAGS = ("MODULE_CAMERA_MODE", "MODULE_AI_NATIVE_FRAME", "MODULE_USE_CUSTOM_FACE_YOLO",
         "MODULE_PAD_ENABLED", "MODULE_DEVICE_CONTEXT", "BTMH_ENV", "BTMH_UI_PREVIEW")


def profile_root() -> Path:
    if os.getenv("CAMPUSFACE_DATA_ROOT"):
        return Path(os.path.expandvars(os.path.expanduser(os.environ["CAMPUSFACE_DATA_ROOT"])))
    local = Path(os.environ.get("LOCALAPPDATA", str(ROOT)))
    stable, legacy = local / "CampusFace", local / "CampusFaceV1142"
    markers = ("config/module.env", "PostgreSQL/data/PG_VERSION")
    if not any((stable / marker).exists() for marker in markers) and any((legacy / marker).exists() for marker in markers):
        return legacy
    return stable


def read_settings(root: Path) -> dict:
    values = {}
    for path in (root / "config/module.env", ROOT / "module.env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    values.update({key: value for key, value in os.environ.items() if key.startswith(("MODULE_", "CAMPUSFACE_", "BTMH_"))})
    return values


def safe_name(value) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    text = re.sub(r"(?:rtsps?|https?)://\S+", "[redacted]", text, flags=re.I)
    return re.sub(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", "[redacted]", text).strip()[:120]


def registry_snapshot(query) -> dict:
    cameras = query("SELECT id,name,zone_name,enabled,ai_enabled,attendance_enabled FROM camera_devices ORDER BY id")
    assignments = query("SELECT a.camera_device_id,a.store_id,s.store_name FROM camera_store_assignments a LEFT JOIN stores s ON s.id=a.store_id ORDER BY a.camera_device_id,a.store_id")
    items = []
    for camera in cameras:
        matching = [a for a in assignments if a["camera_device_id"] == camera["id"]]
        assigned = (len(matching) == 1 and matching[0]["store_name"] is not None
                    and type(matching[0]["store_id"]) is int and matching[0]["store_id"] > 0)
        reasons = []
        if not bool(camera["enabled"]):
            reasons.append("CAMERA_DISABLED")
        if not bool(camera["ai_enabled"]):
            reasons.append("AI_DISABLED")
        if not assigned:
            reasons.append("STORE_ASSIGNMENT_AMBIGUOUS" if len(matching) > 1 else "STORE_ASSIGNMENT_MISSING_OR_INVALID")
        if not safe_name(camera["zone_name"]):
            reasons.append("CAMERA_ZONE_REQUIRED")
        items.append({"camera_id": camera["id"], "camera_name": safe_name(camera["name"]),
                      "enabled": bool(camera["enabled"]), "ai_enabled": bool(camera["ai_enabled"]),
                      "zone_name": safe_name(camera["zone_name"]), "assignment_count": len(matching),
                      "store_id": matching[0]["store_id"] if assigned else None,
                      "store_name": safe_name(matching[0]["store_name"]) if assigned else None,
                      "eligible_configuration": not reasons, "blocking_reasons": reasons})
    return {"status": "READ_ONLY_OK", "cameras": items,
            "stores": [{"id": row["id"], "store_name": safe_name(row["store_name"])} for row in query("SELECT id,store_name FROM stores ORDER BY id")],
            "relevant_role_permissions": query("SELECT role,permission FROM role_permissions WHERE permission IN ('*','camera.configure','camera.live','camera.view','dashboard.view') ORDER BY role,permission"),
            "actor_scope": "NOT_INSPECTED: current browser account/session is not read"}


def inspect_database(root: Path, settings: dict) -> dict:
    mode = settings.get("CAMPUSFACE_DB_MODE", "postgres").lower()
    try:
        if mode == "sqlite":
            path = root / "data/recognition_module.db"
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                result = registry_snapshot(lambda sql: [dict(row) for row in connection.execute(sql).fetchall()])
        else:
            import psycopg
            from psycopg.rows import dict_row
            host = settings.get("CAMPUSFACE_POSTGRES_HOST", "127.0.0.1")
            if host not in {"127.0.0.1", "localhost", "::1"}:
                return {"status": "NOT_RUN", "reason_code": "NONLOCAL_DATABASE_NOT_INSPECTED"}
            spec = importlib.util.spec_from_file_location("btmh_readonly_secret_store", ROOT / "module_app/secret_store.py")
            secret_store = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(secret_store)  # this module imports no app/config and creates no folders
            password = secret_store.load_secret(root / "data/postgres_app_password.dpapi", settings.get("CAMPUSFACE_POSTGRES_PASSWORD", ""))
            if not password:
                return {"status": "BLOCKED", "reason_code": "LOCAL_DATABASE_CREDENTIAL_UNAVAILABLE"}
            with psycopg.connect(host=host, port=int(settings.get("CAMPUSFACE_POSTGRES_PORT", "55442")),
                                 dbname=settings.get("CAMPUSFACE_POSTGRES_DB", "campusface"),
                                 user=settings.get("CAMPUSFACE_POSTGRES_USER", "campusface_app"), password=password,
                                 sslmode=settings.get("CAMPUSFACE_POSTGRES_SSLMODE", "disable"), connect_timeout=5,
                                 options="-c default_transaction_read_only=on -c statement_timeout=5000",
                                 row_factory=dict_row, application_name="BTMH readonly AI diagnosis") as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                result = registry_snapshot(lambda sql: [dict(row) for row in connection.execute(sql).fetchall()])
                connection.rollback()
        return {"mode": mode, **result}
    except Exception as error:
        # Connection/library errors can echo addresses/credentials; never print them.
        return {"mode": mode, "status": "BLOCKED", "reason_code": "READ_ONLY_DB_UNAVAILABLE",
                "error_type": type(error).__name__, "sqlstate": getattr(error, "sqlstate", None)}


def inspect(root: Path) -> dict:
    settings = read_settings(root)
    models = []
    for name, expected in MODEL_PINS.items():
        path = root / "models" / name
        item = {"file": name, "present": path.is_file(), "role": "REQUIRED_FACEID_PAD"}
        if item["present"]:
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            item.update(size=path.stat().st_size, sha256=sha,
                        supported_hash=sha in (expected if isinstance(expected, tuple) else (expected,)))
        models.append(item)
    for name in ("campusface-face-yolo.pt", "yolo11n.pt"):
        models.append({"file": name, "present": (root / "models" / name).is_file(), "role": "OPTIONAL_YOLO"})
    packages = {}
    for name in ("opencv-contrib-python", "onnxruntime", "numpy", "psycopg", "ultralytics", "torch"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "NOT_INSTALLED"
    # Output only scalar flags, never arbitrary values from the environment file.
    flags = {key: settings[key] if re.fullmatch(r"[A-Za-z0-9_.-]{1,30}", settings[key]) else "[redacted]"
             for key in FLAGS if key in settings}
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "read_only": True,
            "data_root": str(root), "diagnostic_interpreter": sys.executable,
            "flags": flags, "models": models, "packages": packages,
            "default_flags_when_unset": {key: default for key, default in {
                "MODULE_PAD_ENABLED": "1", "MODULE_DEVICE_CONTEXT": "1",
                "MODULE_CAMERA_MODE": "service", "MODULE_USE_CUSTOM_FACE_YOLO": "auto"
            }.items() if key not in flags},
            "registry": inspect_database(root, settings),
            "worker_inference_and_frontend_events": "NOT_INSPECTED: collect authenticated website runtime status separately",
            "localhost_sandbox_limit": "Unavailable sandbox localhost does not prove host Production is stopped"}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=None, help="Existing profile; read only; no init/migration")
    args = parser.parse_args()
    try:
        result = inspect((args.data_root or profile_root()).resolve())
    except Exception as error:
        result = {"read_only": True, "status": "BLOCKED", "reason_code": "READ_ONLY_PROFILE_UNAVAILABLE", "error_type": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get("status") == "BLOCKED" or result.get("registry", {}).get("status") != "READ_ONLY_OK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
