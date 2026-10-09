from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .config import (
    DB_MODE,
    PG_SECRET_PATH,
    POSTGRES_CONNECT_TIMEOUT,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_SSLMODE,
    POSTGRES_USER,
    SQLITE_PATH,
)
from .secret_store import load_secret


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _postgres_password() -> str:
    return load_secret(PG_SECRET_PATH, os.getenv("CAMPUSFACE_POSTGRES_PASSWORD", "").strip())


def _qmark_to_pyformat(sql: str) -> str:
    # Project SQL doesn't use '?' inside string literals. Keeping this translator
    # narrow avoids rewriting the rest of the application during the PostgreSQL move.
    return sql.replace("?", "%s")


def _translate_postgres_sql(sql: str) -> str:
    s = sql.strip()
    s = re.sub(r"^INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", s, flags=re.I)
    if re.match(r"^INSERT\s+INTO\s+attendance_records\b", s, flags=re.I) and "ON CONFLICT" not in s.upper():
        s = s.rstrip().rstrip(";") + " ON CONFLICT (session_id, student_id) DO NOTHING"
    return _qmark_to_pyformat(s)


class _CompatConnection:
    def __init__(self, raw, mode: str):
        self.raw = raw
        self.mode = mode

    def execute(self, sql: str, params: Iterable[Any] = ()):
        if self.mode == "postgres":
            return self.raw.execute(_translate_postgres_sql(sql), tuple(params))
        return self.raw.execute(sql, tuple(params))

    def executescript(self, script: str) -> None:
        if self.mode == "sqlite":
            self.raw.executescript(script)
            return
        # Schemas in this project contain simple DDL statements only.
        for statement in [part.strip() for part in script.split(";") if part.strip()]:
            self.raw.execute(statement)

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()


@contextmanager
def connection():
    if DB_MODE == "sqlite":
        conn = sqlite3.connect(SQLITE_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        wrapped = _CompatConnection(conn, "sqlite")
    else:
        password = _postgres_password()
        if not password:
            raise RuntimeError(
                "PostgreSQL credential is missing. Run SETUP_POSTGRESQL_WINDOWS.bat "
                "or set CAMPUSFACE_POSTGRES_PASSWORD for maintenance/testing."
            )
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:
            raise RuntimeError("psycopg is not installed; reinstall requirements-runtime.txt") from exc
        conn = psycopg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=password,
            sslmode=POSTGRES_SSLMODE,
            connect_timeout=POSTGRES_CONNECT_TIMEOUT,
            row_factory=dict_row,
            application_name="CampusFace",
        )
        wrapped = _CompatConnection(conn, "postgres")
    try:
        yield wrapped
        wrapped.commit()
    except Exception:
        wrapped.rollback()
        raise
    finally:
        wrapped.close()


# Some PostgreSQL tables intentionally use a natural/composite primary key and
# therefore do not expose an ``id`` column.  ``execute()`` historically added
# ``RETURNING id`` to every INSERT, which breaks those tables.  Keep the
# generated-id behavior for entity tables while explicitly bypassing it for
# key/value tables used during startup.
_POSTGRES_INSERTS_WITHOUT_ID = {"runtime_settings"}


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with connection() as conn:
        if DB_MODE == "postgres" and re.match(r"^\s*INSERT\s+INTO\s+", sql, flags=re.I):
            translated = _translate_postgres_sql(sql).rstrip().rstrip(";")
            table_match = re.match(r"^\s*INSERT\s+INTO\s+([A-Za-z0-9_]+)", translated, flags=re.I)
            table_name = str(table_match.group(1) if table_match else "").lower()
            if (
                table_name not in _POSTGRES_INSERTS_WITHOUT_ID
                and " RETURNING " not in translated.upper()
                and "ON CONFLICT" not in translated.upper()
            ):
                translated += " RETURNING id"
                cur = conn.raw.execute(translated, tuple(params))
                row = cur.fetchone()
                return int(row["id"] if isinstance(row, dict) else row[0]) if row else 0
        cur = conn.execute(sql, tuple(params))
        if DB_MODE == "sqlite":
            return int(cur.lastrowid or cur.rowcount or 0)
        return int(cur.rowcount or 0)


def fetchone(sql: str, params: Iterable[Any] = ()) -> dict | None:
    with connection() as conn:
        rec = conn.execute(sql, tuple(params)).fetchone()
        return dict(rec) if rec is not None else None


