"""Catalog transactions, scoped API and state continuity on isolated databases."""
import json
import os
import uuid
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from module_app import db, main, auth
from module_app import catalog_backend as catalog
from module_app.catalog_migration import dry_run, apply_mapping
from module_app.production_ops import ensure_production_schema, save_camera_device
from module_app.platform_v5 import ensure_platform_v5_schema, create_store
from module_app.demo_context import ensure_demo_schema, save_camera_configuration, camera_context, camera_event_context, event_attribution
from module_app.camera import StaticCameraService
from module_app.ai_camera_runtime import CameraAIRuntime

OWNER = {"username": "catalog-test", "role": "SUPER_ADMIN"}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    # PostgreSQL runner supplies a disposable loopback DSN, never product config.
    dsn = os.getenv("BTMH_CATALOG_TEST_PG_DSN")
    if dsn:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.conninfo import conninfo_to_dict
        settings = conninfo_to_dict(dsn)
        assert settings.get("host") == "127.0.0.1" and settings.get("dbname", "").startswith("btmh_catalog_test")
        schema = "catalog_test_" + uuid.uuid4().hex
        with psycopg.connect(dsn) as raw:
            raw.execute(f'CREATE SCHEMA "{schema}"')
        @contextmanager
        def connection():
            with psycopg.connect(dsn, row_factory=dict_row) as raw:
                raw.execute(f'SET search_path TO "{schema}"')
                yield db._CompatConnection(raw, "postgres")
        original_connection = db.connection
        for name, module in list(sys.modules.items()):
            if name.startswith("module_app.") and getattr(module, "connection", None) is original_connection:
                monkeypatch.setattr(module, "connection", connection)
        monkeypatch.setattr(db, "DB_MODE", "postgres")
        from module_app import config, production_ops
        monkeypatch.setattr(config, "DB_MODE", "postgres")
        monkeypatch.setattr(production_ops, "DB_MODE", "postgres")
        monkeypatch.setattr(db, "connection", connection)
    else:
        monkeypatch.setattr(db, "DB_MODE", "sqlite")
        monkeypatch.setattr(db, "SQLITE_PATH", tmp_path / "catalog-test.db")
    db.init_db()
    ensure_production_schema(seed_cameras=False)
    ensure_platform_v5_schema()
    auth.ensure_rbac_schema()
    ensure_demo_schema()
    stores = [create_store("QA1", "Test Store 1", "UTC"), create_store("QA2", "Test Store 2", "UTC")]
    cameras = []
    for index in (1, 2):
        row = save_camera_device({"name": f"Test Camera {index}", "source": str(index + 10), "zone_name": "Entry"})
        save_camera_configuration(row["id"], store_id=stores[0]["id"], zone_name="Entry", ai_enabled=True)
        cameras.append(row)
    monkeypatch.setattr(main, "_auth_permission", lambda request, permission: OWNER)
    monkeypatch.setattr(main, "AI_RUNTIME", SimpleNamespace(metadata_change=lambda: __import__("contextlib").nullcontext(), refresh_metadata=lambda: None))
    return stores, cameras


def test_migration_dry_run_schema_only_mapping_and_repeatability(isolated):
    stores, cameras = isolated
    before = db.fetchall("SELECT * FROM camera_devices")
    report = dry_run()
    with db.connection() as conn:
        assert not catalog.zones_available(conn)
    assert report["history_updates"] == 0
    assert report["candidates_require_explicit_mapping"][0]["camera_ids"] == [row["id"] for row in cameras]
    with pytest.raises(catalog.CatalogError, match="TEST_DATABASE_CONFIRMATION"):
        apply_mapping()
    apply_mapping(test_database=True)
    assert catalog.list_zones(OWNER)["items"] == []
    groups = [{"store_id": stores[0]["id"], "zone_name": "Entry", "camera_ids": [row["id"] for row in cameras]}]
    apply_mapping(groups, test_database=True)
    zid = camera_context(cameras[0]["id"])["zone_id"]
    apply_mapping(groups, test_database=True)
    assert camera_context(cameras[0]["id"])["zone_id"] == zid
    assert len(catalog.list_zones(OWNER)["items"]) == 1
    assert db.fetchall("SELECT * FROM camera_devices") == before


