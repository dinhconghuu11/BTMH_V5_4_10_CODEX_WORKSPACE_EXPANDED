from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_ROOT
from .db import connection, fetchall, fetchone, utc_now

RECORDING_ROOT = Path(DATA_ROOT) / "Recordings"


def ensure_recording_schema() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS recording_segments (
        segment_id TEXT PRIMARY KEY,
        camera_source TEXT NOT NULL DEFAULT '',
        start_at TEXT NOT NULL,
        end_at TEXT NOT NULL,
        storage_type TEXT NOT NULL DEFAULT 'NVR',
        media_uri TEXT NOT NULL DEFAULT '',
        size_bytes BIGINT NOT NULL DEFAULT 0,
        protected INTEGER NOT NULL DEFAULT 0,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_recording_segments_camera_time ON recording_segments(camera_source,start_at,end_at);
    CREATE TABLE IF NOT EXISTS video_bookmarks (
        bookmark_id TEXT PRIMARY KEY,
        camera_source TEXT NOT NULL DEFAULT '',
        event_type TEXT NOT NULL DEFAULT '',
        event_ref TEXT NOT NULL DEFAULT '',
        start_at TEXT NOT NULL,
        end_at TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        protected INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_video_bookmarks_time ON video_bookmarks(start_at DESC);
    """
    with connection() as conn:
        conn.executescript(schema)
    RECORDING_ROOT.mkdir(parents=True, exist_ok=True)


def _parse(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def archive_status() -> dict:
    ensure_recording_schema()
    row = fetchone("SELECT COUNT(*) n,COALESCE(SUM(size_bytes),0) total FROM recording_segments") or {}
    protected = fetchone("SELECT COUNT(*) n FROM recording_segments WHERE protected=1") or {}
    return {
        "mode": "NVR_OR_LOCAL_INDEX",
        "recording_root": str(RECORDING_ROOT),
        "segment_count": int(row.get("n") or 0),
        "indexed_bytes": int(row.get("total") or 0),
        "protected_segments": int(protected.get("n") or 0),
        "retention_days_default": 30,
        "note": "V3.1 indexes video metadata; camera/NVR remains the preferred long-term recorder.",
    }


def list_segments(*, camera_source: str = "", start_at: str = "", end_at: str = "", limit: int = 200) -> list[dict]:
    ensure_recording_schema()
    where, params = [], []
    if camera_source:
        where.append("camera_source=?"); params.append(str(camera_source))
    if start_at:
        where.append("end_at>=?"); params.append(str(start_at))
    if end_at:
        where.append("start_at<=?"); params.append(str(end_at))
    sql = "SELECT * FROM recording_segments"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY start_at DESC LIMIT ?"
    params.append(max(1, min(2000, int(limit))))
    return fetchall(sql, tuple(params))


def resolve_event_video(*, camera_source: str, event_at: str, pre_seconds: int = 10, post_seconds: int = 10) -> dict:
    """Return indexed video segments that can cover an event time.

    This deliberately does not pretend that a recording exists. If no NVR/local
    segment has been indexed, callers receive an explicit unavailable result.
    """
    ensure_recording_schema()
    event = _parse(event_at)
    if not event:
        return {"available": False, "segments": [], "reason": "INVALID_EVENT_TIME"}
    from datetime import timedelta
    start = (event - timedelta(seconds=max(0, int(pre_seconds)))).isoformat()
    end = (event + timedelta(seconds=max(0, int(post_seconds)))).isoformat()
    segments = list_segments(camera_source=camera_source, start_at=start, end_at=end, limit=50)
    return {"available": bool(segments), "camera_source": camera_source, "event_at": event.isoformat(), "window": {"start_at": start, "end_at": end}, "segments": segments, "reason": "" if segments else "NO_INDEXED_RECORDING"}