def fetchall(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with connection() as conn:
        return [dict(x) for x in conn.execute(sql, tuple(params)).fetchall()]


def _base_schema() -> str:
    if DB_MODE == "postgres":
        return """
        CREATE TABLE IF NOT EXISTS students (
            id BIGSERIAL PRIMARY KEY,
            student_code TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            class_name TEXT DEFAULT '',
            faculty TEXT DEFAULT '',
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            consent_at TEXT NOT NULL,
            biometric_consent_status TEXT NOT NULL DEFAULT 'NOT_GRANTED',
            biometric_consent_at TEXT,
            biometric_consent_withdrawn_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS face_templates (
            id BIGSERIAL PRIMARY KEY,
            student_id BIGINT NOT NULL UNIQUE,
            embedding_blob BYTEA NOT NULL,
            pose_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS recognition_events (
            id BIGSERIAL PRIMARY KEY,
            student_id BIGINT,
            track_id TEXT NOT NULL DEFAULT '',
            camera_source TEXT NOT NULL DEFAULT 'static-camera',
            direction TEXT NOT NULL DEFAULT 'IN',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            liveness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            anti_spoof_passed INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'RECOGNIZED',
            event_at TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recognition_events_time ON recognition_events(event_at DESC);
        CREATE INDEX IF NOT EXISTS idx_recognition_events_student ON recognition_events(student_id, event_at DESC);
        CREATE TABLE IF NOT EXISTS classroom_events (
            id BIGSERIAL PRIMARY KEY,
            student_id BIGINT,
            track_id TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            event_at TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_classroom_events_time ON classroom_events(event_at DESC);
        CREATE INDEX IF NOT EXISTS idx_classroom_events_student ON classroom_events(student_id, event_at DESC);
        CREATE TABLE IF NOT EXISTS audit_events (
            id BIGSERIAL PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'SYSTEM',
            event_type TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'INFO',
            student_id BIGINT,
            camera_source TEXT NOT NULL DEFAULT '',
            event_at TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_events_time ON audit_events(event_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_events_category ON audit_events(category, event_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_events_student ON audit_events(student_id, event_at DESC);
        CREATE TABLE IF NOT EXISTS office_crossing_events (
            id BIGSERIAL PRIMARY KEY,
            student_id BIGINT,
            track_id TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL DEFAULT 'IN',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            camera_source TEXT NOT NULL DEFAULT '',
            line_name TEXT NOT NULL DEFAULT 'Cửa văn phòng',
            event_at TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_office_crossing_time ON office_crossing_events(event_at DESC);
        CREATE INDEX IF NOT EXISTS idx_office_crossing_student ON office_crossing_events(student_id, event_at DESC);
        CREATE TABLE IF NOT EXISTS hr_presence_sessions (
            id BIGSERIAL PRIMARY KEY,
            student_id BIGINT NOT NULL,
            track_id TEXT NOT NULL DEFAULT '',
            camera_source TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            ended_at TEXT,
            duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            start_reason TEXT NOT NULL DEFAULT 'CAMERA_SEEN',
            end_reason TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_hr_presence_student ON hr_presence_sessions(student_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hr_presence_status ON hr_presence_sessions(status, last_seen_at DESC);
        CREATE TABLE IF NOT EXISTS hr_events (
            id BIGSERIAL PRIMARY KEY,
            student_id BIGINT,
            track_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'INFO',
            camera_source TEXT NOT NULL DEFAULT '',
            event_at TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hr_events_time ON hr_events(event_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hr_events_student ON hr_events(student_id, event_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hr_events_type ON hr_events(event_type, event_at DESC);
        """
    return """
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_code TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL,
        class_name TEXT DEFAULT '',
        faculty TEXT DEFAULT '',
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        consent_at TEXT NOT NULL,
        biometric_consent_status TEXT NOT NULL DEFAULT 'NOT_GRANTED',
        biometric_consent_at TEXT,
        biometric_consent_withdrawn_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS face_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL UNIQUE,
        embedding_blob BLOB NOT NULL,
        pose_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS recognition_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        track_id TEXT NOT NULL DEFAULT '',
        camera_source TEXT NOT NULL DEFAULT 'static-camera',
        direction TEXT NOT NULL DEFAULT 'IN',
        confidence REAL NOT NULL DEFAULT 0,
        liveness_score REAL NOT NULL DEFAULT 0,
        anti_spoof_passed INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'RECOGNIZED',
        event_at TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_recognition_events_time ON recognition_events(event_at DESC);
    CREATE INDEX IF NOT EXISTS idx_recognition_events_student ON recognition_events(student_id, event_at DESC);
    CREATE TABLE IF NOT EXISTS classroom_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        track_id TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL DEFAULT '',
        confidence REAL NOT NULL DEFAULT 0,
        event_at TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_classroom_events_time ON classroom_events(event_at DESC);
    CREATE INDEX IF NOT EXISTS idx_classroom_events_student ON classroom_events(student_id, event_at DESC);
    CREATE TABLE IF NOT EXISTS audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL DEFAULT 'SYSTEM',
        event_type TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'INFO',
        student_id INTEGER,
        camera_source TEXT NOT NULL DEFAULT '',
        event_at TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_audit_events_time ON audit_events(event_at DESC);
    CREATE INDEX IF NOT EXISTS idx_audit_events_category ON audit_events(category, event_at DESC);
    CREATE INDEX IF NOT EXISTS idx_audit_events_student ON audit_events(student_id, event_at DESC);
    CREATE TABLE IF NOT EXISTS office_crossing_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        track_id TEXT NOT NULL DEFAULT '',
        direction TEXT NOT NULL DEFAULT 'IN',
        confidence REAL NOT NULL DEFAULT 0,
        camera_source TEXT NOT NULL DEFAULT '',
        line_name TEXT NOT NULL DEFAULT 'Cửa văn phòng',
        event_at TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_office_crossing_time ON office_crossing_events(event_at DESC);
    CREATE INDEX IF NOT EXISTS idx_office_crossing_student ON office_crossing_events(student_id, event_at DESC);
    CREATE TABLE IF NOT EXISTS hr_presence_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        track_id TEXT NOT NULL DEFAULT '',
        camera_source TEXT NOT NULL DEFAULT '',
        started_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        ended_at TEXT,
        duration_sec REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'OPEN',
        start_reason TEXT NOT NULL DEFAULT 'CAMERA_SEEN',
        end_reason TEXT NOT NULL DEFAULT '',
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_hr_presence_student ON hr_presence_sessions(student_id, started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_hr_presence_status ON hr_presence_sessions(status, last_seen_at DESC);
    CREATE TABLE IF NOT EXISTS hr_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        track_id TEXT NOT NULL DEFAULT '',
        event_type TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'INFO',
        camera_source TEXT NOT NULL DEFAULT '',
        event_at TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_hr_events_time ON hr_events(event_at DESC);
    CREATE INDEX IF NOT EXISTS idx_hr_events_student ON hr_events(student_id, event_at DESC);
    CREATE INDEX IF NOT EXISTS idx_hr_events_type ON hr_events(event_type, event_at DESC);
    """


def init_db() -> None:
    with connection() as conn:
        conn.executescript(_base_schema())


def db_status() -> dict:
    if DB_MODE == "sqlite":
        return {"mode": "sqlite", "path": str(SQLITE_PATH), "offline": True, "production": False}
    info = fetchone("SELECT current_database() AS database, current_user AS db_user, version() AS version") or {}
    return {
        "mode": "postgres",
        "host": POSTGRES_HOST,
        "port": POSTGRES_PORT,
        "database": info.get("database", POSTGRES_DB),
        "db_user": info.get("db_user", POSTGRES_USER),
        "offline": True,
        "local_only": POSTGRES_HOST in {"127.0.0.1", "localhost", "::1"},
        "version": str(info.get("version") or "").split(",")[0],
        "secret_store": "Windows DPAPI" if PG_SECRET_PATH.exists() else "environment",
    }


def _parse_event_time(value: str) -> datetime | None:
    try:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None



def _safe_detail(raw: Any) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        return json.loads(str(raw or "{}")) or {}
    except Exception:
        return {}


def _normalized_event_bbox(detail: dict) -> tuple[float, float, float, float] | None:
    """Return a normalized face bbox for short-lived recognition event grouping.

    Tracker IDs can change when a face turns away for a moment.  A normalized bbox
    gives the event layer a second continuity signal without persisting raw images or
    adding a new biometric identifier.  The value is only used for local dedup.
    """
    try:
        box = detail.get("bbox") or detail.get("face_bbox")
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            return None
        x, y, w, h = [float(v) for v in box[:4]]
        fw = float(detail.get("frame_width") or 0.0)
        fh = float(detail.get("frame_height") or 0.0)
        if max(abs(x), abs(y), abs(w), abs(h)) <= 1.5:
            nx, ny, nw, nh = x, y, w, h
        elif fw > 1.0 and fh > 1.0:
            nx, ny, nw, nh = x / fw, y / fh, w / fw, h / fh
        else:
            return None
        if nw <= 0.0 or nh <= 0.0:
            return None
        return (
            max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny)),
            max(0.001, min(1.0, nw)), max(0.001, min(1.0, nh)),
        )
    except Exception:
        return None