def test_mapping_failure_rolls_back_schema_and_does_not_merge_variants(isolated):
    stores, cameras = isolated
    db.execute("UPDATE camera_devices SET zone_name=' entry ' WHERE id=?", (cameras[1]["id"],))
    assert len(dry_run()["case_whitespace_variants"]) == 2
    with pytest.raises(catalog.CatalogError, match="MAPPING_CAMERA_CHANGED"):
        apply_mapping([{"store_id": stores[0]["id"], "zone_name": "Entry", "camera_ids": [cameras[1]["id"]]}], test_database=True)
    with db.connection() as conn:
        assert not catalog.zones_available(conn)


def test_store_metadata_status_dependencies_history_and_scope(isolated):
    stores, cameras = isolated
    apply_mapping(test_database=True)
    sid = stores[0]["id"]
    old = camera_context(cameras[0]["id"])
    with camera_event_context(old):
        row = catalog.update_store(sid, {"store_name": "Renamed Store"}, OWNER)
        assert event_attribution()["store_name"] == "Test Store 1"
    assert row["id"] == sid and camera_context(cameras[0]["id"])["store_name"] == "Renamed Store"
    for changes, code in [({"status": "ARCHIVED"}, "STORE_IN_USE"), ({"timezone_name": "Asia/Bangkok"}, "STORE_TIMEZONE_IN_USE")]:
        with pytest.raises(catalog.CatalogError, match=code):
            catalog.update_store(sid, changes, OWNER)
    with pytest.raises(PermissionError):
        catalog.update_store(sid, {"store_name": "Forbidden"}, {"role": "MANAGER", "store_id": stores[1]["id"]})
    archived = catalog.update_store(stores[1]["id"], {"status": "ARCHIVED"}, OWNER)
    assert archived["status"] == "ARCHIVED"
    with pytest.raises(ValueError, match="STORE_NOT_ACTIVE"):
        save_camera_configuration(cameras[0]["id"], store_id=archived["id"], zone_name="Entry")
    with pytest.raises(Exception, match="STORE_NOT_ACTIVE"):
        with db.connection() as conn:
            conn.execute("INSERT INTO employee_store_assignments(student_id,store_id,created_at) VALUES(?,?,?)", (999, archived["id"], db.utc_now()))
    assert catalog.update_store(archived["id"], {"status": "ACTIVE"}, OWNER)["status"] == "ACTIVE"


def test_zone_crud_ids_scope_assignment_and_reference_protection(isolated):
    stores, cameras = isolated
    assert catalog.list_zones(OWNER) == {"available": False, "items": []}
    with pytest.raises(catalog.CatalogError, match="MIGRATION_REQUIRED"):
        catalog.create_zone(stores[0]["id"], "Desk", OWNER)
    apply_mapping(test_database=True)
    zone = catalog.create_zone(stores[0]["id"], "Desk", OWNER)
    other = catalog.create_zone(stores[1]["id"], "Desk", OWNER)
    assert zone["id"] != other["id"]
    with pytest.raises(catalog.CatalogError, match="DUPLICATE_ZONE"):
        catalog.create_zone(stores[0]["id"], "Desk", OWNER)
    with pytest.raises(PermissionError):
        catalog.update_zone(zone["id"], {"zone_name": "Other"}, {"role": "MANAGER", "store_id": stores[1]["id"]})
    assert [item["id"] for item in catalog.list_zones({"role": "MANAGER", "store_id": stores[1]["id"]})["items"]] == [other["id"]]
    with pytest.raises(catalog.CatalogError, match="ZONE_STORE_MISMATCH"):
        save_camera_configuration(cameras[0]["id"], store_id=stores[0]["id"], zone_id=other["id"], ai_enabled=True)
    context = save_camera_configuration(cameras[0]["id"], store_id=stores[0]["id"], zone_id=zone["id"], ai_enabled=True)
    assert context["zone_id"] == zone["id"] and context["zone_name"] == "Desk"
    for action in [lambda: catalog.update_zone(zone["id"], {"zone_name": "Changed"}, OWNER), lambda: catalog.delete_zone(zone["id"], OWNER)]:
        with pytest.raises(catalog.CatalogError): action()
    save_camera_configuration(cameras[0]["id"], store_id=stores[0]["id"], zone_name="Legacy")
    with pytest.raises(catalog.CatalogError, match="ZONE_HAS_REFERENCES"):
        catalog.delete_zone(zone["id"], OWNER)
    assert catalog.update_zone(zone["id"], {"status": "ARCHIVED"}, OWNER)["id"] == zone["id"]
    assert catalog.update_zone(other["id"], {"zone_name": "Fresh"}, OWNER)["id"] == other["id"]
    assert catalog.delete_zone(other["id"], OWNER)["id"] == other["id"]


