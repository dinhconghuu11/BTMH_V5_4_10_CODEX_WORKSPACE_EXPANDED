from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets

from .config import DATA_ROOT
from .db import connection, execute, fetchall, fetchone, utc_now

VISITOR_ROOT = Path(DATA_ROOT) / "Snapshots" / "Visitors"


def ensure_visitor_schema() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS visitor_sessions (
        session_code TEXT PRIMARY KEY,
        track_ref TEXT NOT NULL DEFAULT '',
        camera_source TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        visitor_type TEXT NOT NULL DEFAULT 'UNKNOWN',
        label TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        entry_event_id BIGINT,
        entry_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        exit_at TEXT,
        duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
        close_reason TEXT NOT NULL DEFAULT '',
        reviewed_by TEXT NOT NULL DEFAULT '',
        reviewed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_visitor_sessions_time ON visitor_sessions(entry_at DESC);
    CREATE INDEX IF NOT EXISTS idx_visitor_sessions_status ON visitor_sessions(status, last_seen_at DESC);
    CREATE INDEX IF NOT EXISTS idx_visitor_sessions_track ON visitor_sessions(camera_source, track_ref, status);
    CREATE TABLE IF NOT EXISTS visitor_best_shots (
        session_code TEXT NOT NULL,
        rank INTEGER NOT NULL,
        relative_path TEXT NOT NULL,
        quality DOUBLE PRECISION NOT NULL DEFAULT 0,
        pose TEXT NOT NULL DEFAULT '',
        captured_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(session_code, rank)
    );
    """
    with connection() as conn:
        conn.executescript(schema)
    VISITOR_ROOT.mkdir(parents=True, exist_ok=True)


def _dt(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        out = datetime.fromisoformat(raw)
        if out.tzinfo is None:
            out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return None


def _new_code() -> str:
    now = datetime.now(timezone.utc)
    return f"VS-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2).upper()}"


def _save_data_url(session_code: str, rank: int, data_url: str) -> str:
    raw = str(data_url or "")
    if not raw.startswith("data:image/") or "," not in raw:
        return ""
    try:
        payload = base64.b64decode(raw.split(",", 1)[1], validate=True)
    except Exception:
        return ""
    if not payload or len(payload) > 5 * 1024 * 1024:
        return ""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = VISITOR_ROOT / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_code}_best_{int(rank)}.jpg"
    path.write_bytes(payload)
    try:
        return str(path.relative_to(Path(DATA_ROOT)))
    except Exception:
        return str(path)


def _shot_rows(session_code: str) -> list[dict]:
    rows = fetchall(
        "SELECT rank,relative_path,quality,pose,captured_at FROM visitor_best_shots WHERE session_code=? ORDER BY rank",
        (session_code,),
    )
    for row in rows:
        row["snapshot_url"] = f"/api/v1/visitors/{session_code}/shots/{int(row.get('rank') or 0)}.jpg"
    return rows


def _decorate(row: dict) -> dict:
    out = dict(row)
    shots = _shot_rows(str(out.get("session_code") or ""))
    # Every evidence image remains traceable to the original recording timeline.
    # Failure to resolve a local/NVR segment never removes the still image.
    try:
        from .recording import resolve_event_video
        for shot in shots:
            shot["video"] = resolve_event_video(
                camera_source=str(out.get("camera_source") or ""),
                event_at=str(shot.get("captured_at") or out.get("entry_at") or ""),
                pre_seconds=30,
                post_seconds=30,
            )
    except Exception:
        for shot in shots:
            shot["video"] = {"available": False}
    out["best_shots"] = shots
    return out


def touch_unknown(
    *,
    track_ref: str,
    camera_source: str,
    event_id: int | None = None,
    best_shots: list[dict] | None = None,
) -> dict:
    """Create/update a real visitor session for one unknown physical track.

    The recognition engine remains authoritative for biometric classification. This
    function only converts an UNREGISTERED track into visitor-management metadata.
    """
    ensure_visitor_schema()
    now = utc_now()
    track_ref = str(track_ref or "").strip()
    source = str(camera_source or "static-camera").strip() or "static-camera"
    row = fetchone(
        "SELECT * FROM visitor_sessions WHERE camera_source=? AND track_ref=? AND status='ACTIVE' ORDER BY entry_at DESC LIMIT 1",
        (source, track_ref),
    )
    if not row:
        # Tracker IDs can churn briefly. Re-open only a very recent track-loss session
        # from the same camera; reviewed/manual-closed sessions are never merged.
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=8)).isoformat()
        recent = fetchone(
            """SELECT * FROM visitor_sessions WHERE camera_source=? AND status='CLOSED'
            AND close_reason='TRACK_LOST' AND last_seen_at>=? ORDER BY last_seen_at DESC LIMIT 1""",
            (source, cutoff),
        )
        if recent:
            code = str(recent["session_code"])
            execute(
                "UPDATE visitor_sessions SET track_ref=?,status='ACTIVE',exit_at=NULL,close_reason='',updated_at=? WHERE session_code=?",
                (track_ref, now, code),
            )
            row = fetchone("SELECT * FROM visitor_sessions WHERE session_code=?", (code,))
        else:
            code = _new_code()
            with connection() as conn:
                conn.execute(
                    """INSERT INTO visitor_sessions(
                    session_code,track_ref,camera_source,status,visitor_type,label,note,entry_event_id,
                    entry_at,last_seen_at,duration_sec,close_reason,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (code, track_ref, source, "ACTIVE", "UNKNOWN", "", "", int(event_id or 0) or None,
                     now, now, 0.0, "", now, now),
                )
            row = fetchone("SELECT * FROM visitor_sessions WHERE session_code=?", (code,))
    code = str((row or {}).get("session_code") or "")
    entry = _dt((row or {}).get("entry_at")) or datetime.now(timezone.utc)
    current = datetime.now(timezone.utc)
    duration = max(0.0, (current - entry).total_seconds())
    execute(
        "UPDATE visitor_sessions SET track_ref=?,last_seen_at=?,duration_sec=?,updated_at=?,entry_event_id=COALESCE(entry_event_id,?) WHERE session_code=?",
        (track_ref, now, duration, now, int(event_id or 0) or None, code),
    )

    shots = sorted(list(best_shots or []), key=lambda x: float(x.get("quality") or 0), reverse=True)[:3]
    for idx, shot in enumerate(shots, start=1):
        data_url = str(shot.get("data_url") or shot.get("snapshot") or "")
        if not data_url:
            continue
        rel = _save_data_url(code, idx, data_url)
        if not rel:
            continue
        existing = fetchone("SELECT session_code FROM visitor_best_shots WHERE session_code=? AND rank=?", (code, idx))
        values = (rel, float(shot.get("quality") or 0), str(shot.get("pose") or ""), str(shot.get("captured_at") or now), now)
        if existing:
            execute(
                "UPDATE visitor_best_shots SET relative_path=?,quality=?,pose=?,captured_at=?,updated_at=? WHERE session_code=? AND rank=?",
                (*values, code, idx),
            )
        else:
            with connection() as conn:
                conn.execute(
                    """INSERT INTO visitor_best_shots(session_code,rank,relative_path,quality,pose,captured_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (code, idx, rel, float(shot.get("quality") or 0), str(shot.get("pose") or ""), str(shot.get("captured_at") or now), now, now),
                )
    fresh = fetchone("SELECT * FROM visitor_sessions WHERE session_code=?", (code,)) or row or {}
    return _decorate(fresh)


def close_track(*, track_ref: str, camera_source: str, reason: str = "TRACK_LOST") -> dict | None:
    ensure_visitor_schema()
    row = fetchone(
        "SELECT * FROM visitor_sessions WHERE camera_source=? AND track_ref=? AND status='ACTIVE' ORDER BY entry_at DESC LIMIT 1",
        (str(camera_source or "static-camera"), str(track_ref or "")),
    )
    if not row:
        return None
    now = utc_now()
    entry = _dt(row.get("entry_at")) or datetime.now(timezone.utc)
    end = datetime.now(timezone.utc)
    duration = max(0.0, (end - entry).total_seconds())
    execute(
        "UPDATE visitor_sessions SET status='CLOSED',exit_at=?,last_seen_at=?,duration_sec=?,close_reason=?,updated_at=? WHERE session_code=?",
        (now, now, duration, str(reason or "TRACK_LOST"), now, row["session_code"]),
    )
    return _decorate(fetchone("SELECT * FROM visitor_sessions WHERE session_code=?", (row["session_code"],)) or row)


def list_sessions(*, status: str = "", limit: int = 100) -> list[dict]:
    ensure_visitor_schema()
    status = str(status or "").strip().upper()
    lim = max(1, min(500, int(limit)))
    if status:
        rows = fetchall("SELECT * FROM visitor_sessions WHERE status=? ORDER BY entry_at DESC LIMIT ?", (status, lim))
    else:
        rows = fetchall("SELECT * FROM visitor_sessions ORDER BY entry_at DESC LIMIT ?", (lim,))
    return [_decorate(r) for r in rows]


def get_session(session_code: str) -> dict | None:
    ensure_visitor_schema()
    row = fetchone("SELECT * FROM visitor_sessions WHERE session_code=?", (str(session_code),))
    return _decorate(row) if row else None


def review_session(session_code: str, *, visitor_type: str, label: str, note: str, actor: str) -> dict:
    ensure_visitor_schema()
    row = fetchone("SELECT * FROM visitor_sessions WHERE session_code=?", (str(session_code),))
    if not row:
        raise ValueError("Không tìm thấy lượt khách")
    vtype = str(visitor_type or "UNKNOWN").strip().upper()
    if vtype not in {"UNKNOWN", "KNOWN", "VIP", "WATCHLIST", "IGNORED"}:
        raise ValueError("Loại khách không hợp lệ")
    now = utc_now()
    execute(
        "UPDATE visitor_sessions SET visitor_type=?,label=?,note=?,reviewed_by=?,reviewed_at=?,updated_at=? WHERE session_code=?",
        (vtype, str(label or "").strip(), str(note or "").strip(), str(actor or ""), now, now, str(session_code)),
    )
    return get_session(session_code) or row


def shot_path(session_code: str, rank: int) -> Path | None:
    ensure_visitor_schema()
    row = fetchone("SELECT relative_path FROM visitor_best_shots WHERE session_code=? AND rank=?", (str(session_code), int(rank)))
    if not row:
        return None
    raw = Path(str(row.get("relative_path") or ""))
    path = raw if raw.is_absolute() else Path(DATA_ROOT) / raw
    try:
        resolved = path.resolve()
        root = Path(DATA_ROOT).resolve()
        if root not in resolved.parents and resolved != root:
            return None
    except Exception:
        return None
    return path if path.exists() else None