def _bbox_episode_match(a: tuple[float, float, float, float] | None, b: tuple[float, float, float, float] | None) -> bool:
    if not a or not b:
        return False
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    acx, acy = ax + aw * 0.5, ay + ah * 0.5
    bcx, bcy = bx + bw * 0.5, by + bh * 0.5
    center_dist = ((acx-bcx)**2 + (acy-bcy)**2) ** 0.5
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax+aw, bx+bw), min(ay+ah, by+bh)
    inter = max(0.0, x2-x1) * max(0.0, y2-y1)
    union = aw*ah + bw*bh - inter
    iou = inter / union if union > 0 else 0.0
    size_ratio = min(aw*ah, bw*bh) / max(1e-6, max(aw*ah, bw*bh))
    # A short detector miss often creates a new tracker a few pixels away.  Accept
    # either a modest overlap or a nearby centre with broadly similar face size.
    return bool(iou >= 0.055 or (center_dist <= 0.24 and size_ratio >= 0.38))


def _event_attribution() -> dict:
    from .demo_context import event_attribution
    return event_attribution()


def _appearance_classification(**values):
    from .camera_appearances import persist_classification
    return persist_classification(**values)


def _insert_recognition(values: tuple, attribution: dict) -> int:
    # Unattributed callers keep the legacy schema/API path. New background camera
    # callers carry a frame-time snapshot and require the additive startup migration.
    columns = "student_id,track_id,camera_source,direction,confidence,liveness_score,anti_spoof_passed,status,event_at,detail_json,created_at"
    if attribution.get("camera_id") is not None:
        columns += ",camera_id,store_id,zone_name,store_name,camera_name"
        values += tuple(attribution.get(key) for key in ("camera_id", "store_id", "zone_name", "store_name", "camera_name"))
    placeholders = ",".join("?" for _ in values)
    return execute(f"INSERT INTO recognition_events({columns}) VALUES({placeholders})", values)


def _recent_recognition_episode(
    status: str,
    source: str,
    now: str,
    window_sec: float,
    *,
    detail: dict | None = None,
    student_id: int | None = None,
    track_id: str = "",
    fallback_single_sec: float = 45.0,
) -> dict | None:
    if window_sec <= 0:
        return None
    attribution = _event_attribution()
    if attribution.get("camera_id") is not None:
        predicate = "camera_id=? AND " + ("store_id=?" if attribution.get("store_id") is not None else "store_id IS NULL")
        params = (attribution["camera_id"],) + ((attribution["store_id"],) if attribution.get("store_id") is not None else ())
        extra_columns = ",camera_id,store_id,zone_name,store_name,camera_name"
    else:
        predicate, params, extra_columns = "camera_source=?", (source,), ""
    rows = fetchall(
        "SELECT id,student_id,track_id,event_at,detail_json,confidence,liveness_score,status" + extra_columns +
        " FROM recognition_events WHERE " + predicate + " AND status=? ORDER BY id DESC LIMIT 24",
        params + (str(status).upper(),),
    )
    cur_at = _parse_event_time(now)
    if not cur_at:
        return None
    current_box = _normalized_event_bbox(detail or {})
    recent: list[tuple[dict, float]] = []
    exact_track = str(track_id or "").strip()
    for row in rows:
        prev_at = _parse_event_time(str(row.get("event_at") or ""))
        if not prev_at:
            continue
        gap = (cur_at - prev_at).total_seconds()
        if gap < 0.0 or gap > float(window_sec):
            continue
        if student_id is not None and int(row.get("student_id") or -1) != int(student_id):
            continue
        recent.append((row, gap))
        if exact_track and str(row.get("track_id") or "") == exact_track:
            return row
        previous_box = _normalized_event_bbox(_safe_detail(row.get("detail_json")))
        if _bbox_episode_match(current_box, previous_box):
            return row
    # Legacy V2.6 rows did not always include bbox metadata. If exactly one episode
    # is active on this camera, tracker churn within a short grace window is still
    # treated as the same physical presence instead of generating a new DB row.
    if len(recent) == 1 and recent[0][1] <= max(1.0, float(fallback_single_sec)):
        legacy_box = _normalized_event_bbox(_safe_detail(recent[0][0].get("detail_json")))
        # Only use the camera-level fallback when at least one side lacks spatial
        # metadata (legacy rows). If both bboxes are known and far apart, they are
        # allowed to become two simultaneous unknown/security episodes.
        if current_box is None or legacy_box is None:
            return recent[0][0]
    return None


