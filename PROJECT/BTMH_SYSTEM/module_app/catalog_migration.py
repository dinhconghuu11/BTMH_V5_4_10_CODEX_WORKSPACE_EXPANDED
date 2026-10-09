"""Explicit additive migration; never called by product startup/import."""
from __future__ import annotations

from . import db
from .catalog_backend import CatalogError, clean_name, table_exists, write_connection, _audit

REVISION = "catalog-zones-20261009"
_RELATIONS = ("camera_store_assignments", "employee_store_assignments", "work_shifts", "account_profiles", "catalog_zones")


def dry_run(conn=None):
    if conn is None:
        with db.connection() as opened:
            return dry_run(opened)
    groups, unresolved = {}, []
    for raw in conn.execute("SELECT id,name,zone_name FROM camera_devices ORDER BY id").fetchall():
        row = dict(raw)
        assignments = [dict(a)["store_id"] for a in conn.execute(
            "SELECT a.store_id FROM camera_store_assignments a JOIN stores s ON s.id=a.store_id "
            "WHERE a.camera_device_id=?", (row["id"],)).fetchall()]
        if not row["zone_name"]:
            continue
        if len(assignments) != 1:
            unresolved.append({"camera_id": row["id"], "reason": "AMBIGUOUS_STORE" if len(assignments) > 1 else "UNASSIGNED_STORE"})
            continue
        key = (assignments[0], row["zone_name"])
        groups.setdefault(key, []).append(row["id"])
    candidates = [{"store_id": sid, "zone_name": name, "camera_ids": ids} for (sid, name), ids in groups.items()]
    variants = []
    for (sid, name) in groups:
        peers = [other for (store, other) in groups if store == sid and other != name and other.strip().casefold() == name.strip().casefold()]
        if peers:
            variants.append({"store_id": sid, "zone_name": name, "variants": peers})
    return {"revision": REVISION, "candidates_require_explicit_mapping": candidates, "unresolved": unresolved,
            "case_whitespace_variants": variants, "schema_only_default": True, "history_updates": 0}


def _guards(conn):
    # A concurrent assignment must lock the same store row as archive. Existing
    # assignment APIs and sync writers therefore cannot attach to inactive stores.
    for table in _RELATIONS:
        if not table_exists(conn, table):
            continue
        active = " AND NEW.status='ACTIVE'" if table == "catalog_zones" else ""
        if conn.mode == "sqlite":
            for event in ("INSERT", "UPDATE"):
                conn.execute(f"CREATE TRIGGER IF NOT EXISTS catalog_active_{table}_{event.lower()} "
                             f"BEFORE {event} ON {table} WHEN NEW.store_id IS NOT NULL{active} AND "
                             "NOT EXISTS (SELECT 1 FROM stores WHERE id=NEW.store_id AND status='ACTIVE') "
                             "BEGIN SELECT RAISE(ABORT,'STORE_NOT_ACTIVE'); END")
        else:
            conn.execute(f"CREATE OR REPLACE FUNCTION catalog_active_{table}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                         f"BEGIN IF NEW.store_id IS NOT NULL{active} THEN "
                         "PERFORM id FROM stores WHERE id=NEW.store_id AND status='ACTIVE' FOR SHARE; "
                         "IF NOT FOUND THEN RAISE EXCEPTION 'STORE_NOT_ACTIVE'; END IF; END IF; RETURN NEW; END $$")
            conn.execute(f"DROP TRIGGER IF EXISTS catalog_active_{table} ON {table}")
            updates = "store_id,status" if table == "catalog_zones" else "store_id"
            conn.execute(f"CREATE TRIGGER catalog_active_{table} BEFORE INSERT OR UPDATE OF {updates} ON {table} "
                         f"FOR EACH ROW EXECUTE FUNCTION catalog_active_{table}()")


