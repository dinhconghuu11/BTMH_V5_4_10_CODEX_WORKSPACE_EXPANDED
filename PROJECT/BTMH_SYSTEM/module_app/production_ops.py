from __future__ import annotations

import base64
import csv
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    BACKUP_DIR, BASE_DIR, CONFIG_DIR, DATA_DIR, DATA_ROOT, DB_MODE, KEY_PATH, SQLITE_PATH,
    PHOTOS_DIR, EVENT_SNAPSHOTS_DIR,
    PG_SECRET_PATH, POSTGRES_BIN, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT,
    POSTGRES_SSLMODE, POSTGRES_USER,
)
from .db import connection, execute, fetchall, fetchone, utc_now
from .secret_store import load_secret
from .camera_profiles import load_hikvision_profile, normalize_camera_source, redact_camera_source

ENV_PATH = CONFIG_DIR / "module.env"

CAMERA_KEYS = {
    "source": "MODULE_CAMERA_SOURCE",
    "backend": "MODULE_CAMERA_BACKEND",
    "width": "MODULE_CAMERA_WIDTH",
    "height": "MODULE_CAMERA_HEIGHT",
    "fps": "MODULE_CAMERA_FPS",
    "fourcc": "MODULE_CAMERA_FOURCC",
    "preview_fps": "MODULE_CAMERA_PREVIEW_FPS",
    "observation_preview_fps": "BTMH_OBSERVATION_PREVIEW_FPS",
    "observation_preview_width": "BTMH_OBSERVATION_PREVIEW_WIDTH",
    "observation_jpeg_quality": "BTMH_OBSERVATION_JPEG_QUALITY",
}


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Thiếu thời gian")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ensure_production_schema(*, seed_cameras: bool = True) -> None:
    if DB_MODE == "postgres":
        schema = """
        CREATE TABLE IF NOT EXISTS attendance_sessions (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL DEFAULT '',
            room_name TEXT NOT NULL DEFAULT '',
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            grace_minutes INTEGER NOT NULL DEFAULT 5,
            status TEXT NOT NULL DEFAULT 'SCHEDULED',
            created_by TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_sessions_time ON attendance_sessions(start_at, end_at);
        CREATE TABLE IF NOT EXISTS attendance_records (
            id BIGSERIAL PRIMARY KEY,
            session_id BIGINT NOT NULL,
            student_id BIGINT NOT NULL,
            first_checkin_at TEXT,
            last_checkin_at TEXT,
            final_status TEXT NOT NULL DEFAULT 'ABSENT',
            source_event_id BIGINT,
            attempts INTEGER NOT NULL DEFAULT 0,
            rejected_attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_id, student_id),
            FOREIGN KEY(session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(source_event_id) REFERENCES recognition_events(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_records_session ON attendance_records(session_id, final_status);
        CREATE TABLE IF NOT EXISTS runtime_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS system_users (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'OPERATOR',
            password_salt TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS student_photos (
            id BIGSERIAL PRIMARY KEY,
            student_id BIGINT NOT NULL,
            photo_type TEXT NOT NULL DEFAULT 'PROFILE',
            relative_path TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT 'image/jpeg',
            sha256 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(student_id, photo_type),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_student_photos_student ON student_photos(student_id, photo_type);
        CREATE TABLE IF NOT EXISTS camera_devices (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            source TEXT NOT NULL UNIQUE,
            camera_type TEXT NOT NULL DEFAULT 'USB',
            zone_name TEXT NOT NULL DEFAULT '',
            resolution TEXT NOT NULL DEFAULT '1920x1080',
            target_fps INTEGER NOT NULL DEFAULT 30,
            ptz_enabled INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_camera_devices_zone ON camera_devices(zone_name, enabled);
        CREATE TABLE IF NOT EXISTS exception_reviews (
            id BIGSERIAL PRIMARY KEY,
            event_id BIGINT NOT NULL UNIQUE,
            decision TEXT NOT NULL DEFAULT 'PENDING',
            resolved_student_id BIGINT,
            reviewed_by TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES recognition_events(id) ON DELETE CASCADE,
            FOREIGN KEY(resolved_student_id) REFERENCES students(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_exception_reviews_decision ON exception_reviews(decision, updated_at);
        CREATE TABLE IF NOT EXISTS attendance_adjustments (
            id BIGSERIAL PRIMARY KEY,
            session_id BIGINT NOT NULL,
            student_id BIGINT NOT NULL,
            original_status TEXT NOT NULL DEFAULT '',
            new_status TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_adjustments_record ON attendance_adjustments(session_id, student_id, created_at);
        CREATE TABLE IF NOT EXISTS attendance_record_events (
            id BIGSERIAL PRIMARY KEY,
            session_id BIGINT NOT NULL,
            student_id BIGINT NOT NULL,
            recognition_event_id BIGINT,
            event_type TEXT NOT NULL DEFAULT 'CHECKIN',
            event_at TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(recognition_event_id) REFERENCES recognition_events(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_record_events_record ON attendance_record_events(session_id, student_id, event_at);
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS attendance_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL DEFAULT '',
            room_name TEXT NOT NULL DEFAULT '',
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            grace_minutes INTEGER NOT NULL DEFAULT 5,
            status TEXT NOT NULL DEFAULT 'SCHEDULED',
            created_by TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_sessions_time ON attendance_sessions(start_at, end_at);
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            first_checkin_at TEXT,
            last_checkin_at TEXT,
            final_status TEXT NOT NULL DEFAULT 'ABSENT',
            source_event_id INTEGER,
            attempts INTEGER NOT NULL DEFAULT 0,
            rejected_attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_id, student_id),
            FOREIGN KEY(session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(source_event_id) REFERENCES recognition_events(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_records_session ON attendance_records(session_id, final_status);
        CREATE TABLE IF NOT EXISTS runtime_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS system_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'OPERATOR',
            password_salt TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS student_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            photo_type TEXT NOT NULL DEFAULT 'PROFILE',
            relative_path TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT 'image/jpeg',
            sha256 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(student_id, photo_type),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_student_photos_student ON student_photos(student_id, photo_type);
        CREATE TABLE IF NOT EXISTS camera_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source TEXT NOT NULL UNIQUE,
            camera_type TEXT NOT NULL DEFAULT 'USB',
            zone_name TEXT NOT NULL DEFAULT '',
            resolution TEXT NOT NULL DEFAULT '1920x1080',
            target_fps INTEGER NOT NULL DEFAULT 30,
            ptz_enabled INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_camera_devices_zone ON camera_devices(zone_name, enabled);
        CREATE TABLE IF NOT EXISTS exception_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL UNIQUE,
            decision TEXT NOT NULL DEFAULT 'PENDING',
            resolved_student_id INTEGER,
            reviewed_by TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES recognition_events(id) ON DELETE CASCADE,
            FOREIGN KEY(resolved_student_id) REFERENCES students(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_exception_reviews_decision ON exception_reviews(decision, updated_at);
        CREATE TABLE IF NOT EXISTS attendance_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            original_status TEXT NOT NULL DEFAULT '',
            new_status TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_adjustments_record ON attendance_adjustments(session_id, student_id, created_at);
        CREATE TABLE IF NOT EXISTS attendance_record_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            recognition_event_id INTEGER,
            event_type TEXT NOT NULL DEFAULT 'CHECKIN',
            event_at TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(recognition_event_id) REFERENCES recognition_events(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_record_events_record ON attendance_record_events(session_id, student_id, event_at);
        """
    with connection() as conn:
        conn.executescript(schema)
    if seed_cameras:
        seed_default_camera_devices()