def _aggregation_payload(previous_detail: dict, current_detail: dict, now: str, *, promoted_from: str = "") -> dict:
    merged = dict(previous_detail or {})
    # Preserve the first best-shot/evidence references, while allowing fresh quality,
    # pose and reason metadata to improve the diagnostic payload.
    for key, value in dict(current_detail or {}).items():
        if key in {"best_snapshot", "snapshot_path"} and merged.get(key):
            continue
        merged[key] = value
    agg = dict(merged.get("aggregation") or {})
    first_seen = str(agg.get("first_seen") or merged.get("first_seen") or now)
    repeat_count = int(agg.get("repeat_count") or 1) + 1
    agg.update({
        "first_seen": first_seen,
        "last_seen": now,
        "repeat_count": repeat_count,
        "policy": "TRACK_IDENTITY_EPISODE_V27",
    })
    if promoted_from:
        agg["promoted_from"] = str(promoted_from)
    merged["aggregation"] = agg
    return merged


def _new_aggregation_detail(detail: dict, now: str) -> dict:
    payload = dict(detail or {})
    payload["aggregation"] = {
        "first_seen": now,
        "last_seen": now,
        "repeat_count": 1,
        "policy": "TRACK_IDENTITY_EPISODE_V27",
    }
    return payload

def add_event(
    student_id: int,
    track_id: str,
    confidence: float,
    detail: dict,
    *,
    liveness_score: float = 1.0,
    anti_spoof_passed: bool = True,
    status: str = "RECOGNIZED",
    camera_source: str = "static-camera",
    cross_camera_dedup_seconds: float | None = None,
) -> dict:
    appearance = _appearance_classification(track_id=track_id, student_id=student_id, status=status,
        confidence=confidence, liveness_score=liveness_score, anti_spoof_passed=anti_spoof_passed,
        detail=detail, camera_source=camera_source)
    if appearance is not None:
        return appearance
    now = utc_now()
    source = str(camera_source or "static-camera").strip() or "static-camera"
    attribution = _event_attribution()
    attributed = attribution.get("camera_id") is not None
    cross_window = float(cross_camera_dedup_seconds if cross_camera_dedup_seconds is not None else os.getenv("CAMPUSFACE_CROSS_CAMERA_DEDUP_SEC", "8") or 8)
    same_window = float(os.getenv("CAMPUSFACE_SAME_CAMERA_DEDUP_SEC", "60") or 60)
    if str(status).upper() == "RECOGNIZED" and max(cross_window, same_window) > 0:
        scope_sql, scope_params, extra_columns = "", (), ""
        if attributed:
            if attribution.get("store_id") is not None:
                scope_sql, scope_params = " AND store_id=?", (attribution["store_id"],)
            else:
                scope_sql, scope_params = " AND camera_id=? AND store_id IS NULL", (attribution["camera_id"],)
            extra_columns = ",camera_id,store_id,zone_name,store_name,camera_name"
        previous = fetchone(
            "SELECT id,event_at,camera_source,confidence,liveness_score,anti_spoof_passed,status" + extra_columns +
            " FROM recognition_events WHERE student_id=? AND status='RECOGNIZED'" + scope_sql + " ORDER BY id DESC LIMIT 1",
            (student_id,) + scope_params,
        ) or {}
        previous_source = str(previous.get("camera_source") or "").strip()
        previous_at = _parse_event_time(str(previous.get("event_at") or ""))
        current_at = _parse_event_time(now)
        if previous and previous_at and current_at:
            # Professional HR mode: while an employee already has one OPEN presence
            # session, keep only the first successful FaceID record for that session.
            # FaceID can still run continuously for identity confidence; it simply does
            # not create repetitive history/database rows every minute.
            session_dedup = str(os.getenv("CAMPUSFACE_RECOGNITION_SESSION_DEDUP", "1") or "1").strip().lower() not in {"0","false","no","off"}
            # Legacy presence sessions lack store attribution. They must never
            # suppress an event from an independently attributed store pipeline.
            if session_dedup and not attributed:
                open_session = fetchone(
                    "SELECT id,started_at FROM hr_presence_sessions WHERE student_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
                    (student_id,),
                ) or {}
                session_start = _parse_event_time(str(open_session.get("started_at") or ""))
                if open_session and session_start and previous_at >= (session_start - timedelta(seconds=15)):
                    return {
                        "id": int(previous.get("id") or 0),
                        "event_at": str(previous.get("event_at") or now),
                        "status": "RECOGNIZED",
                        "liveness_score": float(previous.get("liveness_score") or liveness_score),
                        "anti_spoof_passed": bool(previous.get("anti_spoof_passed") or 0),
                        "camera_source": previous_source or source,
                        "requested_camera_source": source,
                        "deduplicated": True,
                        "duplicate_scope": "PRESENCE_SESSION",
                    }
            gap = (current_at - previous_at).total_seconds()
            cross_camera = previous.get("camera_id") != attribution["camera_id"] if attributed else bool(previous_source and previous_source != source)
            window = cross_window if cross_camera else same_window
            if window > 0 and 0.0 <= gap <= window:
                return {
                    "id": int(previous.get("id") or 0),
                    "event_at": str(previous.get("event_at") or now),
                    "status": "RECOGNIZED",
                    "liveness_score": float(previous.get("liveness_score") or liveness_score),
                    "anti_spoof_passed": bool(previous.get("anti_spoof_passed") or 0),
                    "camera_source": previous_source or source,
                    "requested_camera_source": source,
                    "deduplicated": True,
                    "duplicate_scope": "CROSS_CAMERA" if cross_camera else "SAME_CAMERA",
                    "duplicate_gap_seconds": round(gap, 3),
                    **({key: previous.get(key) for key in attribution} if attributed else {}),
                }
    event_id = _insert_recognition(
        (student_id, track_id, source, "IN", float(confidence), float(liveness_score),
         1 if anti_spoof_passed else 0, str(status), now, json.dumps({**detail, "camera_source": source, "checkin_result": "SUCCESS" if anti_spoof_passed else "FAILED"}, ensure_ascii=False), now),
        attribution,
    )
    return {"id": event_id, "event_at": now, "status": str(status), "liveness_score": float(liveness_score), "anti_spoof_passed": bool(anti_spoof_passed), "camera_source": source, "deduplicated": False, **attribution}


