from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .config import DATA_ROOT
from .db import connection, execute, fetchall, fetchone, utc_now

CLIP_ROOT = Path(DATA_ROOT) / "Evidence" / "Clips"


def ensure_platform_v5_schema() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS stores (
        id INTEGER PRIMARY KEY,
        store_code TEXT NOT NULL UNIQUE,
        store_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        timezone_name TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS employee_store_assignments (
        student_id INTEGER NOT NULL,
        store_id INTEGER NOT NULL,
        is_primary INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        PRIMARY KEY(student_id, store_id)
    );
    CREATE TABLE IF NOT EXISTS camera_store_assignments (
        camera_device_id INTEGER NOT NULL,
        store_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(camera_device_id, store_id)
    );
    CREATE TABLE IF NOT EXISTS work_shifts (
        id INTEGER PRIMARY KEY,
        store_id INTEGER,
        shift_code TEXT NOT NULL UNIQUE,
        shift_name TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        late_grace_minutes INTEGER NOT NULL DEFAULT 5,
        early_leave_grace_minutes INTEGER NOT NULL DEFAULT 5,
        workdays_json TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS employee_shift_assignments (
        student_id INTEGER PRIMARY KEY,
        shift_id INTEGER NOT NULL,
        effective_from TEXT NOT NULL,
        effective_to TEXT,
        assigned_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS attendance_corrections_v5 (
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        original_checkin_at TEXT,
        original_checkout_at TEXT,
        effective_checkin_at TEXT,
        effective_checkout_at TEXT,
        correction_type TEXT NOT NULL DEFAULT 'MANUAL_ADJUSTMENT',
        reason TEXT NOT NULL,
        approved_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_att_corr_v5_employee_date ON attendance_corrections_v5(student_id, work_date, created_at);
    CREATE TABLE IF NOT EXISTS incidents (
        incident_id TEXT PRIMARY KEY,
        store_id INTEGER,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        severity TEXT NOT NULL DEFAULT 'NORMAL',
        visitor_session_code TEXT NOT NULL DEFAULT '',
        employee_id INTEGER,
        occurred_at TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        evidence_locked INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_incidents_time ON incidents(occurred_at DESC);
    CREATE TABLE IF NOT EXISTS incident_evidence (
        id INTEGER PRIMARY KEY,
        incident_id TEXT NOT NULL,
        evidence_type TEXT NOT NULL,
        evidence_ref TEXT NOT NULL,
        camera_source TEXT NOT NULL DEFAULT '',
        captured_at TEXT,
        note TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_incident_evidence_incident ON incident_evidence(incident_id, created_at);
    CREATE TABLE IF NOT EXISTS video_clips (
        clip_id TEXT PRIMARY KEY,
        segment_id TEXT NOT NULL DEFAULT '',
        camera_source TEXT NOT NULL DEFAULT '',
        start_at TEXT NOT NULL,
        end_at TEXT NOT NULL,
        media_uri TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'INDEXED',
        protected INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_video_clips_time ON video_clips(camera_source,start_at,end_at);
    CREATE TABLE IF NOT EXISTS face_enrollment_validations (
        student_id INTEGER PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'PENDING_STORE_VALIDATION',
        camera_source TEXT NOT NULL DEFAULT '',
        score REAL NOT NULL DEFAULT 0,
        margin REAL NOT NULL DEFAULT 0,
        validated_at TEXT,
        validated_by TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """
    # PostgreSQL does not allow INTEGER PRIMARY KEY to auto-generate. Convert the
    # local-first IDs to identity-compatible BIGSERIAL in that runtime only.
    try:
        from .config import DB_MODE
        if DB_MODE == "postgres":
            for table in ("stores", "work_shifts", "attendance_corrections_v5", "incident_evidence"):
                schema = schema.replace(f"CREATE TABLE IF NOT EXISTS {table} (\n        id INTEGER PRIMARY KEY,", f"CREATE TABLE IF NOT EXISTS {table} (\n        id BIGSERIAL PRIMARY KEY,")
    except Exception:
        pass
    with connection() as conn:
        conn.executescript(schema)
    CLIP_ROOT.mkdir(parents=True, exist_ok=True)
    _ensure_default_store()
    _ensure_default_shift()
    from .shift_attendance import ensure_shift_attendance_schema
    ensure_shift_attendance_schema()



def _sync_event(event_type: str, aggregate_type: str, aggregate_id, payload: dict, store_id: int | None = None) -> None:
    try:
        from .sync_v5 import enqueue_sync_event
        enqueue_sync_event(event_type, aggregate_type, aggregate_id, payload, store_id=store_id)
    except Exception:
        # Edge business operations must remain local-first even if sync metadata cannot be queued.
        pass

def _ensure_default_store() -> None:
    if fetchone("SELECT id FROM stores ORDER BY id LIMIT 1"):
        return
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO stores(store_code,store_name,status,timezone_name,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("BTMH-001", "Cửa hàng mặc định", "ACTIVE", "Asia/Ho_Chi_Minh", now, now),
        )


def _ensure_default_shift() -> None:
    if fetchone("SELECT id FROM work_shifts ORDER BY id LIMIT 1"):
        return
    now = utc_now()
    store = fetchone("SELECT id FROM stores ORDER BY id LIMIT 1") or {}
    with connection() as conn:
        conn.execute(
            """INSERT INTO work_shifts(store_id,shift_code,shift_name,start_time,end_time,late_grace_minutes,early_leave_grace_minutes,workdays_json,active,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (store.get("id"), "HC", "Ca hành chính", "08:00", "17:30", 5, 5, "[0,1,2,3,4,5]", 1, now, now),
        )


def list_stores() -> list[dict]:
    ensure_platform_v5_schema()
    return fetchall("SELECT * FROM stores ORDER BY status DESC,store_name")


def set_face_enrollment_validation_pending(student_id: int, *, note: str = "") -> dict:
    ensure_platform_v5_schema()
    sid = int(student_id)
    if not fetchone("SELECT id FROM students WHERE id=?", (sid,)):
        raise ValueError("Không tìm thấy nhân viên")
    now = utc_now()
    existing = fetchone("SELECT student_id FROM face_enrollment_validations WHERE student_id=?", (sid,))
    if existing:
        execute(
            "UPDATE face_enrollment_validations SET status='PENDING_STORE_VALIDATION',camera_source='',score=0,margin=0,validated_at=NULL,validated_by='',note=?,updated_at=? WHERE student_id=?",
            (str(note or ""), now, sid),
        )
    else:
        execute(
            "INSERT INTO face_enrollment_validations(student_id,status,camera_source,score,margin,validated_at,validated_by,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (sid, "PENDING_STORE_VALIDATION", "", 0.0, 0.0, None, "", str(note or ""), now, now),
        )
    row = face_enrollment_validation(sid) or {}
    _sync_event("FACE_VALIDATION_PENDING", "EMPLOYEE", sid, row, None)
    return row


def mark_face_enrollment_validated(student_id: int, *, camera_source: str, score: float, margin: float, actor: str, note: str = "") -> dict:
    ensure_platform_v5_schema()
    sid = int(student_id)
    if not fetchone("SELECT id FROM students WHERE id=?", (sid,)):
        raise ValueError("Không tìm thấy nhân viên")
    now = utc_now()
    existing = fetchone("SELECT student_id FROM face_enrollment_validations WHERE student_id=?", (sid,))
    values = ("VERIFIED", str(camera_source or ""), float(score or 0.0), float(margin or 0.0), now, str(actor or ""), str(note or ""), now)
    if existing:
        execute(
            "UPDATE face_enrollment_validations SET status=?,camera_source=?,score=?,margin=?,validated_at=?,validated_by=?,note=?,updated_at=? WHERE student_id=?",
            (*values, sid),
        )
    else:
        execute(
            "INSERT INTO face_enrollment_validations(student_id,status,camera_source,score,margin,validated_at,validated_by,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (sid, *values[:-1], now, values[-1]),
        )
    row = face_enrollment_validation(sid) or {}
    _sync_event("FACE_VALIDATED", "EMPLOYEE", sid, row, None)
    return row


def face_enrollment_validation(student_id: int) -> dict | None:
    ensure_platform_v5_schema()
    return fetchone("SELECT * FROM face_enrollment_validations WHERE student_id=?", (int(student_id),))


def create_store(store_code: str, store_name: str, timezone_name: str = "Asia/Ho_Chi_Minh") -> dict:
    ensure_platform_v5_schema()
    code = str(store_code or "").strip().upper()
    name = str(store_name or "").strip()
    if len(code) < 2 or not name:
        raise ValueError("Mã và tên chi nhánh không hợp lệ")
    if fetchone("SELECT id FROM stores WHERE store_code=?", (code,)):
        raise ValueError("Mã chi nhánh đã tồn tại")
    now = utc_now()
    store_id = execute(
        "INSERT INTO stores(store_code,store_name,status,timezone_name,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (code, name, "ACTIVE", str(timezone_name or "Asia/Ho_Chi_Minh"), now, now),
    )
    row = fetchone("SELECT * FROM stores WHERE id=?", (store_id,)) or {}
    _sync_event("STORE_UPSERT", "STORE", row.get("id") or store_id, row, row.get("id"))
    return row


def list_shifts(store_id: int | None = None) -> list[dict]:
    ensure_platform_v5_schema()
    if store_id:
        rows = fetchall("SELECT * FROM work_shifts WHERE store_id=? OR store_id IS NULL ORDER BY active DESC,shift_name", (int(store_id),))
    else:
        rows = fetchall("SELECT * FROM work_shifts ORDER BY active DESC,shift_name")
    for r in rows:
        try:
            r["workdays"] = json.loads(r.get("workdays_json") or "[]")
        except Exception:
            r["workdays"] = []
    return rows


def save_shift(payload: dict, actor: str) -> dict:
    ensure_platform_v5_schema()
    shift_id = int(payload.get("id") or 0)
    code = str(payload.get("shift_code") or "").strip().upper()
    name = str(payload.get("shift_name") or "").strip()
    start = str(payload.get("start_time") or "08:00").strip()
    end = str(payload.get("end_time") or "17:30").strip()
    if not code or not name or len(start) != 5 or len(end) != 5:
        raise ValueError("Thông tin ca làm chưa hợp lệ")
    workdays = payload.get("workdays") if isinstance(payload.get("workdays"), list) else [0,1,2,3,4,5]
    now = utc_now()
    values = (
        int(payload.get("store_id") or 0) or None, code, name, start, end,
        max(0, min(180, int(payload.get("late_grace_minutes") or 0))),
        max(0, min(180, int(payload.get("early_leave_grace_minutes") or 0))),
        json.dumps([int(x) for x in workdays]), 1 if bool(payload.get("active", True)) else 0, now,
    )
    if shift_id:
        execute(
            """UPDATE work_shifts SET store_id=?,shift_code=?,shift_name=?,start_time=?,end_time=?,late_grace_minutes=?,early_leave_grace_minutes=?,workdays_json=?,active=?,updated_at=? WHERE id=?""",
            (*values, shift_id),
        )
    else:
        shift_id = execute(
            """INSERT INTO work_shifts(store_id,shift_code,shift_name,start_time,end_time,late_grace_minutes,early_leave_grace_minutes,workdays_json,active,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (*values[:-1], now, now),
        )
    row = fetchone("SELECT * FROM work_shifts WHERE id=?", (shift_id,)) or {}
    row["actor"] = actor
    _sync_event("SHIFT_UPSERT", "WORK_SHIFT", row.get("id") or shift_id, row, row.get("store_id"))
    return row


def assign_employee_shift(student_id: int, shift_id: int, actor: str, effective_from: str = "") -> dict:
    ensure_platform_v5_schema()
    if not fetchone("SELECT id FROM students WHERE id=?", (int(student_id),)):
        raise ValueError("Không tìm thấy nhân viên")
    shift = fetchone("SELECT * FROM work_shifts WHERE id=? AND active=1", (int(shift_id),))
    if not shift:
        raise ValueError("Ca làm không tồn tại hoặc đã tắt")
    now = utc_now()
    try:
        start = date.fromisoformat(str(effective_from or now[:10])).isoformat()
    except ValueError:
        raise ValueError("Ngày hiệu lực ca làm chưa hợp lệ") from None
    from .shift_attendance import save_assignment_history
    with connection() as conn:
        row = save_assignment_history(conn, int(student_id), shift, start, actor, now)
        current = conn.execute("SELECT student_id FROM employee_shift_assignments WHERE student_id=?", (int(student_id),)).fetchone()
        if current:
            conn.execute("UPDATE employee_shift_assignments SET shift_id=?,effective_from=?,effective_to=NULL,assigned_by=?,updated_at=? WHERE student_id=?",
                         (int(shift_id), start, actor, now, int(student_id)))
        else:
            conn.execute("INSERT INTO employee_shift_assignments(student_id,shift_id,effective_from,effective_to,assigned_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                         (int(student_id), int(shift_id), start, None, actor, now, now))
    _sync_event("EMPLOYEE_SHIFT_ASSIGNED", "EMPLOYEE", int(student_id), row, row.get("store_id"))
    return row


def employee_shift(student_id: int, business_date: str | None = None) -> dict | None:
    ensure_platform_v5_schema()
    from .shift_attendance import assignment_for_date
    from zoneinfo import ZoneInfo
    day = business_date or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    return assignment_for_date(int(student_id), day)


def create_attendance_correction(payload: dict, actor: str) -> dict:
    ensure_platform_v5_schema()
    student_id = int(payload.get("student_id") or 0)
    work_date = str(payload.get("work_date") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not student_id or len(work_date) != 10 or len(reason) < 3:
        raise ValueError("Nhân viên, ngày làm việc và lý do điều chỉnh là bắt buộc")
    try:
        date.fromisoformat(work_date)
        for field in ("original_checkin_at", "original_checkout_at", "effective_checkin_at", "effective_checkout_at"):
            if payload.get(field):
                stamp = datetime.fromisoformat(str(payload[field]).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Ngày hoặc thời điểm điều chỉnh chưa hợp lệ") from None
    if not fetchone("SELECT id FROM students WHERE id=?", (student_id,)):
        raise ValueError("Không tìm thấy nhân viên")
    now = utc_now()
    correction_id = execute(
        """INSERT INTO attendance_corrections_v5(student_id,work_date,original_checkin_at,original_checkout_at,effective_checkin_at,effective_checkout_at,correction_type,reason,approved_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            student_id, work_date, payload.get("original_checkin_at"), payload.get("original_checkout_at"),
            payload.get("effective_checkin_at"), payload.get("effective_checkout_at"),
            str(payload.get("correction_type") or "MANUAL_ADJUSTMENT"), reason, actor, now, now,
        ),
    )
    row = fetchone("SELECT * FROM attendance_corrections_v5 WHERE id=?", (correction_id,)) or {}
    _sync_event("ATTENDANCE_CORRECTION", "EMPLOYEE", student_id, row, None)
    return row


def list_attendance_corrections(student_id: int | None = None, limit: int = 200) -> list[dict]:
    ensure_platform_v5_schema()
    lim = max(1, min(1000, int(limit)))
    if student_id:
        return fetchall("SELECT c.*,s.student_code,s.full_name FROM attendance_corrections_v5 c LEFT JOIN students s ON s.id=c.student_id WHERE c.student_id=? ORDER BY c.created_at DESC LIMIT ?", (int(student_id), lim))
    return fetchall("SELECT c.*,s.student_code,s.full_name FROM attendance_corrections_v5 c LEFT JOIN students s ON s.id=c.student_id ORDER BY c.created_at DESC LIMIT ?", (lim,))


def _incident_code() -> str:
    return "INC-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4].upper()


def create_incident(payload: dict, actor: str) -> dict:
    ensure_platform_v5_schema()
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("Tiêu đề sự cố là bắt buộc")
    code = _incident_code()
    now = utc_now()
    occurred = str(payload.get("occurred_at") or now)
    visitor_code = str(payload.get("visitor_session_code") or "").strip()
    with connection() as conn:
        conn.execute(
            """INSERT INTO incidents(incident_id,store_id,title,status,severity,visitor_session_code,employee_id,occurred_at,note,evidence_locked,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (code, int(payload.get("store_id") or 0) or None, title, "OPEN", str(payload.get("severity") or "NORMAL").upper(),
             visitor_code, int(payload.get("employee_id") or 0) or None,
             occurred, str(payload.get("note") or ""), 0, actor, now, now),
        )
    # If a confirmed visitor session is supplied, snapshot evidence and any
    # already-indexed recording segments are attached immediately. We do not
    # infer guilt or intent; this is only evidence preservation/traceability.
    if visitor_code:
        try:
            session = fetchone("SELECT camera_source,entry_at FROM visitor_sessions WHERE session_code=?", (visitor_code,)) or {}
            camera_source = str(session.get("camera_source") or "")
            shots = fetchall("SELECT rank,captured_at FROM visitor_best_shots WHERE session_code=? ORDER BY rank", (visitor_code,))
            from .recording import resolve_event_video
            seen_segments = set()
            for shot in shots[:3]:
                rank = int(shot.get("rank") or 0)
                captured_at = str(shot.get("captured_at") or session.get("entry_at") or occurred)
                add_incident_evidence(code, "BEST_FACE", f"{visitor_code}:shot:{rank}", actor, camera_source, captured_at, "Best Face tự động gắn từ Visitor Session")
                video = resolve_event_video(camera_source=camera_source, event_at=captured_at, pre_seconds=30, post_seconds=30)
                for seg in (video.get("segments") or []):
                    seg_id = str(seg.get("segment_id") or "")
                    if seg_id and seg_id not in seen_segments:
                        seen_segments.add(seg_id)
                        add_incident_evidence(code, "VIDEO_SEGMENT", seg_id, actor, camera_source, captured_at, "Recording segment liên kết Best Face")
        except Exception:
            pass
    row = get_incident(code) or {}
    _sync_event("INCIDENT_CREATED", "INCIDENT", code, row, row.get("store_id"))
    return row


def list_incidents(status: str = "", limit: int = 200) -> list[dict]:
    ensure_platform_v5_schema()
    lim = max(1, min(1000, int(limit)))
    if status:
        rows = fetchall("SELECT * FROM incidents WHERE status=? ORDER BY occurred_at DESC LIMIT ?", (str(status).upper(), lim))
    else:
        rows = fetchall("SELECT * FROM incidents ORDER BY occurred_at DESC LIMIT ?", (lim,))
    return [decorate_incident(x) for x in rows]


def get_incident(incident_id: str) -> dict | None:
    ensure_platform_v5_schema()
    row = fetchone("SELECT * FROM incidents WHERE incident_id=?", (str(incident_id),))
    return decorate_incident(row) if row else None


def decorate_incident(row: dict) -> dict:
    out = dict(row)
    out["evidence"] = fetchall("SELECT * FROM incident_evidence WHERE incident_id=? ORDER BY created_at", (str(out.get("incident_id") or ""),))
    return out


def add_incident_evidence(incident_id: str, evidence_type: str, evidence_ref: str, actor: str, camera_source: str = "", captured_at: str = "", note: str = "") -> dict:
    ensure_platform_v5_schema()
    if not fetchone("SELECT incident_id FROM incidents WHERE incident_id=?", (str(incident_id),)):
        raise ValueError("Không tìm thấy sự cố")
    now = utc_now()
    evidence_id = execute(
        "INSERT INTO incident_evidence(incident_id,evidence_type,evidence_ref,camera_source,captured_at,note,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (str(incident_id), str(evidence_type).upper(), str(evidence_ref), str(camera_source), str(captured_at or "") or None, str(note or ""), actor, now),
    )
    row = fetchone("SELECT * FROM incident_evidence WHERE id=?", (evidence_id,)) or {}
    incident = fetchone("SELECT store_id FROM incidents WHERE incident_id=?", (str(incident_id),)) or {}
    _sync_event("INCIDENT_EVIDENCE_ADDED", "INCIDENT", incident_id, row, incident.get("store_id"))
    return row


def lock_incident_evidence(incident_id: str, actor: str) -> dict:
    ensure_platform_v5_schema()
    incident = fetchone("SELECT * FROM incidents WHERE incident_id=?", (str(incident_id),))
    if not incident:
        raise ValueError("Không tìm thấy sự cố")
    refs = fetchall("SELECT evidence_type,evidence_ref FROM incident_evidence WHERE incident_id=?", (str(incident_id),))
    for item in refs:
        etype, ref = str(item.get("evidence_type") or "").upper(), str(item.get("evidence_ref") or "")
        if etype in {"CLIP", "VIDEO_CLIP"}:
            execute("UPDATE video_clips SET protected=1,updated_at=? WHERE clip_id=?", (utc_now(), ref))
            clip = fetchone("SELECT segment_id FROM video_clips WHERE clip_id=?", (ref,)) or {}
            if clip.get("segment_id"):
                execute("UPDATE recording_segments SET protected=1,updated_at=? WHERE segment_id=?", (utc_now(), clip.get("segment_id")))
        elif etype in {"SEGMENT", "VIDEO_SEGMENT"}:
            execute("UPDATE recording_segments SET protected=1,updated_at=? WHERE segment_id=?", (utc_now(), ref))
    execute("UPDATE incidents SET evidence_locked=1,updated_at=? WHERE incident_id=?", (utc_now(), str(incident_id)))
    row = get_incident(incident_id) or {}
    _sync_event("INCIDENT_EVIDENCE_LOCKED", "INCIDENT", incident_id, {"incident_id": incident_id, "evidence_locked": True, "actor": actor}, row.get("store_id"))
    return row


def _parse_iso(value: str) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def create_video_clip(segment_id: str, start_at: str, end_at: str, actor: str) -> dict:
    """Create an evidence clip from an indexed local recording when possible.

    If the source is NVR/remote, the clip is still indexed as a requested time range,
    but status stays INDEXED rather than pretending bytes were produced locally.
    """
    ensure_platform_v5_schema()
    segment = fetchone("SELECT * FROM recording_segments WHERE segment_id=?", (str(segment_id),))
    if not segment:
        raise ValueError("Không tìm thấy recording segment")
    start = _parse_iso(start_at); end = _parse_iso(end_at)
    seg_start = _parse_iso(segment.get("start_at") or start_at); seg_end = _parse_iso(segment.get("end_at") or end_at)
    if end <= start:
        raise ValueError("Thời gian kết thúc phải sau thời gian bắt đầu")
    if start < seg_start or end > seg_end:
        raise ValueError("Khoảng cắt phải nằm trong recording segment đã chọn")
    clip_id = "CLIP-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4].upper()
    now = utc_now(); output_uri = ""; status = "INDEXED"
    uri = str(segment.get("media_uri") or "")
    source_path = Path(uri)
    if not source_path.is_absolute():
        source_path = Path(DATA_ROOT) / source_path
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg and source_path.exists() and source_path.is_file():
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        folder = CLIP_ROOT / day; folder.mkdir(parents=True, exist_ok=True)
        out = folder / f"{clip_id}.mp4"
        offset = max(0.0, (start - seg_start).total_seconds()); duration = max(0.1, (end - start).total_seconds())
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{offset:.3f}", "-i", str(source_path), "-t", f"{duration:.3f}", "-c", "copy", "-y", str(out)]
        try:
            subprocess.run(cmd, check=True, timeout=max(30, int(duration) + 20), capture_output=True)
            output_uri = str(out.relative_to(Path(DATA_ROOT)))
            status = "READY"
        except Exception:
            status = "INDEXED"
    with connection() as conn:
        conn.execute(
            "INSERT INTO video_clips(clip_id,segment_id,camera_source,start_at,end_at,media_uri,status,protected,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (clip_id, str(segment_id), str(segment.get("camera_source") or ""), start.isoformat(), end.isoformat(), output_uri, status, 0, actor, now, now),
        )
    row = fetchone("SELECT * FROM video_clips WHERE clip_id=?", (clip_id,)) or {}
    _sync_event("VIDEO_CLIP_CREATED", "VIDEO_CLIP", clip_id, row, None)
    return row


def list_video_clips(limit: int = 200) -> list[dict]:
    ensure_platform_v5_schema()
    return fetchall("SELECT * FROM video_clips ORDER BY created_at DESC LIMIT ?", (max(1, min(1000, int(limit))),))