def create_session(name: str, class_name: str, room_name: str, start_at: str, end_at: str, grace_minutes: int = 5, created_by: str = "admin") -> dict:
    start = _parse_iso(start_at)
    end = _parse_iso(end_at)
    if end <= start:
        raise ValueError("Giờ kết thúc phải sau giờ bắt đầu")
    grace = max(0, min(180, int(grace_minutes)))
    now = utc_now()
    status = "ACTIVE" if start <= datetime.now(timezone.utc) <= end else "SCHEDULED"
    sid = execute(
        """INSERT INTO attendance_sessions(name,class_name,room_name,start_at,end_at,grace_minutes,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (str(name).strip() or "Hiện diện", str(class_name).strip(), str(room_name).strip(), _iso(start), _iso(end), grace, status, str(created_by or "admin"), now, now),
    )
    initialize_roster(sid)
    return get_session(sid)


def initialize_roster(session_id: int) -> int:
    session = fetchone("SELECT * FROM attendance_sessions WHERE id=?", (session_id,))
    if not session:
        raise ValueError("Không tìm thấy phiên hiện diện")
    cls = str(session.get("class_name") or "").strip()
    if cls:
        students = fetchall("SELECT id FROM students WHERE class_name=? ORDER BY id", (cls,))
    else:
        students = fetchall("SELECT id FROM students ORDER BY id")
    now = utc_now()
    count = 0
    with connection() as conn:
        for s in students:
            conn.execute(
                """INSERT OR IGNORE INTO attendance_records(session_id,student_id,final_status,created_at,updated_at)
                VALUES(?,?,?,?,?)""",
                (session_id, int(s["id"]), "ABSENT", now, now),
            )
            count += 1
    return count


def get_session(session_id: int) -> dict:
    row = fetchone("SELECT * FROM attendance_sessions WHERE id=?", (session_id,))
    if not row:
        raise ValueError("Không tìm thấy phiên hiện diện")
    row["summary"] = session_summary(session_id)
    return row


def list_sessions(limit: int = 100) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = fetchall("SELECT * FROM attendance_sessions ORDER BY start_at DESC LIMIT ?", (max(1, min(500, int(limit))),))
    for row in rows:
        try:
            start, end = _parse_iso(row["start_at"]), _parse_iso(row["end_at"])
            auto = "ACTIVE" if start <= now <= end else "ENDED" if now > end else "SCHEDULED"
            if row.get("status") != "CLOSED":
                row["status"] = auto
        except Exception:
            pass
        row["summary"] = session_summary(int(row["id"]))
    return rows


def active_session_for_student(student_id: int, at: str | None = None) -> dict | None:
    when = _parse_iso(at or utc_now())
    student = fetchone("SELECT class_name FROM students WHERE id=?", (student_id,))
    if not student:
        return None
    cls = str(student.get("class_name") or "")
    rows = fetchall(
        """SELECT * FROM attendance_sessions
        WHERE status!='CLOSED' AND start_at<=? AND end_at>=?
        AND (class_name='' OR class_name=?)
        ORDER BY CASE WHEN class_name=? THEN 0 ELSE 1 END, start_at DESC LIMIT 1""",
        (_iso(when), _iso(when), cls, cls),
    )
    return rows[0] if rows else None



def _runtime_int(key: str, default: int, low: int, high: int) -> int:
    row = fetchone("SELECT setting_value FROM runtime_settings WHERE setting_key=?", (key,))
    try:
        value = int(float((row or {}).get("setting_value") or default))
    except Exception:
        value = default
    return max(low, min(high, value))


def operations_rules() -> dict:
    row = fetchone("SELECT setting_value FROM runtime_settings WHERE setting_key=?", ("exception_low_confidence",))
    try:
        low_conf = float((row or {}).get("setting_value") or 0.72)
    except Exception:
        low_conf = 0.72
    return {
        "duplicate_window_seconds": _runtime_int("attendance_duplicate_window_seconds", 45, 5, 600),
        "reentry_gap_minutes": _runtime_int("attendance_reentry_gap_minutes", 10, 1, 240),
        "exception_low_confidence": max(0.35, min(0.99, low_conf)),
        "evidence_retention_days": _runtime_int("evidence_retention_days", 30, 1, 3650),
    }


def save_operations_rules(values: dict) -> dict:
    current = operations_rules()
    merged = {**current, **(values or {})}
    clean = {
        "attendance_duplicate_window_seconds": max(5, min(600, int(merged.get("duplicate_window_seconds", 45)))),
        "attendance_reentry_gap_minutes": max(1, min(240, int(merged.get("reentry_gap_minutes", 10)))),
        "exception_low_confidence": max(0.35, min(0.99, float(merged.get("exception_low_confidence", 0.72)))),
        "evidence_retention_days": max(1, min(3650, int(merged.get("evidence_retention_days", 30)))),
    }
    now = utc_now()
    for key, value in clean.items():
        existing = fetchone("SELECT setting_key FROM runtime_settings WHERE setting_key=?", (key,))
        if existing:
            execute("UPDATE runtime_settings SET setting_value=?,updated_at=? WHERE setting_key=?", (str(value), now, key))
        else:
            execute("INSERT INTO runtime_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)", (key, str(value), now))
    return operations_rules()


def _log_attendance_record_event(session_id: int, student_id: int, recognition_event_id: int | None, event_type: str, event_at: str, detail: dict | None = None) -> None:
    now = utc_now()
    execute(
        """INSERT INTO attendance_record_events(session_id,student_id,recognition_event_id,event_type,event_at,detail_json,created_at)
        VALUES(?,?,?,?,?,?,?)""",
        (int(session_id), int(student_id), recognition_event_id, str(event_type), str(event_at), json.dumps(detail or {}, ensure_ascii=False), now),
    )


def apply_successful_checkin(event_id: int, student_id: int, event_at: str) -> dict | None:
    session = active_session_for_student(student_id, event_at)
    if not session:
        return None
    sid = int(session["id"])
    initialize_roster(sid)
    start = _parse_iso(session["start_at"])
    when = _parse_iso(event_at)
    grace = int(session.get("grace_minutes") or 0)
    late_after = start.timestamp() + grace * 60
    status = "LATE" if when.timestamp() > late_after else "PRESENT"
    now = utc_now()
    rules = operations_rules()
    current = fetchone("SELECT * FROM attendance_records WHERE session_id=? AND student_id=?", (sid, student_id))
    event_type = "FIRST_CHECKIN"
    gap_seconds = None
    if current and current.get("last_checkin_at"):
        try:
            previous = _parse_iso(str(current.get("last_checkin_at")))
            gap_seconds = max(0.0, (when - previous).total_seconds())
        except Exception:
            gap_seconds = None
        if gap_seconds is not None and gap_seconds <= int(rules["duplicate_window_seconds"]):
            event_type = "DUPLICATE"
        elif gap_seconds is not None and gap_seconds >= int(rules["reentry_gap_minutes"]) * 60:
            event_type = "REENTRY"
        else:
            event_type = "REPEAT"
    if current:
        first = current.get("first_checkin_at") or event_at
        final = current.get("final_status") or "ABSENT"
        if final == "ABSENT" or (final == "LATE" and status == "PRESENT"):
            final = status
        execute(
            """UPDATE attendance_records SET first_checkin_at=?,last_checkin_at=?,final_status=?,source_event_id=?,attempts=attempts+1,updated_at=?
            WHERE session_id=? AND student_id=?""",
            (first, event_at, final, event_id, now, sid, student_id),
        )
    else:
        execute(
            """INSERT INTO attendance_records(session_id,student_id,first_checkin_at,last_checkin_at,final_status,source_event_id,attempts,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (sid, student_id, event_at, event_at, status, event_id, 1, now, now),
        )
    _log_attendance_record_event(sid, student_id, event_id, event_type, event_at, {"gap_seconds": gap_seconds, "computed_status": status})
    return {"session_id": sid, "attendance_status": status, "attendance_event_type": event_type, "gap_seconds": gap_seconds}


def apply_rejected_checkin(student_id: int | None, event_at: str) -> None:
    if not student_id:
        return
    session = active_session_for_student(int(student_id), event_at)
    if not session:
        return
    sid = int(session["id"])
    initialize_roster(sid)
    execute(
        """UPDATE attendance_records SET rejected_attempts=rejected_attempts+1,updated_at=?
        WHERE session_id=? AND student_id=?""",
        (utc_now(), sid, int(student_id)),
    )


def session_summary(session_id: int) -> dict:
    total = fetchone("SELECT COUNT(*) n FROM attendance_records WHERE session_id=?", (session_id,)) or {"n": 0}
    grouped = fetchall("SELECT final_status,COUNT(*) n FROM attendance_records WHERE session_id=? GROUP BY final_status", (session_id,))
    counts = {str(r["final_status"]): int(r["n"]) for r in grouped}
    rejected = fetchone("SELECT COALESCE(SUM(rejected_attempts),0) n FROM attendance_records WHERE session_id=?", (session_id,)) or {"n": 0}
    return {
        "total": int(total["n"]),
        "present": int(counts.get("PRESENT", 0)),
        "late": int(counts.get("LATE", 0)),
        "absent": int(counts.get("ABSENT", 0)),
        "excused": int(counts.get("EXCUSED", 0)),
        "early_leave": int(counts.get("EARLY_LEAVE", 0)),
        "rejected_attempts": int(rejected["n"] or 0),
    }



def session_ledger(session_id: int) -> list[dict]:
    initialize_roster(session_id)
    rows = fetchall(
        """SELECT ar.id,ar.session_id,ar.student_id,ar.first_checkin_at,ar.last_checkin_at,ar.final_status,ar.attempts,ar.rejected_attempts,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM attendance_records ar JOIN students s ON s.id=ar.student_id
        WHERE ar.session_id=? ORDER BY CASE ar.final_status WHEN 'ABSENT' THEN 2 WHEN 'LATE' THEN 1 ELSE 0 END,s.full_name""",
        (session_id,),
    )
    for row in rows:
        adj = fetchone(
            """SELECT original_status,new_status,reason,actor,created_at FROM attendance_adjustments
            WHERE session_id=? AND student_id=? ORDER BY id DESC LIMIT 1""",
            (session_id, int(row["student_id"])),
        )
        events = fetchall(
            """SELECT event_type,event_at,recognition_event_id FROM attendance_record_events
            WHERE session_id=? AND student_id=? ORDER BY id DESC LIMIT 8""",
            (session_id, int(row["student_id"])),
        )
        row["manual_adjustment"] = adj
        row["recent_events"] = events
        row["reentry_count"] = sum(1 for e in events if str(e.get("event_type") or "").upper() == "REENTRY")
        row["duplicate_count"] = sum(1 for e in events if str(e.get("event_type") or "").upper() == "DUPLICATE")
    return rows


def adjust_attendance_record(session_id: int, student_id: int, new_status: str, reason: str, actor: str) -> dict:
    allowed = {"PRESENT", "LATE", "ABSENT", "EXCUSED", "EARLY_LEAVE"}
    status = str(new_status or "").strip().upper()
    if status not in allowed:
        raise ValueError("Trạng thái hiện diện không hợp lệ")
    clean_reason = str(reason or "").strip()
    if len(clean_reason) < 3:
        raise ValueError("Cần nhập lý do điều chỉnh")
    row = fetchone("SELECT * FROM attendance_records WHERE session_id=? AND student_id=?", (int(session_id), int(student_id)))
    if not row:
        raise ValueError("Không tìm thấy bản ghi hiện diện")
    old = str(row.get("final_status") or "ABSENT").upper()
    now = utc_now()
    execute(
        """INSERT INTO attendance_adjustments(session_id,student_id,original_status,new_status,reason,actor,created_at)
        VALUES(?,?,?,?,?,?,?)""",
        (int(session_id), int(student_id), old, status, clean_reason[:1000], str(actor or "operator")[:120], now),
    )
    execute("UPDATE attendance_records SET final_status=?,updated_at=? WHERE session_id=? AND student_id=?", (status, now, int(session_id), int(student_id)))
    return {
        "session_id": int(session_id), "student_id": int(student_id), "original_status": old,
        "new_status": status, "reason": clean_reason, "actor": str(actor or "operator"), "updated_at": now,
    }


def close_session(session_id: int) -> dict:
    if not fetchone("SELECT id FROM attendance_sessions WHERE id=?", (session_id,)):
        raise ValueError("Không tìm thấy phiên")
    execute("UPDATE attendance_sessions SET status='CLOSED',updated_at=? WHERE id=?", (utc_now(), session_id))
    return get_session(session_id)


def session_csv(session_id: int) -> bytes:
    session = get_session(session_id)
    rows = session_ledger(session_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Phiên", session["name"], "Bộ phận", session["class_name"], "Bắt đầu", session["start_at"], "Kết thúc", session["end_at"]])
    writer.writerow([])
    writer.writerow(["Mã nhân viên", "Họ tên", "Bộ phận", "Trạng thái", "Check-in đầu", "Check-in cuối", "Số lần hợp lệ", "Lần bị từ chối"])
    for r in rows:
        writer.writerow([r["student_code"], r["full_name"], r["class_name"], r["final_status"], r.get("first_checkin_at") or "", r.get("last_checkin_at") or "", r.get("attempts") or 0, r.get("rejected_attempts") or 0])
    return ("\ufeff" + out.getvalue()).encode("utf-8")



def _json_obj(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _env_dict() -> dict[str, str]:
    if not ENV_PATH.exists() and (BASE_DIR / "module.env.example").exists():
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASE_DIR / "module.env.example", ENV_PATH)
    result: dict[str, str] = {}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def camera_settings() -> dict:
    env = _env_dict()
    defaults = {
        "source": os.getenv("MODULE_CAMERA_SOURCE", "0"),
        "backend": os.getenv("MODULE_CAMERA_BACKEND", "auto"),
        "width": os.getenv("MODULE_CAMERA_WIDTH", "1920"),
        "height": os.getenv("MODULE_CAMERA_HEIGHT", "1080"),
        "fps": os.getenv("MODULE_CAMERA_FPS", "30"),
        "fourcc": os.getenv("MODULE_CAMERA_FOURCC", "auto"),
        "preview_fps": os.getenv("MODULE_CAMERA_PREVIEW_FPS", "25"),
        "observation_preview_fps": os.getenv("BTMH_OBSERVATION_PREVIEW_FPS", os.getenv("MODULE_CLASSROOM_PREVIEW_FPS", "25")),
        "observation_preview_width": os.getenv("BTMH_OBSERVATION_PREVIEW_WIDTH", os.getenv("MODULE_CLASSROOM_PREVIEW_WIDTH", "1920")),
        "observation_jpeg_quality": os.getenv("BTMH_OBSERVATION_JPEG_QUALITY", os.getenv("MODULE_CLASSROOM_JPEG_QUALITY", "92")),
    }
    return {key: env.get(env_key, defaults[key]) for key, env_key in CAMERA_KEYS.items()}


def save_camera_settings(payload: dict[str, Any]) -> dict:
    current = _env_dict()
    clean = {
        "source": normalize_camera_source(str(payload.get("source", "0")).strip()),
        "backend": str(payload.get("backend", "auto")).strip().lower(),
        "width": str(max(320, min(3840, int(payload.get("width", 1920))))),
        "height": str(max(240, min(2160, int(payload.get("height", 1080))))),
        "fps": str(max(5, min(60, int(payload.get("fps", 30))))),
        "fourcc": str(payload.get("fourcc", "auto")).strip().upper(),
        "preview_fps": str(max(5, min(30, int(payload.get("preview_fps", 25))))),
        "observation_preview_fps": str(max(10, min(30, int(payload.get("observation_preview_fps", payload.get("classroom_preview_fps", 25)))))),
        "observation_preview_width": str(max(720, min(1920, int(payload.get("observation_preview_width", payload.get("classroom_preview_width", 1920)))))),
        "observation_jpeg_quality": str(max(75, min(95, int(payload.get("observation_jpeg_quality", payload.get("classroom_jpeg_quality", 92)))))),
    }
    for legacy_key in ("MODULE_CLASSROOM_PREVIEW_FPS", "MODULE_CLASSROOM_PREVIEW_WIDTH", "MODULE_CLASSROOM_JPEG_QUALITY"):
        current.pop(legacy_key, None)
    for key, env_key in CAMERA_KEYS.items():
        current[env_key] = clean[key]
    lines = ["# BTMH Security runtime configuration"]
    for key in sorted(current):
        lines.append(f"{key}={current[key]}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {**clean, "restart_required": True, "path": str(ENV_PATH)}


def _postgres_password() -> str:
    return load_secret(PG_SECRET_PATH, os.getenv("CAMPUSFACE_POSTGRES_PASSWORD", "").strip())


def _pg_tool(name: str) -> Path:
    exe = f"{name}.exe" if os.name == "nt" else name
    candidates = [POSTGRES_BIN / exe]
    found = shutil.which(exe) or shutil.which(name)
    if found:
        candidates.append(Path(found))
    if os.name == "nt":
        pf = Path(os.getenv("ProgramFiles", r"C:\Program Files"))
        candidates.extend(sorted((pf / "PostgreSQL").glob(f"*/bin/{exe}"), reverse=True))
    for path in candidates:
        if path and path.exists():
            return path
    raise RuntimeError(f"Không tìm thấy {exe}. Hãy chạy SETUP_POSTGRESQL_WINDOWS.bat")


def _pg_env() -> dict[str, str]:
    password = _postgres_password()
    if not password:
        raise RuntimeError("Thiếu PostgreSQL credential của CampusFace")
    env = dict(os.environ)
    env["PGPASSWORD"] = password
    return env


def _pg_common_args() -> list[str]:
    return ["--host", POSTGRES_HOST, "--port", str(POSTGRES_PORT), "--username", POSTGRES_USER]


def create_backup(label: str = "manual") -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in str(label or "manual") if c.isalnum() or c in "-_ ").strip().replace(" ", "-")[:32] or "manual"
    filename = f"CampusFace-Backup-{stamp}-{safe}.zip"
    final = BACKUP_DIR / filename
    with tempfile.TemporaryDirectory(prefix="campusface-backup-") as td:
        temp = Path(td)
        if DB_MODE == "postgres":
            dump_name = "campusface.dump"
            dump_path = temp / dump_name
            cmd = [str(_pg_tool("pg_dump")), *_pg_common_args(), "--dbname", POSTGRES_DB,
                   "--format=custom", "--compress=6", "--no-owner", "--no-privileges", "--file", str(dump_path)]
            cp = subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True, timeout=180)
            if cp.returncode != 0 or not dump_path.exists():
                raise RuntimeError(f"pg_dump thất bại: {(cp.stderr or cp.stdout).strip()}")
            manifest = {
                "format": 2,
                "created_at": utc_now(),
                "database_mode": "postgres",
                "database": dump_name,
                "database_name": POSTGRES_DB,
                "includes_face_key": KEY_PATH.exists(),
                "source_data_root": str(DATA_ROOT),
            }
        else:
            dump_name = "recognition_module.db"
            dump_path = temp / dump_name
            src = sqlite3.connect(SQLITE_PATH)
            dst = sqlite3.connect(dump_path)
            try:
                src.backup(dst)
            finally:
                dst.close(); src.close()
            manifest = {
                "format": 1,
                "created_at": utc_now(),
                "database_mode": "sqlite",
                "database": dump_name,
                "includes_face_key": KEY_PATH.exists(),
                "source_data_root": str(DATA_ROOT),
            }
        (temp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if KEY_PATH.exists():
            shutil.copy2(KEY_PATH, temp / "face_templates.key")
        if ENV_PATH.exists():
            shutil.copy2(ENV_PATH, temp / "module.env")
        # V2.10: keep operational JSON configuration (Virtual Gate, watchdog,
        # local UI policies) with the backup. Secrets stay in their existing
        # protected stores; runtime DB credentials are not restored implicitly.
        config_copy = temp / "Config"
        copied_config = []
        if CONFIG_DIR.exists():
            for cfg_file in CONFIG_DIR.glob("*.json"):
                try:
                    config_copy.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cfg_file, config_copy / cfg_file.name)
                    copied_config.append(cfg_file.name)
                except OSError:
                    pass
        media_manifest = {}
        if PHOTOS_DIR.exists():
            photos_copy = temp / "Photos"
            shutil.copytree(PHOTOS_DIR, photos_copy, dirs_exist_ok=True)
            media_manifest["photos"] = "Photos"
        if EVENT_SNAPSHOTS_DIR.exists():
            snapshots_copy = temp / "Snapshots"
            shutil.copytree(EVENT_SNAPSHOTS_DIR, snapshots_copy, dirs_exist_ok=True)
            media_manifest["snapshots"] = "Snapshots"
        if media_manifest:
            manifest["media"] = media_manifest
        if copied_config:
            manifest["config_files"] = copied_config
        if media_manifest or copied_config:
            (temp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(final, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in temp.rglob("*"):
                if item.is_file():
                    zf.write(item, item.relative_to(temp).as_posix())
    return {"name": filename, "path": str(final), "size": final.stat().st_size, "created_at": datetime.fromtimestamp(final.stat().st_mtime, timezone.utc).isoformat()}


def list_backups() -> list[dict]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(BACKUP_DIR.glob("CampusFace-Backup-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        rows.append({"name": p.name, "size": p.stat().st_size, "created_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()})
    return rows


def backup_path(name: str) -> Path:
    p = (BACKUP_DIR / Path(str(name)).name).resolve()
    if p.parent != BACKUP_DIR.resolve() or not p.exists() or p.suffix.lower() != ".zip":
        raise ValueError("Không tìm thấy bản sao lưu")
    return p


def import_backup(name: str, data: bytes) -> dict:
    if not data or len(data) > 1024 * 1024 * 1000:
        raise ValueError("File backup không hợp lệ hoặc quá lớn")
    safe = Path(name or "CampusFace-Backup-imported.zip").name
    if not safe.lower().endswith(".zip"):
        safe += ".zip"
    path = BACKUP_DIR / safe
    path.write_bytes(data)
    try:
        validate_backup(path)
    except Exception:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise
    return {"name": path.name, "size": path.stat().st_size, "imported": True}



def seed_default_camera_devices() -> None:
    """Seed absent devices only. Never overwrite an operator's camera configuration.

    Earlier versions called a destructive migration on every list read, allowing a
    stale bundled/local Hikvision profile to silently restore an obsolete IP or
    password. Only a clearly unconfigured legacy USB placeholder may be upgraded.
    """
    now = utc_now()
    if not fetchone("SELECT id FROM camera_devices WHERE source=?", ("0",)):
        execute("""INSERT INTO camera_devices(name,source,camera_type,zone_name,resolution,target_fps,ptz_enabled,enabled,notes,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                ("Camera laptop", "0", "LAPTOP", "", "1920x1080", 30, 0, 1, "", now, now))
    profile = load_hikvision_profile()
    if profile is None:
        return
    source = normalize_camera_source(profile.url)
    if fetchone("SELECT id FROM camera_devices WHERE source=?", (source,)):
        return
    # Any saved RTSP configuration wins over a profile/template on disk.
    if fetchone("SELECT id FROM camera_devices WHERE LOWER(source) LIKE 'rtsp://%' LIMIT 1"):
        return
    legacy = fetchone("SELECT id FROM camera_devices WHERE source='1' AND name='Camera PTZ' AND camera_type='PTZ' ORDER BY id LIMIT 1")
    if legacy:
        execute("UPDATE camera_devices SET name=?,source=?,camera_type='RTSP',updated_at=? WHERE id=?",
                (profile.name or "Hikvision Camera", source, now, int(legacy["id"])))
    else:
        execute("""INSERT INTO camera_devices(name,source,camera_type,zone_name,resolution,target_fps,ptz_enabled,enabled,notes,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (profile.name or "Hikvision Camera", source, "RTSP", "", "1920x1080", 25, 0, 1, "", now, now))


def list_camera_devices() -> list[dict]:
    # Schema initialization seeds once; a read must never mutate connection data.
    rows = fetchall("SELECT * FROM camera_devices ORDER BY enabled DESC,id")
    active_source = str(camera_settings().get("source") or "0")
    for row in rows:
        row["active"] = str(row.get("source") or "") == active_source
        row["ptz_enabled"] = bool(row.get("ptz_enabled"))
        row["enabled"] = bool(row.get("enabled"))
    return rows


def save_camera_device(values: dict, device_id: int | None = None) -> dict:
    name = str(values.get("name") or "Camera").strip()[:120]
    source = normalize_camera_source(str(values.get("source") or "0").strip())
    camera_type = str(values.get("camera_type") or "USB").strip().upper()[:40]
    zone_name = str(values.get("zone_name") or "").strip()[:120]
    resolution = str(values.get("resolution") or "1920x1080").strip()[:40]
    target_fps = max(5, min(60, int(values.get("target_fps") or 30)))
    ptz_enabled = 1 if bool(values.get("ptz_enabled")) else 0
    enabled = 1 if values.get("enabled", True) else 0
    notes = str(values.get("notes") or "").strip()[:1000]
    now = utc_now()
    from .capture_session_v544 import valid_source, ERRORS
    try:
        source = valid_source(source)
    except ValueError as exc:
        raise ValueError(ERRORS.get(str(exc), ERRORS["INVALID_SOURCE"])) from None
    existing = fetchone("SELECT id FROM camera_devices WHERE source=?", (source,))
    if existing and (device_id is None or int(existing["id"]) != int(device_id)):
        raise ValueError("Nguồn camera đã tồn tại trong danh sách")
    if device_id is None:
        device_id = execute(
            """INSERT INTO camera_devices(name,source,camera_type,zone_name,resolution,target_fps,ptz_enabled,enabled,notes,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (name, source, camera_type, zone_name, resolution, target_fps, ptz_enabled, enabled, notes, now, now),
        )
    else:
        if not fetchone("SELECT id FROM camera_devices WHERE id=?", (int(device_id),)):
            raise ValueError("Không tìm thấy camera")
        execute(
            """UPDATE camera_devices SET name=?,source=?,camera_type=?,zone_name=?,resolution=?,target_fps=?,ptz_enabled=?,enabled=?,notes=?,updated_at=? WHERE id=?""",
            (name, source, camera_type, zone_name, resolution, target_fps, ptz_enabled, enabled, notes, now, int(device_id)),
        )
    return fetchone("SELECT * FROM camera_devices WHERE id=?", (int(device_id),)) or {"id": int(device_id)}


def delete_camera_device(device_id: int) -> None:
    row = fetchone("SELECT source FROM camera_devices WHERE id=?", (int(device_id),))
    if not row:
        raise ValueError("Không tìm thấy camera")
    if str(row.get("source") or "") == str(camera_settings().get("source") or "0"):
        raise ValueError("Không thể xóa camera đang hoạt động")
    execute("DELETE FROM camera_devices WHERE id=?", (int(device_id),))


def _safe_snapshot_path(raw: str) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = DATA_ROOT / candidate
    try:
        resolved = candidate.resolve()
        root = DATA_ROOT.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        return resolved
    except Exception:
        return None


def persist_recognition_evidence(event_id: int, data_url: str) -> str:
    raw = str(data_url or "").strip()
    if not raw:
        return ""
    try:
        payload = raw.split(",", 1)[1] if raw.startswith("data:") and "," in raw else raw
        blob = base64.b64decode(payload, validate=False)
    except Exception:
        return ""
    if not blob or len(blob) > 8 * 1024 * 1024:
        return ""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = EVENT_SNAPSHOTS_DIR / "Recognition" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"event_{int(event_id)}.jpg"
    path.write_bytes(blob)
    relative = str(path.relative_to(DATA_ROOT)).replace("\\", "/")
    row = fetchone("SELECT detail_json FROM recognition_events WHERE id=?", (int(event_id),)) or {}
    detail = _json_obj(row.get("detail_json"))
    detail.pop("best_snapshot", None)
    detail["snapshot_path"] = relative
    execute("UPDATE recognition_events SET detail_json=? WHERE id=?", (json.dumps(detail, ensure_ascii=False), int(event_id)))
    return relative


def recognition_evidence_path(event_id: int) -> Path | None:
    row = fetchone("SELECT detail_json FROM recognition_events WHERE id=?", (int(event_id),))
    if not row:
        return None
    detail = _json_obj(row.get("detail_json"))
    return _safe_snapshot_path(str(detail.get("snapshot_path") or ""))


def _exception_center(detail: dict[str, Any]) -> tuple[float, float] | None:
    """Normalized face/person center used only to reconnect short tracker-ID churn."""
    box = detail.get("bbox") or detail.get("face_bbox")
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return None
    try:
        x, y, w, h = [float(v) for v in box[:4]]
        fw = float(detail.get("frame_width") or 0.0)
        fh = float(detail.get("frame_height") or 0.0)
        if fw <= 1.0 or fh <= 1.0 or w <= 0.0 or h <= 0.0:
            return None
        return ((x + w * 0.5) / fw, (y + h * 0.5) / fh)
    except Exception:
        return None


def _exception_kind(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").upper()
    if status == "SPOOF_BLOCKED":
        return "SPOOF"
    if status == "UNREGISTERED":
        return "UNKNOWN"
    return "LOW_CONFIDENCE"


def _verification_cases(*, pool: int = 5000) -> list[dict[str, Any]]:
    """Collapse raw FaceID/PAD observations into human-review cases.

    Professional operations UIs count *open cases*, not detector observations. A
    person who stays in front of one camera for several minutes therefore remains
    one case even when the tracker ID changes briefly or PAD/FaceID re-evaluates the
    same physical face many times.
    """
    rules = operations_rules()
    threshold = float(rules["exception_low_confidence"])
    gap_sec = max(120.0, float(rules.get("reentry_gap_minutes") or 10) * 60.0)
    rows = fetchall(
        """SELECT re.id,re.student_id,re.track_id,re.camera_source,re.confidence,re.liveness_score,re.anti_spoof_passed,re.status,re.event_at,re.detail_json,
        s.student_code,s.full_name,s.class_name,s.faculty,
        er.decision,er.resolved_student_id,er.reviewed_by,er.note,er.reviewed_at,rs.student_code AS resolved_student_code,rs.full_name AS resolved_full_name
        FROM recognition_events re
        LEFT JOIN students s ON s.id=re.student_id
        LEFT JOIN exception_reviews er ON er.event_id=re.id
        LEFT JOIN students rs ON rs.id=er.resolved_student_id
        WHERE (re.status IN ('UNREGISTERED','SPOOF_BLOCKED') OR (re.status='RECOGNIZED' AND re.confidence<?))
        ORDER BY re.id DESC LIMIT ?""",
        (threshold, max(200, min(10000, int(pool)))),
    )
    rows.reverse()
    cases: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        detail = _json_obj(row.pop("detail_json", "{}"))
        row["detail"] = detail
        row["reason"] = str(detail.get("reason") or (detail.get("liveness") or {}).get("reason") or "")
        row["snapshot_url"] = f"/api/v1/events/{int(row['id'])}/evidence.jpg" if detail.get("snapshot_path") else str(detail.get("best_snapshot") or "")
        row["decision"] = str(row.get("decision") or "PENDING").upper()
        row_dt = None
        try:
            row_dt = _parse_iso(str(row.get("event_at") or ""))
        except Exception:
            pass
        center = _exception_center(detail)
        camera = str(row.get("camera_source") or "")
        sid = int(row["student_id"]) if row.get("student_id") is not None else None
        tid = str(row.get("track_id") or "")
        kind = _exception_kind(row)

        match = None
        best_score = -1.0
        for case in reversed(active):
            last_dt = case.get("_last_dt")
            if row_dt is not None and last_dt is not None:
                age = (row_dt - last_dt).total_seconds()
                if age < 0 or age > gap_sec:
                    continue
            if str(case.get("camera_source") or "") != camera:
                continue
            case_sid = case.get("student_id")
            if sid is not None or case_sid is not None:
                if sid is None or case_sid is None or int(case_sid) != int(sid):
                    continue
                score = 10.0
            else:
                score = 0.0
                case_tid = str(case.get("_last_track_id") or "")
                if tid and case_tid and tid == case_tid:
                    score += 5.0
                c0 = case.get("_last_center")
                if center is not None and c0 is not None:
                    dx = float(center[0]) - float(c0[0])
                    dy = float(center[1]) - float(c0[1])
                    dist = (dx * dx + dy * dy) ** 0.5
                    # A generous threshold reconnects a face that turns/moves a little,
                    # while still keeping two people on opposite sides of the room apart.
                    if dist <= 0.28:
                        score += max(0.0, 4.0 - dist * 10.0)
                    else:
                        continue
                elif not tid or not case_tid:
                    # Old rows may not contain bbox metadata. Only merge into the most
                    # recent same-camera unknown case when temporal continuity is strong.
                    if row_dt is not None and last_dt is not None and (row_dt - last_dt).total_seconds() <= 60.0:
                        score += 1.0
                    else:
                        continue
            if score > best_score:
                best_score = score
                match = case

        if match is None:
            match = {
                **row,
                "case_id": f"VC-{int(row.get('id') or 0)}",
                "event_ids": [int(row.get("id") or 0)],
                "first_seen": str(row.get("event_at") or ""),
                "last_seen": str(row.get("event_at") or ""),
                "repeat_count": 1,
                "case_kind": kind,
                "_last_dt": row_dt,
                "_last_center": center,
                "_last_track_id": tid,
                "_decisions": [row["decision"]],
            }
            cases.append(match)
            active.append(match)
        else:
            match["event_ids"].append(int(row.get("id") or 0))
            match["last_seen"] = str(row.get("event_at") or match.get("last_seen") or "")
            match["repeat_count"] = int(match.get("repeat_count") or 1) + 1
            match["_last_dt"] = row_dt or match.get("_last_dt")
            match["_last_center"] = center or match.get("_last_center")
            match["_last_track_id"] = tid or match.get("_last_track_id")
            match["_decisions"].append(row["decision"])
            # Keep the newest observation metadata/evidence, but preserve case identity.
            for key in ("id","track_id","confidence","liveness_score","anti_spoof_passed","status","event_at","reason","snapshot_url","detail","resolved_student_id","reviewed_by","note","reviewed_at","resolved_student_code","resolved_full_name"):
                if row.get(key) not in (None, ""):
                    match[key] = row.get(key)
            if kind == "SPOOF":
                match["case_kind"] = "SPOOF"
                match["status"] = "SPOOF_BLOCKED"
            elif match.get("case_kind") != "SPOOF" and kind == "UNKNOWN":
                match["case_kind"] = "UNKNOWN"
                match["status"] = "UNREGISTERED"

        # Prune stale active cases to keep grouping O(n) small on long databases.
        if row_dt is not None and len(active) > 20:
            active[:] = [c for c in active if c.get("_last_dt") is None or (row_dt - c["_last_dt"]).total_seconds() <= gap_sec]

    for case in cases:
        decisions = [str(x or "PENDING").upper() for x in case.pop("_decisions", [])]
        # Any unresolved member means the human-review case is still open.
        case["decision"] = "PENDING" if any(x == "PENDING" for x in decisions) else (decisions[-1] if decisions else "PENDING")
        case["observation_count"] = int(case.get("repeat_count") or 1)
        case.pop("_last_dt", None)
        case.pop("_last_center", None)
        case.pop("_last_track_id", None)
    cases.sort(key=lambda x: str(x.get("last_seen") or x.get("event_at") or ""), reverse=True)
    return cases


def exception_queue(limit: int = 80, decision: str = "PENDING") -> list[dict]:
    wanted = str(decision or "PENDING").strip().upper()
    cases = _verification_cases(pool=max(1000, int(limit) * 30))
    out = [x for x in cases if not wanted or str(x.get("decision") or "PENDING").upper() == wanted]
    return out[:max(1, min(500, int(limit)))]


def review_exception(event_id: int, decision: str, resolved_student_id: int | None, reviewer: str, note: str = "") -> dict:
    event = fetchone("SELECT id,status,student_id,anti_spoof_passed FROM recognition_events WHERE id=?", (int(event_id),))
    if not event:
        raise ValueError("Không tìm thấy sự kiện nhận diện")
    clean = str(decision or "").strip().upper()
    allowed = {"CONFIRMED_IDENTITY", "MARKED_UNKNOWN", "DISMISSED", "PENDING"}
    if clean not in allowed:
        raise ValueError("Quyết định xác minh không hợp lệ")
    if clean == "CONFIRMED_IDENTITY":
        if not resolved_student_id or not fetchone("SELECT id FROM students WHERE id=?", (int(resolved_student_id),)):
            raise ValueError("Cần chọn nhân viên để xác nhận danh tính")
    else:
        resolved_student_id = None

    # Review the whole aggregated case, not only the representative raw event.
    member_ids = [int(event_id)]
    for case in _verification_cases(pool=10000):
        ids = [int(x) for x in (case.get("event_ids") or [])]
        if int(event_id) in ids:
            member_ids = ids or member_ids
            break
    now = utc_now()
    reviewed_at = None if clean == "PENDING" else now
    actor = str(reviewer or "operator")[:120]
    clean_note = str(note or "")[:1000]
    with connection() as conn:
        for eid in member_ids:
            existing = conn.execute("SELECT id FROM exception_reviews WHERE event_id=?", (int(eid),)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE exception_reviews SET decision=?,resolved_student_id=?,reviewed_by=?,note=?,reviewed_at=?,updated_at=? WHERE event_id=?""",
                    (clean, resolved_student_id, actor, clean_note, reviewed_at, now, int(eid)),
                )
            else:
                conn.execute(
                    """INSERT INTO exception_reviews(event_id,decision,resolved_student_id,reviewed_by,note,reviewed_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (int(eid), clean, resolved_student_id, actor, clean_note, reviewed_at, now, now),
                )
    result = fetchone(
        """SELECT er.*,s.student_code AS resolved_student_code,s.full_name AS resolved_full_name
        FROM exception_reviews er LEFT JOIN students s ON s.id=er.resolved_student_id WHERE er.event_id=?""",
        (int(event_id),),
    ) or {"event_id": int(event_id), "decision": clean}
    result["case_event_count"] = len(member_ids)
    result["case_event_ids"] = member_ids
    return result


def persist_hr_evidence(event_id: int, image: bytes | str) -> str:
    """Persist one full-scene snapshot for a meaningful HR business event."""
    if not event_id or not image:
        return ""
    if isinstance(image, (bytes, bytearray)):
        blob = bytes(image)
    else:
        raw = str(image or "").strip()
        try:
            payload = raw.split(",", 1)[1] if raw.startswith("data:") and "," in raw else raw
            blob = base64.b64decode(payload, validate=False)
        except Exception:
            return ""
    if not blob or len(blob) > 12 * 1024 * 1024:
        return ""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = EVENT_SNAPSHOTS_DIR / "HR" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"event_{int(event_id)}.jpg"
    path.write_bytes(blob)
    relative = str(path.relative_to(DATA_ROOT)).replace("\\", "/")
    row = fetchone("SELECT detail_json FROM hr_events WHERE id=?", (int(event_id),)) or {}
    detail = _json_obj(row.get("detail_json"))
    detail.pop("best_snapshot", None)
    detail["snapshot_path"] = relative
    execute("UPDATE hr_events SET detail_json=? WHERE id=?", (json.dumps(detail, ensure_ascii=False), int(event_id)))
    return relative


def hr_event_evidence_path(event_id: int) -> Path | None:
    """Return the HR snapshot; old events may reuse nearby FaceID evidence safely."""
    row = fetchone("SELECT student_id,event_at,detail_json FROM hr_events WHERE id=?", (int(event_id),))
    if not row:
        return None
    detail = _json_obj(row.get("detail_json"))
    direct = _safe_snapshot_path(str(detail.get("snapshot_path") or ""))
    if direct and direct.exists():
        return direct
    sid = row.get("student_id")
    if sid is None:
        return None
    try:
        target = _parse_iso(str(row.get("event_at") or ""))
    except Exception:
        target = None
    nearest: tuple[float, Path] | None = None
    for rec in fetchall("SELECT id,event_at,detail_json FROM recognition_events WHERE student_id=? ORDER BY id DESC LIMIT 80", (int(sid),)):
        rd = _json_obj(rec.get("detail_json"))
        candidate = _safe_snapshot_path(str(rd.get("snapshot_path") or ""))
        if not candidate or not candidate.exists():
            continue
        if target is None:
            return candidate
        try:
            delta = abs((_parse_iso(str(rec.get("event_at") or "")) - target).total_seconds())
        except Exception:
            continue
        if delta <= 900.0 and (nearest is None or delta < nearest[0]):
            nearest = (delta, candidate)
    return nearest[1] if nearest else None


def cleanup_old_hr_evidence(retention_days: int | None = None) -> dict:
    days = int(retention_days or operations_rules()["evidence_retention_days"])
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, days) * 86400
    root = EVENT_SNAPSHOTS_DIR / "HR"
    removed = 0
    kept = 0
    if root.exists():
        for path in root.rglob("*.jpg"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
                else:
                    kept += 1
            except OSError:
                pass
    return {"retention_days": days, "removed": removed, "kept": kept}

def cleanup_old_recognition_evidence(retention_days: int | None = None) -> dict:
    days = int(retention_days or operations_rules()["evidence_retention_days"])
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, days) * 86400
    root = EVENT_SNAPSHOTS_DIR / "Recognition"
    removed = 0
    kept = 0
    if root.exists():
        for path in root.rglob("*.jpg"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
                else:
                    kept += 1
            except OSError:
                pass
    return {"retention_days": days, "removed": removed, "kept": kept}


def operations_summary() -> dict:
    recognition_cleanup = cleanup_old_recognition_evidence()
    hr_cleanup = cleanup_old_hr_evidence()
    # V2.9: the badge is a count of open HUMAN-REVIEW CASES, never raw AI observations.
    pending = sum(1 for x in _verification_cases(pool=10000) if str(x.get("decision") or "PENDING").upper() == "PENDING")
    devices = list_camera_devices()
    active_sessions = int((fetchone("SELECT COUNT(*) n FROM attendance_sessions WHERE status!='CLOSED' AND start_at<=? AND end_at>=?", (utc_now(), utc_now())) or {}).get("n") or 0)
    return {"pending_exceptions": pending, "camera_devices": len(devices), "enabled_devices": sum(1 for d in devices if d.get("enabled")), "active_sessions": active_sessions, "rules": operations_rules(), "evidence_cleanup": {"recognition": recognition_cleanup, "hr": hr_cleanup}}

def validate_backup(path: Path) -> dict:
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        if "manifest.json" not in names:
            raise ValueError("Backup thiếu manifest")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        mode = str(manifest.get("database_mode") or ("sqlite" if "recognition_module.db" in names else "postgres"))
        if mode == "postgres":
            dump_name = str(manifest.get("database") or "campusface.dump")
            if dump_name not in names:
                raise ValueError("Backup PostgreSQL thiếu database dump")
            with tempfile.TemporaryDirectory(prefix="campusface-validate-") as td:
                dump = Path(td) / "campusface.dump"
                dump.write_bytes(zf.read(dump_name))
                cp = subprocess.run([str(_pg_tool("pg_restore")), "--list", str(dump)], capture_output=True, text=True, timeout=60)
                if cp.returncode != 0:
                    raise ValueError("PostgreSQL backup không hợp lệ")
                listing = cp.stdout.lower()
                for table in ("students", "face_templates", "recognition_events"):
                    if table not in listing:
                        raise ValueError(f"Backup thiếu bảng {table}")
        else:
            if "recognition_module.db" not in names:
                raise ValueError("Backup SQLite thiếu database")
            with tempfile.TemporaryDirectory(prefix="campusface-validate-") as td:
                dbp = Path(td) / "db.sqlite"
                dbp.write_bytes(zf.read("recognition_module.db"))
                conn = sqlite3.connect(dbp)
                try:
                    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                finally:
                    conn.close()
            required = {"students", "face_templates", "recognition_events"}
            if not required.issubset(tables):
                raise ValueError("Backup không đúng định dạng CampusFace")
    return manifest


def restore_backup(name: str) -> dict:
    path = backup_path(name)
    manifest = validate_backup(path)
    mode = str(manifest.get("database_mode") or "sqlite")
    if DB_MODE != mode:
        raise ValueError(f"Backup {mode} không thể restore trực tiếp vào database {DB_MODE}. Hãy dùng công cụ migration.")
    emergency = create_backup("before-restore")
    with tempfile.TemporaryDirectory(prefix="campusface-restore-") as td:
        temp = Path(td)
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(temp)
        if DB_MODE == "postgres":
            dump = temp / str(manifest.get("database") or "campusface.dump")
            cmd = [str(_pg_tool("pg_restore")), *_pg_common_args(), "--dbname", POSTGRES_DB,
                   "--clean", "--if-exists", "--no-owner", "--no-privileges", "--exit-on-error", str(dump)]
            cp = subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True, timeout=240)
            if cp.returncode != 0:
                raise RuntimeError(f"pg_restore thất bại: {(cp.stderr or cp.stdout).strip()}")
        else:
            replacement = temp / "recognition_module.db"
            SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
            staged = SQLITE_PATH.with_suffix(".restore.tmp")
            shutil.copy2(replacement, staged)
            for suffix in ("-wal", "-shm"):
                try:
                    Path(str(SQLITE_PATH) + suffix).unlink(missing_ok=True)
                except Exception:
                    pass
            os.replace(staged, SQLITE_PATH)
        if (temp / "face_templates.key").exists():
            shutil.copy2(temp / "face_templates.key", KEY_PATH)
        if (temp / "Photos").exists():
            if PHOTOS_DIR.exists():
                shutil.rmtree(PHOTOS_DIR, ignore_errors=True)
            shutil.copytree(temp / "Photos", PHOTOS_DIR)
        if (temp / "Snapshots").exists():
            if EVENT_SNAPSHOTS_DIR.exists():
                shutil.rmtree(EVENT_SNAPSHOTS_DIR, ignore_errors=True)
            shutil.copytree(temp / "Snapshots", EVENT_SNAPSHOTS_DIR)
        # Restore only JSON operational policies. module.env / protected secrets are
        # intentionally left untouched so a restore cannot disconnect PostgreSQL.
        if (temp / "Config").exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            for cfg_file in (temp / "Config").glob("*.json"):
                try:
                    shutil.copy2(cfg_file, CONFIG_DIR / cfg_file.name)
                except OSError:
                    pass
        # Preserve the current DB/secret configuration. Camera settings can be restored
        # manually from module.env if required; replacing it here could disconnect DB.
    ensure_production_schema()
    return {"ok": True, "restored": path.name, "manifest": manifest, "emergency_backup": emergency["name"], "restart_required": True}


def storage_status() -> dict:
    usage = shutil.disk_usage(DATA_ROOT)
    if DB_MODE == "postgres":
        row = fetchone("SELECT pg_database_size(current_database()) AS db_size") or {"db_size": 0}
        db_size = int(row.get("db_size") or 0)
        db_path = f"postgresql://{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    else:
        db_size = SQLITE_PATH.stat().st_size if SQLITE_PATH.exists() else 0
        db_path = str(SQLITE_PATH)
    backups = list_backups()
    def _tree_size(root: Path) -> int:
        total = 0
        if root.exists():
            for item in root.rglob("*"):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        pass
        return total
    photos_size = _tree_size(PHOTOS_DIR)
    snapshots_size = _tree_size(EVENT_SNAPSHOTS_DIR)
    return {
        "data_root": str(DATA_ROOT),
        "db_mode": DB_MODE,
        "db_path": db_path,
        "db_size": db_size,
        "photos_size": photos_size,
        "snapshots_size": snapshots_size,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "backup_count": len(backups),
        "last_backup_at": backups[0]["created_at"] if backups else None,
    }