# Legacy contract marker: CAMPUSFACE_SPOOF_EVENT_DEDUP_SEC", "30" (V2.2). V2.7 runtime is 180s episode aggregation.
def add_spoof_event(track_id: str, detail: dict, *, student_id: int | None = None, confidence: float = 0.0, liveness_score: float = 0.0, camera_source: str = "static-camera") -> dict:
    """Persist one spoof/security episode, not one row per tracker re-acquisition."""
    appearance = _appearance_classification(track_id=track_id, student_id=student_id, status="SPOOF_BLOCKED",
        confidence=confidence, liveness_score=liveness_score, anti_spoof_passed=False,
        detail=detail, camera_source=camera_source)
    if appearance is not None:
        return appearance
    now = utc_now()
    source = str(camera_source or "static-camera").strip() or "static-camera"
    attribution = _event_attribution()
    payload = dict(detail or {})
    dedup_sec = float(os.getenv("CAMPUSFACE_SPOOF_EVENT_DEDUP_SEC", "180") or 180)
    promote_sec = float(os.getenv("CAMPUSFACE_SPOOF_PROMOTE_UNKNOWN_SEC", "90") or 90)

    # If the same physical face was first classified UNREGISTERED and passive PAD
    # subsequently confirms a spoof, promote that existing episode instead of adding
    # a second history row. This is especially important when the detector changes
    # track IDs while a phone/photo stays in view.
    unknown = _recent_recognition_episode(
        "UNREGISTERED", source, now, promote_sec,
        detail=payload, student_id=None, track_id=str(track_id or ""), fallback_single_sec=min(45.0, promote_sec),
    )
    if unknown:
        previous_detail = _safe_detail(unknown.get("detail_json"))
        merged = _aggregation_payload(previous_detail, {
            **payload,
            "camera_source": source,
            "checkin_result": "FAILED",
            "failure_type": "ANTI_SPOOF",
        }, now, promoted_from="UNREGISTERED")
        execute(
            """UPDATE recognition_events SET student_id=?,track_id=?,confidence=?,liveness_score=?,
            anti_spoof_passed=0,status='SPOOF_BLOCKED',detail_json=? WHERE id=?""",
            (student_id, str(track_id or unknown.get("track_id") or ""), float(confidence), float(liveness_score), json.dumps(merged, ensure_ascii=False), int(unknown.get("id") or 0)),
        )
        return {
            "id": int(unknown.get("id") or 0), "event_at": str(unknown.get("event_at") or now),
            "status": "SPOOF_BLOCKED", "liveness_score": float(liveness_score),
            "anti_spoof_passed": False, "camera_source": source,
            "deduplicated": False, "aggregated": True, "promoted_from_unknown": True,
            **({key: unknown.get(key) for key in attribution} if attribution.get("camera_id") is not None else {}),
        }

    previous = _recent_recognition_episode(
        "SPOOF_BLOCKED", source, now, dedup_sec,
        detail=payload, student_id=student_id, track_id=str(track_id or ""), fallback_single_sec=min(60.0, dedup_sec),
    )
    if previous:
        prev_detail = _safe_detail(previous.get("detail_json"))
        prev_reason = str(prev_detail.get("reason") or (prev_detail.get("liveness") or {}).get("reason") or "")
        cur_reason = str(payload.get("reason") or (payload.get("liveness") or {}).get("reason") or "")
        # A reason wording change from the PAD engine should not fragment the same
        # physical spoof episode; preserve both by keeping the newest reason in detail.
        merged = _aggregation_payload(prev_detail, {
            **payload,
            "camera_source": source,
            "checkin_result": "FAILED",
            "failure_type": "ANTI_SPOOF",
            "previous_reason": prev_reason if prev_reason and prev_reason != cur_reason else prev_detail.get("previous_reason", ""),
        }, now)
        execute(
            """UPDATE recognition_events SET confidence=?,liveness_score=?,detail_json=? WHERE id=?""",
            (max(float(previous.get("confidence") or 0.0), float(confidence)), max(float(previous.get("liveness_score") or 0.0), float(liveness_score)), json.dumps(merged, ensure_ascii=False), int(previous.get("id") or 0)),
        )
        return {
            "id": int(previous.get("id") or 0), "event_at": str(previous.get("event_at") or now),
            "status": "SPOOF_BLOCKED", "liveness_score": max(float(previous.get("liveness_score") or 0.0), float(liveness_score)),
            "anti_spoof_passed": False, "camera_source": source, "deduplicated": True,
            "duplicate_scope": "SECURITY_EPISODE",
            **({key: previous.get(key) for key in attribution} if attribution.get("camera_id") is not None else {}),
        }

    payload = _new_aggregation_detail({
        **payload,
        "camera_source": source,
        "checkin_result": "FAILED",
        "failure_type": "ANTI_SPOOF",
    }, now)
    event_id = _insert_recognition(
        (student_id, track_id, source, "IN", float(confidence), float(liveness_score), 0, "SPOOF_BLOCKED", now,
         json.dumps(payload, ensure_ascii=False), now),
        attribution,
    )
    return {"id": event_id, "event_at": now, "status": "SPOOF_BLOCKED", "liveness_score": float(liveness_score), "anti_spoof_passed": False, "camera_source": source, "deduplicated": False, **attribution}


