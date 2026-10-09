"""Additive demo camera settings and immutable, source-free event attribution.

Call ``ensure_demo_schema`` after the existing production/platform migrations.
Camera sources are inspected only by the server-side resolver and never returned.
Legacy events are deliberately not attributed from today's camera configuration.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import re
import threading

from . import db

ATTRIBUTION_FIELDS = ("camera_id", "store_id", "zone_name", "store_name", "camera_name")
_EVENT_CONTEXT = ContextVar("btmh_camera_event_context", default=None)
_SCHEMA_LOCK = threading.RLock()
_CAMERA_COLUMNS = {
    "ai_enabled": "INTEGER NOT NULL DEFAULT 0",
    "attendance_enabled": "INTEGER NOT NULL DEFAULT 1",
    "visitor_counting_enabled": "INTEGER NOT NULL DEFAULT 0",
    "entrance_config_json": "TEXT NOT NULL DEFAULT '{}'",
}
_EVENT_COLUMNS = {
    "camera_id": "BIGINT", "store_id": "BIGINT", "zone_name": "TEXT",
    "store_name": "TEXT", "camera_name": "TEXT",
}
ENTRANCE_DEFAULTS = {
    "enabled": False, "name": "", "x1": .15, "y1": .55, "x2": .85, "y2": .55,
    "inside_side": "positive", "deadband": .025, "cooldown_sec": 2.5,
    "anchor": "person_center", "roi": None, "reacquire_sec": 2.0, "max_distance": .12,
}


def _positive_id(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or value != number):
        return None
    return number if number > 0 else None


def _safe_name(value, limit=120):
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "")).strip()
    text = re.sub(r"(?:rtsps?|https?)://\S+", "[redacted]", text, flags=re.I)
    text = re.sub(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", "[redacted]", text)
    return text[:limit]


def _columns(conn, table):
    if conn.mode == "postgres":
        rows = conn.execute("SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema=current_schema() AND table_name=?", (table,)).fetchall()
        return {str(dict(row)["column_name"]) for row in rows}
    return {str(dict(row)["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_demo_schema():
    """Idempotent additions only; no customer runtime DB is opened by import."""
    with _SCHEMA_LOCK, db.connection() as conn:
        if conn.mode == "postgres":
            conn.execute("SELECT pg_advisory_xact_lock(54100071)")
        for table, additions in (("camera_devices", _CAMERA_COLUMNS), ("recognition_events", _EVENT_COLUMNS)):
            columns = _columns(conn, table)
            if not columns:
                continue  # Existing schema owns creation; this migration never seeds cameras.
            for column, declaration in additions.items():
                if column not in columns:
                    optional = " IF NOT EXISTS" if conn.mode == "postgres" else ""
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN{optional} {column} {declaration}")
        if _columns(conn, "recognition_events") >= set(_EVENT_COLUMNS):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recognition_camera_time_demo "
                         "ON recognition_events(camera_id,event_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recognition_store_time_demo "
                         "ON recognition_events(store_id,event_at)")


def _bounded(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"INVALID_ENTRANCE_{name.upper()}")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"INVALID_ENTRANCE_{name.upper()}") from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"INVALID_ENTRANCE_{name.upper()}")
    return number


def validate_entrance_config(config=None):
    """Allowlisted normalized line/optional rectangular ROI; never persist arbitrary fields."""
    if config is not None and not isinstance(config, dict):
        raise ValueError("INVALID_ENTRANCE_CONFIG")
    values = {**ENTRANCE_DEFAULTS, **(config or {})}
    if not isinstance(values["enabled"], bool):
        raise ValueError("INVALID_ENTRANCE_ENABLED")
    result = {"enabled": values["enabled"], "name": _safe_name(values["name"])}
    for key in ("x1", "y1", "x2", "y2"):
        result[key] = _bounded(values[key], key, 0., 1.)
    if math.hypot(result["x2"] - result["x1"], result["y2"] - result["y1"]) < .01:
        raise ValueError("INVALID_ENTRANCE_LINE")
    side = str(values["inside_side"])
    anchor = str(values["anchor"])
    if side not in {"positive", "negative"}:
        raise ValueError("INVALID_ENTRANCE_INSIDE_SIDE")
    if anchor not in {"person_center", "person_bottom", "face_center"}:
        raise ValueError("INVALID_ENTRANCE_ANCHOR")
    result.update(inside_side=side, anchor=anchor)
    for key, low, high in (("deadband", .001, .2), ("cooldown_sec", .1, 60.),
                           ("reacquire_sec", 0., 10.), ("max_distance", .01, .5)):
        result[key] = _bounded(values[key], key, low, high)
    roi = values["roi"]
    result["roi"] = None
    if roi is not None:
        if not isinstance(roi, dict):
            raise ValueError("INVALID_ENTRANCE_ROI")
        clean_roi = {key: _bounded(roi.get(key), "roi", 0., 1.) for key in ("x1", "y1", "x2", "y2")}
        if clean_roi["x1"] >= clean_roi["x2"] or clean_roi["y1"] >= clean_roi["y2"]:
            raise ValueError("INVALID_ENTRANCE_ROI")
        if not all(clean_roi["x1"] <= result[x] <= clean_roi["x2"] and
                   clean_roi["y1"] <= result[y] <= clean_roi["y2"] for x, y in (("x1", "y1"), ("x2", "y2"))):
            raise ValueError("ENTRANCE_LINE_OUTSIDE_ROI")
        result["roi"] = clean_roi
    return result


def _camera_context(conn, camera_id):
    row = conn.execute("SELECT id,name,zone_name,enabled,ai_enabled,attendance_enabled,"
                       "visitor_counting_enabled,entrance_config_json FROM camera_devices WHERE id=?",
                       (camera_id,)).fetchone()
    if not row:
        return None
    row = dict(row)
    assignments = [dict(item) for item in conn.execute(
        "SELECT a.store_id,s.store_name,s.timezone_name FROM camera_store_assignments a "
        "LEFT JOIN stores s ON s.id=a.store_id WHERE a.camera_device_id=? ORDER BY a.store_id",
        (camera_id,)).fetchall()]
    assignment = assignments[0] if len(assignments) == 1 and assignments[0].get("store_name") is not None else {}
    try:
        entrance = validate_entrance_config(json.loads(row.get("entrance_config_json") or "{}"))
    except (ValueError, TypeError, json.JSONDecodeError):
        entrance = {**ENTRANCE_DEFAULTS, "enabled": False}
    return {
        "id": int(row["id"]), "camera_id": int(row["id"]), "name": _safe_name(row["name"]), "camera_name": _safe_name(row["name"]),
        "zone_name": _safe_name(row.get("zone_name")), "store_id": assignment.get("store_id"),
        "store_name": _safe_name(assignment.get("store_name")) if assignment else None,
        "timezone_name": _safe_name(assignment.get("timezone_name"), 80) if assignment else None,
        "assignment_state": "ASSIGNED" if assignment else "AMBIGUOUS" if len(assignments) > 1 else "UNASSIGNED",
        "enabled": bool(row.get("enabled")), "ai_enabled": bool(row.get("ai_enabled")),
        "attendance_enabled": bool(row.get("attendance_enabled")),
        "visitor_counting_enabled": bool(row.get("visitor_counting_enabled")), "entrance_config": entrance,
    }


def camera_context(camera_id):
    cid = _positive_id(camera_id)
    if cid is None:
        return None
    with db.connection() as conn:
        return _camera_context(conn, cid)


def source_context(source):
    """Resolve only a configured source, never a mutable display label."""
    from .camera_profiles import normalize_camera_source
    wanted = normalize_camera_source(str(source or ""))
    if not wanted:
        return None
    with db.connection() as conn:
        rows = conn.execute("SELECT id,source FROM camera_devices").fetchall()
        matches = [int(dict(row)["id"]) for row in rows
                   if normalize_camera_source(str(dict(row)["source"])) == wanted]
        return _camera_context(conn, matches[0]) if len(matches) == 1 else None


def _snapshot(values):
    values = values or {}
    camera_id = _positive_id(values.get("camera_id", values.get("id")))
    if camera_id is None:
        return {field: None for field in ATTRIBUTION_FIELDS}
    return {"camera_id": camera_id, "store_id": _positive_id(values.get("store_id")),
            **{key: _safe_name(values.get(key)) if values.get(key) is not None else None
               for key in ("zone_name", "store_name", "camera_name")}}


@contextmanager
def camera_event_context(snapshot):
    """Capture names/location before processing a frame; nested/thread contexts remain isolated."""
    token = _EVENT_CONTEXT.set(_snapshot(dict(snapshot or {})))
    try:
        yield event_attribution()
    finally:
        _EVENT_CONTEXT.reset(token)


def event_attribution():
    return dict(_EVENT_CONTEXT.get() or {field: None for field in ATTRIBUTION_FIELDS})


def scoped_store_ids(user):
    """None means global owner/admin scope; empty means no store data, never global."""
    user = user or {}
    if str(user.get("role") or "").upper() in {"SUPER_ADMIN", "ADMIN"}:
        return None
    sid = _positive_id(user.get("store_id"))
    return frozenset((sid,)) if sid is not None else frozenset()


def enforce_store_scope(user, store_id):
    scope = scoped_store_ids(user)
    if scope is not None and _positive_id(store_id) not in scope:
        raise PermissionError("STORE_SCOPE_DENIED")
    return True


def list_camera_contexts(user=None):
    scope = scoped_store_ids(user) if user is not None else None  # None is internal/system access.
    with db.connection() as conn:
        ids = [int(dict(row)["id"]) for row in conn.execute("SELECT id FROM camera_devices ORDER BY id").fetchall()]
        items = [_camera_context(conn, cid) for cid in ids]
    return [item for item in items if item and (scope is None or item["store_id"] in scope)]


def save_camera_configuration(camera_id, store_id=None, zone_name="", ai_enabled=False,
                              attendance_enabled=True, visitor_counting_enabled=False, entrance_config=None, camera_name=None):
    """One atomic current store assignment per camera, using its existing immutable ID."""
    cid = _positive_id(camera_id)
    sid = _positive_id(store_id)
    if cid is None or (store_id is not None and sid is None):
        raise ValueError("INVALID_CAMERA_STORE_ID")
    if not all(isinstance(flag, bool) for flag in (ai_enabled, attendance_enabled, visitor_counting_enabled)):
        raise ValueError("INVALID_CAMERA_FLAGS")
    if camera_name is not None:
        name = str(camera_name).strip()
        if not name or len(name) > 120 or name != _safe_name(name):
            raise ValueError("INVALID_CAMERA_NAME")
    zone = _safe_name(zone_name)
    if (ai_enabled or visitor_counting_enabled) and not zone:
        raise ValueError("CAMERA_ZONE_REQUIRED")
    entrance = validate_entrance_config(entrance_config)
    if (ai_enabled or visitor_counting_enabled) and sid is None:
        raise ValueError("CAMERA_STORE_REQUIRED")
    if visitor_counting_enabled and not entrance["enabled"]:
        raise ValueError("ENTRANCE_CONFIG_REQUIRED")
    with db.connection() as conn:
        if conn.mode == "sqlite":
            conn.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if conn.mode == "postgres" else ""
        if not conn.execute("SELECT id FROM camera_devices WHERE id=?" + lock, (cid,)).fetchone():
            raise ValueError("CAMERA_NOT_FOUND")
        if sid is not None and not conn.execute("SELECT id FROM stores WHERE id=?", (sid,)).fetchone():
            raise ValueError("STORE_NOT_FOUND")
        now = db.utc_now()
        conn.execute("UPDATE camera_devices SET zone_name=?,ai_enabled=?,attendance_enabled=?,"
                     "visitor_counting_enabled=?,entrance_config_json=?,updated_at=? WHERE id=?",
                     (zone, int(bool(ai_enabled)), int(bool(attendance_enabled)),
                      int(bool(visitor_counting_enabled)), json.dumps(entrance, ensure_ascii=False), now, cid))
        if camera_name is not None:
            conn.execute("UPDATE camera_devices SET name=? WHERE id=?", (name, cid))
        conn.execute("DELETE FROM camera_store_assignments WHERE camera_device_id=?", (cid,))
        if sid is not None:
            conn.execute("INSERT INTO camera_store_assignments(camera_device_id,store_id,created_at) VALUES(?,?,?)",
                         (cid, sid, now))
        return _camera_context(conn, cid)
