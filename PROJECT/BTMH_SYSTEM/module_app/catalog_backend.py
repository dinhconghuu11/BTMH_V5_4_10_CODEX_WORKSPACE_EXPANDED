"""Transactional catalog metadata. Zone schema is installed only by explicit migration."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db
from .demo_context import _safe_name, _camera_context, enforce_store_scope


class CatalogError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def table_exists(conn, table):
    if conn.mode == "postgres":
        return bool(conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() "
                                 "AND table_name=?", (table,)).fetchone())
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def zones_available(conn):
    return table_exists(conn, "catalog_zones") and table_exists(conn, "camera_zone_assignments")


@contextmanager
def write_connection():
    try:
        with db.connection() as conn:
            if conn.mode == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            yield conn
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505" or isinstance(exc, sqlite3.IntegrityError) and "UNIQUE constraint failed" in str(exc):
            raise CatalogError("DUPLICATE_CATALOG", 409) from None
        if "STORE_NOT_ACTIVE" in str(exc):
            raise CatalogError("STORE_NOT_ACTIVE", 409) from None
        raise


def clean_name(value):
    text = str(value or "").strip()
    if not text or len(text) > 120 or text != _safe_name(text):
        raise CatalogError("INVALID_NAME")
    return text


def _lock(conn):
    return " FOR UPDATE" if conn.mode == "postgres" else ""


def _store(conn, sid, actor=None):
    if actor is not None:
        enforce_store_scope(actor, sid)
    row = conn.execute("SELECT * FROM stores WHERE id=?" + _lock(conn), (sid,)).fetchone()
    if not row:
        raise CatalogError("STORE_NOT_FOUND", 404)
    return dict(row)


def _audit(conn, event_type, actor, detail):
    now = db.utc_now()
    conn.execute("INSERT INTO audit_events(category,event_type,status,event_at,detail_json,created_at) "
                 "VALUES('SYSTEM',?,'SUCCESS',?,?,?)",
                 (event_type, now, json.dumps({"actor": (actor or {}).get("username"), **detail}, ensure_ascii=False), now))


def rename_camera(cid, name, actor):
    name = clean_name(name)
    with write_connection() as conn:
        if not conn.execute("SELECT id FROM camera_devices WHERE id=?" + _lock(conn), (cid,)).fetchone():
            raise CatalogError("CAMERA_NOT_FOUND", 404)
        before = _camera_context(conn, cid)
        enforce_store_scope(actor, before.get("store_id"))
        conn.execute("UPDATE camera_devices SET name=?,updated_at=? WHERE id=?", (name, db.utc_now(), cid))
        _audit(conn, "CAMERA_RENAMED", actor, {"camera_id": cid, "old_name": before["camera_name"], "camera_name": name})
        return _camera_context(conn, cid)


def store_dependencies(conn, sid):
    checks = (("camera_store_assignments", "store_id=?"), ("employee_store_assignments", "store_id=?"),
              ("work_shifts", "store_id=?"), ("account_profiles", "store_id=?"),
              ("catalog_zones", "store_id=? AND status='ACTIVE'"), ("edge_nodes_v5", "store_id=?"))
    return {table: int(dict(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {condition}", (sid,)).fetchone())["n"])
            for table, condition in checks if table_exists(conn, table)}


def _store_has_history(conn, sid):
    from .demo_context import _columns
    # Conservative: these independent domain snapshots remain untouched.
    for table in ("recognition_events", "camera_appearances", "shift_attendance_records", "entrance_visits", "incidents"):
        if "store_id" in _columns(conn, table) and conn.execute(f"SELECT 1 FROM {table} WHERE store_id=? LIMIT 1", (sid,)).fetchone():
            return True
    return False


def update_store(sid, payload, actor):
    with write_connection() as conn:
        row = _store(conn, sid, actor)
        name = clean_name(payload.get("store_name", row["store_name"]))
        code = str(payload.get("store_code", row["store_code"])).strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,79}", code):
            raise CatalogError("INVALID_STORE_CODE")
        timezone = str(payload.get("timezone_name", row["timezone_name"]))
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise CatalogError("INVALID_TIMEZONE") from None
        status = str(payload.get("status", row["status"])).upper()
        if status not in {"ACTIVE", "INACTIVE", "ARCHIVED"}:
            raise CatalogError("INVALID_STATUS")
        dependencies = store_dependencies(conn, sid)
        if status != "ACTIVE" and not zones_available(conn):
            raise CatalogError("ZONE_MIGRATION_REQUIRED", 503)
        if status != "ACTIVE" and any(dependencies.values()):
            raise CatalogError("STORE_IN_USE", 409)
        if timezone != row["timezone_name"] and (any(dependencies.values()) or _store_has_history(conn, sid)):
            raise CatalogError("STORE_TIMEZONE_IN_USE", 409)
        if conn.execute("SELECT 1 FROM stores WHERE store_code=? AND id<>?", (code, sid)).fetchone():
            raise CatalogError("DUPLICATE_STORE_CODE", 409)
        conn.execute("UPDATE stores SET store_code=?,store_name=?,timezone_name=?,status=?,updated_at=? WHERE id=?",
                     (code, name, timezone, status, db.utc_now(), sid))
        _audit(conn, "STORE_UPDATED", actor, {"store_id": sid, "before": row, "store_name": name, "status": status})
        return dict(conn.execute("SELECT * FROM stores WHERE id=?", (sid,)).fetchone())


def list_zones(actor):
    from .demo_context import scoped_store_ids
    with db.connection() as conn:
        if not zones_available(conn):
            return {"available": False, "items": []}
        scope = scoped_store_ids(actor)
        items = [dict(row) for row in conn.execute(
            "SELECT z.*,s.store_name,(SELECT COUNT(*) FROM camera_zone_assignments a WHERE a.zone_id=z.id) AS camera_count "
            "FROM catalog_zones z JOIN stores s ON s.id=z.store_id ORDER BY z.status,z.store_id,z.zone_name").fetchall()]
        return {"available": True, "items": [row for row in items if scope is None or row["store_id"] in scope]}


def _require_zones(conn):
    if not zones_available(conn):
        raise CatalogError("ZONE_MIGRATION_REQUIRED", 503)


def _zone(conn, zid, actor, *, locked=False):
    _require_zones(conn)
    row = conn.execute("SELECT * FROM catalog_zones WHERE id=?" + (_lock(conn) if locked else ""), (zid,)).fetchone()
    if not row:
        raise CatalogError("ZONE_NOT_FOUND", 404)
    row = dict(row)
    enforce_store_scope(actor, row["store_id"])
    return row


def create_zone(sid, name, actor):
    name = clean_name(name)
    with write_connection() as conn:
        _require_zones(conn)
        store = _store(conn, sid, actor)
        if store["status"] != "ACTIVE":
            raise CatalogError("STORE_NOT_ACTIVE", 409)
        if conn.execute("SELECT 1 FROM catalog_zones WHERE store_id=? AND zone_name=?", (sid, name)).fetchone():
            raise CatalogError("DUPLICATE_ZONE_NAME", 409)
        now = db.utc_now()
        cur = conn.execute("INSERT INTO catalog_zones(store_id,zone_name,status,created_at,updated_at) VALUES(?,?,'ACTIVE',?,?)" +
                           (" RETURNING id" if conn.mode == "postgres" else ""), (sid, name, now, now))
        zid = int(dict(cur.fetchone())["id"]) if conn.mode == "postgres" else cur.lastrowid
        _audit(conn, "ZONE_CREATED", actor, {"zone_id": zid, "store_id": sid, "zone_name": name})
        return dict(conn.execute("SELECT * FROM catalog_zones WHERE id=?", (zid,)).fetchone())


def _zone_in_use(conn, zid):
    return bool(conn.execute("SELECT 1 FROM camera_zone_assignments WHERE zone_id=? LIMIT 1", (zid,)).fetchone())


def update_zone(zid, payload, actor):
    with write_connection() as conn:
        row = _zone(conn, zid, actor)
        store = _store(conn, row["store_id"], actor)
        row = _zone(conn, zid, actor, locked=True)
        name = clean_name(payload.get("zone_name", row["zone_name"]))
        status = str(payload.get("status", row["status"])).upper()
        if status not in {"ACTIVE", "INACTIVE", "ARCHIVED"}:
            raise CatalogError("INVALID_STATUS")
        if (name != row["zone_name"] or status != row["status"]) and _zone_in_use(conn, zid):
            raise CatalogError("ZONE_IN_USE", 409)
        if status == "ACTIVE" and store["status"] != "ACTIVE":
            raise CatalogError("STORE_NOT_ACTIVE", 409)
        if conn.execute("SELECT 1 FROM catalog_zones WHERE store_id=? AND zone_name=? AND id<>?", (row["store_id"], name, zid)).fetchone():
            raise CatalogError("DUPLICATE_ZONE_NAME", 409)
        conn.execute("UPDATE catalog_zones SET zone_name=?,status=?,updated_at=? WHERE id=?", (name, status, db.utc_now(), zid))
        _audit(conn, "ZONE_UPDATED", actor, {"zone_id": zid, "before": row, "zone_name": name, "status": status})
        return dict(conn.execute("SELECT * FROM catalog_zones WHERE id=?", (zid,)).fetchone())


def delete_zone(zid, actor):
    with write_connection() as conn:
        row = _zone(conn, zid, actor)
        _store(conn, row["store_id"], actor)
        row = _zone(conn, zid, actor, locked=True)
        if _zone_in_use(conn, zid) or row["ever_assigned"]:
            raise CatalogError("ZONE_HAS_REFERENCES", 409)
        conn.execute("DELETE FROM catalog_zones WHERE id=?", (zid,))
        _audit(conn, "ZONE_DELETED", actor, {"zone_id": zid, "store_id": row["store_id"], "zone_name": row["zone_name"]})
        return {"id": zid}


def assign_zone(conn, cid, sid, zone_name, zone_id):
    """Legacy free-text clients remain valid; explicit ID must match active store."""
    if not zones_available(conn):
        if zone_id is not None:
            raise CatalogError("ZONE_MIGRATION_REQUIRED", 503)
        return zone_name
    if zone_id is not None:
        row = conn.execute("SELECT * FROM catalog_zones WHERE id=?" + _lock(conn), (zone_id,)).fetchone()
        if not row or dict(row)["store_id"] != sid or dict(row)["status"] != "ACTIVE":
            raise CatalogError("ZONE_STORE_MISMATCH", 409)
        zone_name = dict(row)["zone_name"]
        conn.execute("DELETE FROM camera_zone_assignments WHERE camera_device_id=?", (cid,))
        conn.execute("INSERT INTO camera_zone_assignments(camera_device_id,zone_id,created_at) VALUES(?,?,?)", (cid, zone_id, db.utc_now()))
        conn.execute("UPDATE catalog_zones SET ever_assigned=1 WHERE id=?", (zone_id,))
    else:
        current = conn.execute("SELECT z.store_id,z.zone_name FROM catalog_zones z JOIN camera_zone_assignments a ON a.zone_id=z.id "
                               "WHERE a.camera_device_id=?", (cid,)).fetchone()
        if current and (dict(current)["store_id"] != sid or dict(current)["zone_name"] != zone_name):
            conn.execute("DELETE FROM camera_zone_assignments WHERE camera_device_id=?", (cid,))
    return zone_name