def add_unknown_event(track_id: str, detail: dict, *, camera_source: str = "static-camera") -> dict:
    """Persist one unknown-person episode despite short tracker-ID churn."""
    appearance = _appearance_classification(track_id=track_id, student_id=None, status="UNREGISTERED",
        confidence=0.0, liveness_score=0.0, anti_spoof_passed=False,
        detail=detail, camera_source=camera_source)
    if appearance is not None:
        return appearance
    now = utc_now()
    source = str(camera_source or "static-camera").strip() or "static-camera"
    attribution = _event_attribution()
    payload = dict(detail or {})
    # legacy V2.2 contract marker: CAMPUSFACE_UNKNOWN_EVENT_DEDUP_SEC", "30"
    dedup_sec = float(os.getenv("CAMPUSFACE_UNKNOWN_EVENT_DEDUP_SEC", "180") or 180)
    spoof_hold = float(os.getenv("CAMPUSFACE_UNKNOWN_AFTER_SPOOF_HOLD_SEC", "60") or 60)

    # Do not alternate UNKNOWN/SPOOF rows every few seconds for the same physical
    # carrier. A recently confirmed spoof remains the authoritative episode briefly.
    recent_spoof = _recent_recognition_episode(
        "SPOOF_BLOCKED", source, now, spoof_hold,
        detail=payload, student_id=None, track_id=str(track_id or ""), fallback_single_sec=min(35.0, spoof_hold),
    )
    if recent_spoof:
        return {
            "id": int(recent_spoof.get("id") or 0), "event_at": str(recent_spoof.get("event_at") or now),
            "status": "SPOOF_BLOCKED", "camera_source": source, "deduplicated": True,
            "duplicate_scope": "RECENT_SPOOF_EPISODE",
            **({key: recent_spoof.get(key) for key in attribution} if attribution.get("camera_id") is not None else {}),
        }

    previous = _recent_recognition_episode(
        "UNREGISTERED", source, now, dedup_sec,
        detail=payload, student_id=None, track_id=str(track_id or ""), fallback_single_sec=min(60.0, dedup_sec),
    )
    if previous:
        merged = _aggregation_payload(_safe_detail(previous.get("detail_json")), {**payload, "camera_source": source}, now)
        execute(
            "UPDATE recognition_events SET detail_json=? WHERE id=?",
            (json.dumps(merged, ensure_ascii=False), int(previous.get("id") or 0)),
        )
        return {
            "id": int(previous.get("id") or 0), "event_at": str(previous.get("event_at") or now),
            "status": "UNREGISTERED", "camera_source": source, "deduplicated": True,
            "duplicate_scope": "UNKNOWN_PERSON_EPISODE",
            **({key: previous.get(key) for key in attribution} if attribution.get("camera_id") is not None else {}),
        }

    payload = _new_aggregation_detail({**payload, "camera_source": source}, now)
    event_id = _insert_recognition(
        (None, track_id, source, "IN", 0.0, 0.0, 0, "UNREGISTERED", now, json.dumps(payload, ensure_ascii=False), now),
        attribution,
    )
    return {"id": event_id, "event_at": now, "status": "UNREGISTERED", "camera_source": source, "deduplicated": False, **attribution}


def add_classroom_event(student_id: int | None, track_id: str, action: str, confidence: float, detail: dict) -> dict:
    """Persist one temporal classroom event with a small DB-side duplicate guard.

    The Action Engine already emits START/END once per episode.  This second guard
    protects against tracker churn or a worker retry without suppressing a genuine
    later episode.  It is fully local/offline and works with both PostgreSQL/SQLite.
    """
    now = utc_now()
    payload = dict(detail or {})
    phase = str(payload.get("event_phase") or "STATE").upper()
    dedup_sec = float(payload.get("event_dedup_sec") or os.getenv("CAMPUSFACE_CLASSROOM_EVENT_DEDUP_SEC", "6") or 6)
    if dedup_sec > 0:
        if student_id is not None:
            previous = fetchone(
                """SELECT id,event_at,detail_json FROM classroom_events
                WHERE student_id=? AND action=? ORDER BY id DESC LIMIT 1""",
                (student_id, action),
            ) or {}
        else:
            previous = fetchone(
                """SELECT id,event_at,detail_json FROM classroom_events
                WHERE track_id=? AND action=? ORDER BY id DESC LIMIT 1""",
                (track_id, action),
            ) or {}
        if previous:
            prev_phase = "STATE"
            try:
                prev_phase = str((json.loads(str(previous.get("detail_json") or "{}")) or {}).get("event_phase") or "STATE").upper()
            except Exception:
                pass
            previous_at = _parse_event_time(str(previous.get("event_at") or ""))
            current_at = _parse_event_time(now)
            if prev_phase == phase and previous_at and current_at:
                gap = (current_at - previous_at).total_seconds()
                if 0.0 <= gap <= dedup_sec:
                    return {
                        "id": int(previous.get("id") or 0),
                        "event_at": str(previous.get("event_at") or now),
                        "deduplicated": True,
                        "duplicate_gap_seconds": round(gap, 3),
                    }
    event_id = execute(
        """INSERT INTO classroom_events(student_id,track_id,action,confidence,event_at,detail_json,created_at)
        VALUES(?,?,?,?,?,?,?)""",
        (student_id, track_id, action, float(confidence), now, json.dumps(payload, ensure_ascii=False), now),
    )
    return {"id": event_id, "event_at": now, "deduplicated": False}