def test_audit_failure_rolls_back_camera_store_and_zone(isolated, monkeypatch):
    stores, cameras = isolated
    apply_mapping(test_database=True)
    def fail(*args): raise RuntimeError("test audit failure")
    monkeypatch.setattr(catalog, "_audit", fail)
    with pytest.raises(RuntimeError): catalog.rename_camera(cameras[0]["id"], "Rejected", OWNER)
    with pytest.raises(RuntimeError): catalog.update_store(stores[0]["id"], {"store_name": "Rejected"}, OWNER)
    with pytest.raises(RuntimeError): catalog.create_zone(stores[0]["id"], "Rejected", OWNER)
    assert camera_context(cameras[0]["id"])["camera_name"] == "Test Camera 1"
    assert db.fetchone("SELECT store_name FROM stores WHERE id=?", (stores[0]["id"],))["store_name"] == "Test Store 1"
    assert catalog.list_zones(OWNER)["items"] == []


@pytest.mark.parametrize("name", ["", "rtsp://test:credential@example.test/stream", "x"*121])
def test_camera_name_validation_and_source_free_api(isolated, name):
    _, cameras = isolated
    with pytest.raises(HTTPException) as error:
        main.camera_name_save(cameras[0]["id"], main.CameraNamePayload(camera_name=name), object())
    assert error.value.status_code == 400
    result = main.camera_name_save(cameras[0]["id"], main.CameraNamePayload(camera_name="Lobby"), object())
    assert result["ok"] and result["item"]["camera_id"] == cameras[0]["id"]
    assert "source" not in json.dumps(result)
    assert db.fetchone("SELECT event_type FROM audit_events WHERE event_type='CAMERA_RENAMED'")


def test_new_routes_preserve_permission_mapping_and_scope(isolated, monkeypatch):
    stores, cameras = isolated
    actor = {"username": "scoped", "role": "MANAGER", "store_id": stores[1]["id"]}
    monkeypatch.setattr(main, "_auth_permission", lambda *args: actor)
    with pytest.raises(HTTPException) as error:
        main.camera_name_save(cameras[0]["id"], main.CameraNamePayload(camera_name="Forbidden"), object())
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        main.store_update_v5(stores[0]["id"], main.StoreUpdatePayload(store_name="Forbidden"), object())
    assert error.value.status_code == 403
    assert main._api_permission_for("/api/v1/stores/1", "PATCH") == "system.manage"
    assert main._api_permission_for("/api/v1/zones/1", "DELETE") == "system.manage"
    assert main._api_permission_for("/api/v1/zones", "GET") == "camera.live"
    assert main._api_permission_for("/api/v1/cameras/devices/1/name", "PATCH") == "camera.configure"


