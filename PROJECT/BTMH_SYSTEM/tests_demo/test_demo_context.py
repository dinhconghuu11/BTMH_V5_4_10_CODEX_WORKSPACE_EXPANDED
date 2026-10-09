"""Run directly with Python: isolated SQLite, no models, credentials or pytest imports."""
from __future__ import annotations

import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys
import threading
import types
import unittest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "module_app"


def load_isolated_modules():
    package_name = "btmh_phase_a_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(SOURCE_ROOT)]
    sys.modules[package_name] = package
    config = types.ModuleType(package_name + ".config")
    for name, value in {
        "DB_MODE": "sqlite", "SQLITE_PATH": ":memory:", "PG_SECRET_PATH": Path("unused"),
        "POSTGRES_CONNECT_TIMEOUT": 1, "POSTGRES_DB": "unused", "POSTGRES_HOST": "unused",
        "POSTGRES_PORT": 5432, "POSTGRES_SSLMODE": "disable", "POSTGRES_USER": "unused",
    }.items():
        setattr(config, name, value)
    sys.modules[config.__name__] = config
    secret_store = types.ModuleType(package_name + ".secret_store")
    secret_store.load_secret = lambda *args, **kwargs: ""
    secret_store.SecretStoreError = RuntimeError
    sys.modules[secret_store.__name__] = secret_store
    modules = []
    for name in ("db", "demo_context"):
        spec = importlib.util.spec_from_file_location(package_name + "." + name, SOURCE_ROOT / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        setattr(package, name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    return tuple(modules)


class DemoContextTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
        temporary_database = sqlite3.connect(":memory:", check_same_thread=False)
        temporary_database.row_factory = sqlite3.Row
        temporary_database.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(temporary_database.close)
        adapter_lock = threading.RLock()

        @contextmanager
        def temporary_connection():
            with adapter_lock:
                try:
                    yield self.db._CompatConnection(temporary_database, "sqlite")
                    temporary_database.commit()
                except Exception:
                    temporary_database.rollback()
                    raise

        self.db.connection = temporary_connection
        self.db.init_db()
        with self.db.connection() as conn:
            conn.executescript("""
                CREATE TABLE camera_devices(id INTEGER PRIMARY KEY,name TEXT,source TEXT UNIQUE,
                    zone_name TEXT DEFAULT '',enabled INTEGER DEFAULT 1,updated_at TEXT);
                CREATE TABLE stores(id INTEGER PRIMARY KEY,store_name TEXT,timezone_name TEXT);
                CREATE TABLE camera_store_assignments(camera_device_id INTEGER,store_id INTEGER,created_at TEXT,
                    PRIMARY KEY(camera_device_id,store_id));
                INSERT INTO stores VALUES(1,'Store A','Asia/Ho_Chi_Minh'),(2,'Store B','Asia/Ho_Chi_Minh');
                INSERT INTO camera_devices VALUES(11,'Entrance','0','Front',1,'2026-01-01');
                INSERT INTO camera_devices VALUES(12,'Entrance','1','Rear',1,'2026-01-01');
                INSERT INTO camera_devices VALUES(13,'Unassigned','rtsp://demo:placeholder@camera.invalid/101','',1,'2026-01-01');
            """)
            conn.execute("INSERT INTO recognition_events(track_id,camera_source,status,event_at,created_at) VALUES(?,?,?,?,?)",
                         ("pre-migration", "Entrance", "UNREGISTERED", self.db.utc_now(), self.db.utc_now()))
        self.context.ensure_demo_schema()
        self.db.execute("INSERT INTO students(student_code,full_name,class_name,faculty,consent_at,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?)", ("TEST", "Employee", "", "", self.db.utc_now(), self.db.utc_now(), self.db.utc_now()))
        self.context.save_camera_configuration(11, 1, "Front", True)
        self.context.save_camera_configuration(12, 2, "Rear", True)

    def recognized(self, camera_id, track="track", **options):
        with self.context.camera_event_context(self.context.camera_context(camera_id)):
            return self.db.add_event(1, track, .9, {}, camera_source="Entrance", **options)

    def test_idempotent_migration_safe_defaults_and_legacy_unknown(self):
        legacy = self.db.add_event(1, "legacy", .9, {}, camera_source="Entrance")
        self.context.ensure_demo_schema()
        self.context.ensure_demo_schema()
        row = self.db.fetchone("SELECT * FROM recognition_events WHERE id=?", (legacy["id"],))
        self.assertTrue(all(row[field] is None for field in self.context.ATTRIBUTION_FIELDS))
        old = self.db.fetchone("SELECT * FROM recognition_events WHERE track_id='pre-migration'")
        self.assertTrue(all(old[field] is None for field in self.context.ATTRIBUTION_FIELDS))
        camera = self.context.camera_context(13)
        self.assertFalse(camera["ai_enabled"])
        self.assertFalse(camera["visitor_counting_enabled"])
        self.assertEqual(camera["assignment_state"], "UNASSIGNED")
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM camera_devices")["n"], 3)

    def test_rename_and_move_preserve_past_location_snapshots(self):
        first = self.recognized(11)
        self.db.execute("UPDATE camera_devices SET name=?,source=? WHERE id=?", ("New entrance", "new-source", 11))
        self.context.save_camera_configuration(11, 2, "New zone", True)
        self.db.execute("UPDATE stores SET store_name=? WHERE id=?", ("Renamed store", 1))
        row = self.db.fetchone("SELECT * FROM recognition_events WHERE id=?", (first["id"],))
        self.assertEqual((row["camera_id"], row["camera_name"], row["store_id"], row["store_name"], row["zone_name"]),
                         (11, "Entrance", 1, "Store A", "Front"))
        next_event = self.recognized(11)
        self.assertNotEqual(next_event["id"], first["id"])
        self.assertEqual(next_event["store_id"], 2)

    def test_success_dedup_is_store_scoped_and_uses_camera_id_after_rename(self):
        first = self.recognized(11)
        second = self.recognized(12)
        self.assertFalse(second["deduplicated"])
        self.assertNotEqual(first["id"], second["id"])
        self.db.execute("UPDATE camera_devices SET name=? WHERE id=?", ("Renamed", 11))
        repeated = self.recognized(11)
        self.assertTrue(repeated["deduplicated"])
        self.assertEqual(repeated["id"], first["id"])
        self.assertEqual(repeated["duplicate_scope"], "SAME_CAMERA")
        self.assertEqual(repeated["camera_name"], "Entrance")
        self.context.save_camera_configuration(12, 1, "Rear", True)
        across_camera = self.recognized(12)
        self.assertTrue(across_camera["deduplicated"])
        self.assertEqual(across_camera["duplicate_scope"], "CROSS_CAMERA")

    def test_unknown_and_spoof_use_stable_camera_store_and_keep_snapshot_on_promotion(self):
        with self.context.camera_event_context(self.context.camera_context(11)):
            first = self.db.add_unknown_event("same", {}, camera_source="Entrance")
        with self.context.camera_event_context(self.context.camera_context(12)):
            other = self.db.add_unknown_event("same", {}, camera_source="Entrance")
        self.assertNotEqual(first["id"], other["id"])
        self.db.execute("UPDATE camera_devices SET name=? WHERE id=?", ("Renamed", 11))
        with self.context.camera_event_context(self.context.camera_context(11)):
            repeated = self.db.add_unknown_event("same", {}, camera_source="Renamed")
            spoof = self.db.add_spoof_event("same", {"reason": "test"}, camera_source="Renamed")
            held = self.db.add_unknown_event("same", {}, camera_source="Renamed")
        self.assertEqual(repeated["id"], first["id"])
        self.assertEqual(spoof["id"], first["id"])
        self.assertEqual(spoof["camera_name"], "Entrance")
        self.assertEqual(held["status"], "SPOOF_BLOCKED")
        self.context.save_camera_configuration(11, 2, "Moved", True)
        with self.context.camera_event_context(self.context.camera_context(11)):
            moved = self.db.add_unknown_event("same", {}, camera_source="Renamed")
        self.assertNotEqual(moved["id"], first["id"])
        self.assertEqual(self.db.fetchone("SELECT camera_name FROM recognition_events WHERE id=?", (first["id"],))["camera_name"], "Entrance")

    def test_legacy_without_context_retains_episode_and_presence_dedup(self):
        first = self.db.add_unknown_event("legacy", {}, camera_source="legacy label")
        second = self.db.add_unknown_event("legacy", {}, camera_source="legacy label")
        self.assertEqual(first["id"], second["id"])
        recognized = self.db.add_event(1, "legacy", .9, {}, camera_source="legacy label")
        self.db.execute("INSERT INTO hr_presence_sessions(student_id,status,started_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (1, "OPEN", self.db.utc_now(), self.db.utc_now(), self.db.utc_now(), self.db.utc_now()))
        repeated = self.db.add_event(1, "legacy", .9, {}, camera_source="legacy label")
        self.assertEqual(repeated["id"], recognized["id"])
        self.assertEqual(repeated["duplicate_scope"], "PRESENCE_SESSION")
        attributed = self.recognized(11)
        self.assertFalse(attributed["deduplicated"])

    def test_store_scope_is_fail_closed_and_public_metadata_excludes_sources(self):
        self.assertEqual(self.context.scoped_store_ids({"role": "MANAGER"}), frozenset())
        self.assertIsNone(self.context.scoped_store_ids({"role": "SUPER_ADMIN"}))
        self.assertEqual([x["camera_id"] for x in self.context.list_camera_contexts({"role": "HR", "store_id": 1})], [11])
        self.assertEqual(self.context.list_camera_contexts({"role": "EMPLOYEE"}), [])
        with self.assertRaises(PermissionError):
            self.context.enforce_store_scope({"role": "MANAGER", "store_id": 1}, 2)
        self.assertTrue(self.context.enforce_store_scope({"role": "ADMIN"}, None))
        public = json.dumps(self.context.source_context("rtsp://demo:placeholder@camera.invalid/101"))
        self.assertNotIn("rtsp", public)
        self.assertNotIn("placeholder", public)
        self.assertNotIn("camera.invalid", public)
        self.assertIsNone(self.context.source_context("Unassigned"))

    def test_configuration_is_atomic_and_canonical_assignment_is_single(self):
        before = self.context.camera_context(11)
        with self.assertRaisesRegex(ValueError, "STORE_NOT_FOUND"):
            self.context.save_camera_configuration(11, 99, "Changed", False)
        self.assertEqual(self.context.camera_context(11), before)
        self.db.execute("INSERT INTO camera_store_assignments VALUES(?,?,?)", (11, 2, self.db.utc_now()))
        self.assertEqual(self.context.camera_context(11)["assignment_state"], "AMBIGUOUS")
        self.assertEqual(self.context.list_camera_contexts({"role": "MANAGER", "store_id": 1}), [])
        saved = self.context.save_camera_configuration(11, 2, "Moved", True)
        self.assertEqual(saved["store_id"], 2)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM camera_store_assignments WHERE camera_device_id=11")["n"], 1)
        with self.assertRaisesRegex(ValueError, "CAMERA_STORE_REQUIRED"):
            self.context.save_camera_configuration(13, None, "Front", True)
        with self.assertRaisesRegex(ValueError, "CAMERA_ZONE_REQUIRED"):
            self.context.save_camera_configuration(13, 1, " ", True)
        with self.assertRaisesRegex(ValueError, "CAMERA_ZONE_REQUIRED"):
            self.context.save_camera_configuration(13, 1, "", False, True, True, {"enabled": True})

    def test_display_name_changes_atomically_without_changing_id_source_or_event_snapshot(self):
        source = self.db.fetchone("SELECT source FROM camera_devices WHERE id=11")["source"]
        with self.context.camera_event_context(self.context.camera_context(11)):
            event = self.db.add_spoof_event("name-test", {"reason": "test"}, camera_source="Entrance")
        saved = self.context.save_camera_configuration(11, 1, "Front", camera_name="Hà Đông - Cửa vào")
        self.assertEqual((saved["camera_id"], saved["camera_name"]), (11, "Hà Đông - Cửa vào"))
        self.assertEqual(self.db.fetchone("SELECT source FROM camera_devices WHERE id=11")["source"], source)
        self.assertEqual(self.db.fetchone("SELECT camera_name FROM recognition_events WHERE id=?", (event["id"],))["camera_name"], "Entrance")
        for name in ("", "  ", "a" * 121, "rtsp://private.invalid/live", "Camera 192.0.2.1", "Bad\nName"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "INVALID_CAMERA_NAME"):
                self.context.save_camera_configuration(11, 1, "Front", camera_name=name)
        self.assertEqual(self.context.camera_context(11)["camera_name"], "Hà Đông - Cửa vào")

    def test_entrance_validation_and_context_thread_nesting(self):
        with self.assertRaises(ValueError):
            self.context.validate_entrance_config({"x1": float("nan")})
        with self.assertRaises(ValueError):
            self.context.validate_entrance_config({"enabled": "false"})
        with self.assertRaises(ValueError):
            self.context.save_camera_configuration(11, 1, "", "false")
        with self.assertRaises(ValueError):
            self.context.validate_entrance_config({"roi": {"x1": .3, "y1": .3, "x2": .7, "y2": .7}})
        cfg = self.context.validate_entrance_config({"enabled": True, "secret": "not persisted", "roi": {"x1": 0., "y1": 0., "x2": 1., "y2": 1.}})
        self.assertNotIn("secret", cfg)
        saved = self.context.save_camera_configuration(11, 1, "Front", True, True, True, cfg)
        self.assertTrue(saved["visitor_counting_enabled"])
        snapshot = self.context.camera_context(11)
        thread_seen = []
        with self.context.camera_event_context(snapshot):
            snapshot["camera_name"] = "Mutated"
            thread = threading.Thread(target=lambda: thread_seen.append(self.context.event_attribution()))
            thread.start()
            thread.join()
            with self.context.camera_event_context(self.context.camera_context(12)):
                self.assertEqual(self.context.event_attribution()["camera_id"], 12)
            self.assertEqual(self.context.event_attribution()["camera_name"], "Entrance")
        self.assertIsNone(thread_seen[0]["camera_id"])
        self.assertIsNone(self.context.event_attribution()["camera_id"])

    def test_standalone_spoof_insert_snapshot_and_repeat_dedup(self):
        with self.context.camera_event_context(self.context.camera_context(11)):
            first = self.db.add_spoof_event("isolated", {"reason": "test"}, camera_source="Entrance")
            second = self.db.add_spoof_event("isolated", {"reason": "changed"}, camera_source="Entrance")
        self.assertEqual(first["id"], second["id"])
        row = self.db.fetchone("SELECT * FROM recognition_events WHERE id=?", (first["id"],))
        self.assertEqual((row["camera_id"], row["store_id"], row["camera_name"]), (11, 1, "Entrance"))
        self.assertEqual(row["status"], "SPOOF_BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