def add_audit_event(category: str, event_type: str, status: str = "INFO", *, student_id: int | None = None, camera_source: str = "", detail: dict | None = None) -> dict:
    now = utc_now()
    event_id = execute(
        """INSERT INTO audit_events(category,event_type,status,student_id,camera_source,event_at,detail_json,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        (str(category).upper(), str(event_type).upper(), str(status).upper(), student_id, str(camera_source or ""), now, json.dumps(detail or {}, ensure_ascii=False), now),
    )
    return {"id": event_id, "category": str(category).upper(), "event_type": str(event_type).upper(), "status": str(status).upper(), "student_id": student_id, "event_at": now}


def audit_events(limit: int = 500) -> list[dict]:
    limit = max(1, min(2000, int(limit)))
    return fetchall(
        """SELECT ae.id,ae.category,ae.event_type,ae.status,ae.student_id,ae.camera_source,ae.event_at,ae.detail_json,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM audit_events ae LEFT JOIN students s ON s.id=ae.student_id
        ORDER BY ae.id DESC LIMIT ?""",
        (limit,),
    )


def add_office_crossing_event(
    student_id: int | None,
    track_id: str,
    direction: str,
    confidence: float,
    camera_source: str,
    line_name: str,
    detail: dict | None = None,
) -> dict:
    """Persist one virtual-gate crossing event.

    The OfficeEngine already has track-level hysteresis/cooldown. A small DB guard
    below protects against worker restarts or a tracker ID churn at the doorway.
    """
    direction = "OUT" if str(direction or "").upper() == "OUT" else "IN"
    now = utc_now()
    payload = dict(detail or {})
    payload["direction"] = direction
    # Same recognized person / same direction within two seconds is almost always
    # the same physical crossing. Unknown tracks rely on the engine cooldown.
    if student_id is not None:
        previous = fetchone(
            """SELECT id,event_at,direction FROM office_crossing_events
            WHERE student_id=? ORDER BY id DESC LIMIT 1""",
            (student_id,),
        ) or {}
        previous_at = _parse_event_time(str(previous.get("event_at") or ""))
        current_at = _parse_event_time(now)
        if previous_at and current_at and str(previous.get("direction") or "").upper() == direction:
            gap = (current_at - previous_at).total_seconds()
            if 0.0 <= gap <= 2.0:
                return {
                    "id": int(previous.get("id") or 0),
                    "event_at": str(previous.get("event_at") or now),
                    "direction": direction,
                    "deduplicated": True,
                }
    event_id = execute(
        """INSERT INTO office_crossing_events(student_id,track_id,direction,confidence,camera_source,line_name,event_at,detail_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (student_id, str(track_id or ""), direction, float(confidence or 0.0), str(camera_source or ""),
         str(line_name or "Cửa văn phòng"), now, json.dumps(payload, ensure_ascii=False), now),
    )
    return {"id": event_id, "event_at": now, "direction": direction, "deduplicated": False}


def office_crossing_history(limit: int = 50) -> list[dict]:
    limit = max(1, min(500, int(limit)))
    rows = fetchall(
        """SELECT e.id,e.student_id,e.track_id,e.direction,e.confidence,e.camera_source,e.line_name,e.event_at,e.detail_json,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM office_crossing_events e LEFT JOIN students s ON s.id=e.student_id
        ORDER BY e.id DESC LIMIT ?""",
        (limit,),
    )
    for row in rows:
        try:
            detail = json.loads(str(row.get("detail_json") or "{}")) or {}
        except Exception:
            detail = {}
        row["detail"] = detail
        if not row.get("full_name"):
            row["full_name"] = str(detail.get("full_name") or "Chưa xác định")
        if not row.get("student_code"):
            row["student_code"] = str(detail.get("student_code") or "")
    return rows


def office_crossing_summary() -> dict:
    # "Today" follows the Windows/local machine timezone while events remain stored
    # as UTC ISO strings. Explicit UTC bounds keep SQLite/PostgreSQL behavior equal.
    local_now = datetime.now().astimezone()
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    utc_start = local_start.astimezone(timezone.utc).isoformat()
    utc_end = local_end.astimezone(timezone.utc).isoformat()
    rows = fetchall(
        """SELECT direction,COUNT(*) AS n FROM office_crossing_events
        WHERE event_at>=? AND event_at<? GROUP BY direction""",
        (utc_start, utc_end),
    )
    counts = {str(r.get("direction") or "").upper(): int(r.get("n") or 0) for r in rows}
    in_count = int(counts.get("IN", 0))
    out_count = int(counts.get("OUT", 0))
    return {
        "in_today": in_count,
        "out_today": out_count,
        "occupancy_estimate": max(0, in_count - out_count),
    }

def add_hr_event(
    student_id: int | None,
    track_id: str,
    event_type: str,
    *,
    status: str = "INFO",
    camera_source: str = "",
    detail: dict | None = None,
    dedup_seconds: float = 30.0,
) -> dict:
    """Persist a meaningful HR transition, never a per-frame observation.

    The in-memory state machine is the primary debounce layer. This DB-side guard
    protects 24/7 deployments from worker restarts or tracker churn.
    """
    now = utc_now()
    etype = str(event_type or "").upper().strip()
    payload = dict(detail or {})
    previous = None
    if dedup_seconds > 0:
        if student_id is not None:
            previous = fetchone(
                """SELECT id,event_at,detail_json FROM hr_events
                WHERE student_id=? AND event_type=? ORDER BY id DESC LIMIT 1""",
                (int(student_id), etype),
            )
        elif track_id:
            previous = fetchone(
                """SELECT id,event_at,detail_json FROM hr_events
                WHERE track_id=? AND event_type=? ORDER BY id DESC LIMIT 1""",
                (str(track_id), etype),
            )
    if previous:
        prev_at = _parse_event_time(str(previous.get("event_at") or ""))
        cur_at = _parse_event_time(now)
        same_semantic_state = True
        if etype == "STATUS_CHANGE":
            try:
                prev_detail = json.loads(str(previous.get("detail_json") or "{}")) or {}
            except Exception:
                prev_detail = {}
            same_semantic_state = str(prev_detail.get("to_status") or "").upper() == str(payload.get("to_status") or "").upper()
        if prev_at and cur_at and same_semantic_state:
            gap = (cur_at - prev_at).total_seconds()
            if 0.0 <= gap <= float(dedup_seconds):
                return {
                    "id": int(previous.get("id") or 0),
                    "event_at": str(previous.get("event_at") or now),
                    "event_type": etype,
                    "deduplicated": True,
                    "duplicate_gap_seconds": round(gap, 3),
                }
    event_id = execute(
        """INSERT INTO hr_events(student_id,track_id,event_type,status,camera_source,event_at,detail_json,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        (student_id, str(track_id or ""), etype, str(status or "INFO").upper(), str(camera_source or ""), now,
         json.dumps(payload, ensure_ascii=False), now),
    )
    return {"id": event_id, "event_at": now, "event_type": etype, "status": str(status or "INFO").upper(), "deduplicated": False}


def open_presence_session(
    student_id: int,
    track_id: str,
    camera_source: str,
    *,
    start_reason: str = "CAMERA_SEEN",
    detail: dict | None = None,
) -> dict:
    """Open one presence session per employee, or touch the existing open session."""
    now = utc_now()
    existing = fetchone(
        """SELECT * FROM hr_presence_sessions WHERE student_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1""",
        (int(student_id),),
    )
    if existing:
        execute(
            """UPDATE hr_presence_sessions SET track_id=?,camera_source=?,last_seen_at=?,updated_at=? WHERE id=?""",
            (str(track_id or existing.get("track_id") or ""), str(camera_source or existing.get("camera_source") or ""), now, now, int(existing["id"])),
        )
        existing.update({"track_id": str(track_id or existing.get("track_id") or ""), "camera_source": str(camera_source or existing.get("camera_source") or ""), "last_seen_at": now})
        return {**existing, "created": False}
    sid = execute(
        """INSERT INTO hr_presence_sessions(student_id,track_id,camera_source,started_at,last_seen_at,ended_at,duration_sec,status,start_reason,end_reason,detail_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (int(student_id), str(track_id or ""), str(camera_source or ""), now, now, None, 0.0, "OPEN",
         str(start_reason or "CAMERA_SEEN").upper(), "", json.dumps(detail or {}, ensure_ascii=False), now, now),
    )
    return {"id": sid, "student_id": int(student_id), "track_id": str(track_id or ""), "camera_source": str(camera_source or ""),
            "started_at": now, "last_seen_at": now, "status": "OPEN", "start_reason": str(start_reason or "CAMERA_SEEN").upper(), "created": True}


def touch_presence_session(student_id: int, track_id: str = "", camera_source: str = "") -> dict | None:
    now = utc_now()
    row = fetchone(
        """SELECT * FROM hr_presence_sessions WHERE student_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1""",
        (int(student_id),),
    )
    if not row:
        return None
    execute(
        """UPDATE hr_presence_sessions SET track_id=?,camera_source=?,last_seen_at=?,updated_at=? WHERE id=?""",
        (str(track_id or row.get("track_id") or ""), str(camera_source or row.get("camera_source") or ""), now, now, int(row["id"])),
    )
    return {**row, "last_seen_at": now}


def close_presence_session(student_id: int, *, end_reason: str = "OUT", detail: dict | None = None) -> dict | None:
    now = utc_now()
    row = fetchone(
        """SELECT * FROM hr_presence_sessions WHERE student_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1""",
        (int(student_id),),
    )
    if not row:
        return None
    started = _parse_event_time(str(row.get("started_at") or ""))
    ended = _parse_event_time(now)
    duration = max(0.0, (ended - started).total_seconds()) if started and ended else 0.0
    payload = {}
    try:
        payload = json.loads(str(row.get("detail_json") or "{}")) or {}
    except Exception:
        payload = {}
    if detail:
        payload.update(detail)
    execute(
        """UPDATE hr_presence_sessions SET ended_at=?,duration_sec=?,status='CLOSED',end_reason=?,detail_json=?,updated_at=? WHERE id=?""",
        (now, float(duration), str(end_reason or "OUT").upper(), json.dumps(payload, ensure_ascii=False), now, int(row["id"])),
    )
    return {**row, "ended_at": now, "duration_sec": duration, "status": "CLOSED", "end_reason": str(end_reason or "OUT").upper()}


def hr_event_history(limit: int = 500) -> list[dict]:
    limit = max(1, min(2000, int(limit)))
    rows = fetchall(
        """SELECT e.id,e.student_id,e.track_id,e.event_type,e.status,e.camera_source,e.event_at,e.detail_json,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM hr_events e LEFT JOIN students s ON s.id=e.student_id
        ORDER BY e.id DESC LIMIT ?""",
        (limit,),
    )
    for row in rows:
        try:
            row["detail"] = json.loads(str(row.get("detail_json") or "{}")) or {}
        except Exception:
            row["detail"] = {}
    return rows


def hr_presence_history(limit: int = 500) -> list[dict]:
    limit = max(1, min(2000, int(limit)))
    rows = fetchall(
        """SELECT p.id,p.student_id,p.track_id,p.camera_source,p.started_at,p.last_seen_at,p.ended_at,p.duration_sec,p.status,p.start_reason,p.end_reason,p.detail_json,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM hr_presence_sessions p JOIN students s ON s.id=p.student_id
        ORDER BY p.id DESC LIMIT ?""",
        (limit,),
    )
    for row in rows:
        try:
            row["detail"] = json.loads(str(row.get("detail_json") or "{}")) or {}
        except Exception:
            row["detail"] = {}
    return rows


def hr_current_presence() -> list[dict]:
    return fetchall(
        """SELECT p.id,p.student_id,p.track_id,p.camera_source,p.started_at,p.last_seen_at,p.status,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM hr_presence_sessions p JOIN students s ON s.id=p.student_id
        WHERE p.status='OPEN' ORDER BY p.last_seen_at DESC"""
    )



def close_all_open_presence_sessions(*, end_reason: str = "SYSTEM_RESTART") -> int:
    """Close any sessions left open when the runtime stops/restarts.

    This prevents a stale OPEN row from making the next boot claim that someone is
    currently present before the camera has actually seen them again.
    """
    rows = fetchall("SELECT student_id FROM hr_presence_sessions WHERE status='OPEN'")
    closed = 0
    for row in rows:
        try:
            result = close_presence_session(int(row["student_id"]), end_reason=end_reason)
            if result:
                closed += 1
        except Exception:
            continue
    return closed