def test_primary_auxiliary_rename_preserves_live_state_and_behavior_change_retires(isolated, monkeypatch):
    stores, rows = isolated
    made, counters = [], {"starts": 0, "stops": 0, "resets": 0}
    def worker(row, context):
        camera = StaticCameraService()
        camera._walkby = SimpleNamespace(reset=lambda *args: counters.__setitem__("resets", counters["resets"]+1),
                                         configure_resource_limits=lambda *args: None, _pipeline=SimpleNamespace(status=lambda: {}))
        camera.configure_source(row["source"], context["camera_name"])
        camera.configure_ai_pipeline(context, enabled=True)
        camera.start = lambda: counters.__setitem__("starts", counters["starts"]+1)
        camera.stop = lambda: counters.__setitem__("stops", counters["stops"]+1)
        camera.status = lambda: {"safe_decoder_shutdown": True}
        camera._active_session = object()
        camera._result = {"tracks": [{"track_id": "stable", "pad": "passed"}], "events": []}
        camera._source_epoch = 7
        camera._frame_seq = 22
        made.append(camera)
        return camera
    primary = worker(rows[0], camera_context(rows[0]["id"]))
    runtime = CameraAIRuntime(primary, rows=lambda: rows, contexts=lambda: [camera_context(row["id"]) for row in rows], worker_factory=worker)
    runtime.reconcile()
    monkeypatch.setattr(main, "AI_RUNTIME", runtime)
    owners = [runtime.service(row["id"]) for row in rows]
    snapshots = [(c._active_session, c._walkby, c._appearance_owner, c._ai_session_id, c._result, c._source_epoch, c._frame_seq) for c in owners]
    counts = dict(counters)
    old_context = camera_context(rows[0]["id"])
    from module_app.camera_appearances import ensure_appearance_schema
    ensure_appearance_schema()
    now = db.utc_now()
    history_id = db.execute("INSERT INTO recognition_events(track_id,camera_source,status,event_at,created_at,camera_id,store_id,"
                            "zone_name,store_name,camera_name,appearance_id,business_date,daily_sequence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            ("stable", "Test Camera 1", "RECOGNIZED", now, now, rows[0]["id"], stores[0]["id"],
                             "Entry", "Test Store 1", "Test Camera 1", "catalog-test-appearance", "2026-10-09", 8))
    history_before = db.fetchone("SELECT * FROM recognition_events WHERE id=?", (history_id,))
    with camera_event_context(old_context):
        for row in rows:
            result = main.camera_name_save(row["id"], main.CameraNamePayload(camera_name=f"Renamed {row['id']}"), object())
            assert result["ok"]
        assert event_attribution()["camera_name"] == old_context["camera_name"]
    legacy = camera_context(rows[0]["id"])
    fields = ("camera_name", "store_id", "zone_name", "ai_enabled", "attendance_enabled", "visitor_counting_enabled", "entrance_config")
    legacy_payload = main.CameraConfigurationPayload(**{key: legacy[key] for key in fields})
    legacy_payload.camera_name = "Legacy Client Rename"
    assert main.camera_configuration_save(rows[0]["id"], legacy_payload, object())["ok"]
    runtime.reconcile()
    assert counters == counts
    assert [runtime.service(row["id"]) for row in rows] == owners
    assert [(c._active_session, c._walkby, c._appearance_owner, c._ai_session_id, c._result, c._source_epoch, c._frame_seq) for c in owners] == snapshots
    assert owners[0]._event_context["camera_name"] == "Legacy Client Rename" and owners[1]._event_context["camera_name"].startswith("Renamed")
    assert db.fetchone("SELECT * FROM recognition_events WHERE id=?", (history_id,)) == history_before
    catalog.update_store(stores[0]["id"], {"store_name": "Updated Store"}, OWNER)
    runtime.refresh_metadata()
    assert counters == counts and all(c._event_context["store_name"] == "Updated Store" for c in owners)
    db.execute("UPDATE camera_devices SET attendance_enabled=0 WHERE id=?", (rows[1]["id"],))
    runtime.reconcile()
    assert runtime.service(rows[0]["id"]) is owners[0]
    assert runtime.service(rows[1]["id"]) is not owners[1]
    assert counters["stops"] == counts["stops"] + 1