def apply_mapping(groups=None, *, test_database=False):
    """Apply only with explicit test authorization; no automatic legacy grouping."""
    if not test_database:
        raise CatalogError("TEST_DATABASE_CONFIRMATION_REQUIRED")
    groups = groups or []
    with write_connection() as conn:
        if conn.mode == "postgres":
            conn.execute("SELECT pg_advisory_xact_lock(54100091)")
        report = dry_run(conn)
        key_type = "BIGSERIAL" if conn.mode == "postgres" else "INTEGER"
        conn.execute(f"CREATE TABLE IF NOT EXISTS catalog_zones (id {key_type} PRIMARY KEY, "
                     "store_id BIGINT NOT NULL REFERENCES stores(id), zone_name TEXT NOT NULL, "
                     "status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','INACTIVE','ARCHIVED')), "
                     "ever_assigned INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,updated_at TEXT NOT NULL, "
                     "UNIQUE(store_id,zone_name))")
        conn.execute("CREATE TABLE IF NOT EXISTS camera_zone_assignments (camera_device_id BIGINT PRIMARY KEY "
                     "REFERENCES camera_devices(id) ON DELETE CASCADE, zone_id BIGINT NOT NULL "
                     "REFERENCES catalog_zones(id), created_at TEXT NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_camera_zone_assignment ON camera_zone_assignments(zone_id)")
        _guards(conn)
        seen = set()
        for group in groups:
            sid, name, camera_ids = group["store_id"], clean_name(group["zone_name"]), group["camera_ids"]
            if isinstance(sid, bool) or not isinstance(sid, int) or sid <= 0 or name != group["zone_name"]:
                raise CatalogError("INVALID_MAPPING")
            store = conn.execute("SELECT id,status FROM stores WHERE id=?" + (" FOR UPDATE" if conn.mode == "postgres" else ""), (sid,)).fetchone()
            if not store or dict(store)["status"] != "ACTIVE":
                raise CatalogError("INVALID_MAPPING")
            if not isinstance(camera_ids, list) or not camera_ids:
                raise CatalogError("INVALID_MAPPING")
            zone = conn.execute("SELECT id,status FROM catalog_zones WHERE store_id=? AND zone_name=?", (sid, name)).fetchone()
            now = db.utc_now()
            if not zone:
                cur = conn.execute("INSERT INTO catalog_zones(store_id,zone_name,created_at,updated_at) VALUES(?,?,?,?)" +
                                   (" RETURNING id" if conn.mode == "postgres" else ""), (sid, name, now, now))
                zid = int(dict(cur.fetchone())["id"]) if conn.mode == "postgres" else cur.lastrowid
            else:
                if dict(zone)["status"] != "ACTIVE":
                    raise CatalogError("INVALID_MAPPING")
                zid = dict(zone)["id"]
            for cid in camera_ids:
                if isinstance(cid, bool) or not isinstance(cid, int) or cid <= 0 or cid in seen:
                    raise CatalogError("INVALID_MAPPING")
                seen.add(cid)
                camera = conn.execute("SELECT id,zone_name FROM camera_devices WHERE id=?" + (" FOR UPDATE" if conn.mode == "postgres" else ""), (cid,)).fetchone()
                assignments = [dict(row)["store_id"] for row in conn.execute(
                    "SELECT store_id FROM camera_store_assignments WHERE camera_device_id=?", (cid,)).fetchall()]
                if not camera or dict(camera)["zone_name"] != name or assignments != [sid]:
                    raise CatalogError("MAPPING_CAMERA_CHANGED", 409)
                existing = conn.execute("SELECT zone_id FROM camera_zone_assignments WHERE camera_device_id=?", (cid,)).fetchone()
                if existing and dict(existing)["zone_id"] != zid:
                    raise CatalogError("MAPPING_CONFLICT", 409)
                if not existing:
                    conn.execute("INSERT INTO camera_zone_assignments(camera_device_id,zone_id,created_at) VALUES(?,?,?)", (cid, zid, now))
                conn.execute("UPDATE catalog_zones SET ever_assigned=1 WHERE id=?", (zid,))
        _audit(conn, "CATALOG_TEST_MIGRATION", {"username": "isolated-test-migration"}, {"revision": REVISION, "mapped_camera_ids": sorted(seen)})
        return {**report, "applied": True, "mapped_camera_ids": sorted(seen)}
