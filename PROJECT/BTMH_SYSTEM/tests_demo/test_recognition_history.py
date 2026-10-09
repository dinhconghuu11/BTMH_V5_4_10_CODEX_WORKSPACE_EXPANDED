"""Focused history SQL/scoping tests; pure in-memory SQLite, no customer DB."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import unittest

from test_demo_context import load_isolated_modules

SOURCE = Path(__file__).resolve().parents[1] / "module_app"


class RecognitionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(raw.close)
        lock = threading.RLock()
        self.statements = []
        db = self.db

        class LoggedConnection(db._CompatConnection):
            def execute(adapter, sql, params=()):
                self.statements.append((sql, list(params)))
                return super().execute(sql, params)

        @contextmanager
        def connection():
            with lock:
                try:
                    yield LoggedConnection(raw, "sqlite")
                    raw.commit()
                except Exception:
                    raw.rollback()
                    raise

        self.db.connection = connection
        self.db.init_db()
        with self.db.connection() as conn:
            conn.executescript("""
                CREATE TABLE stores(id INTEGER PRIMARY KEY,store_name TEXT,timezone_name TEXT);
                CREATE TABLE camera_devices(id INTEGER PRIMARY KEY,name TEXT,source TEXT,zone_name TEXT,enabled INTEGER,updated_at TEXT);
                CREATE TABLE camera_store_assignments(camera_device_id INTEGER,store_id INTEGER,created_at TEXT);
                CREATE TABLE employee_store_assignments(student_id INTEGER,store_id INTEGER,is_primary INTEGER,created_at TEXT);
                CREATE TABLE employee_shift_assignment_history(student_id INTEGER,store_id INTEGER,effective_from TEXT);
                INSERT INTO stores VALUES(1,'Store A','Asia/Ho_Chi_Minh'),(2,'Store B','Asia/Ho_Chi_Minh');
                INSERT INTO camera_devices VALUES(11,'Current moved camera','rtsp://secret:password@camera.invalid/101','Current zone',1,'2026');
                INSERT INTO camera_devices VALUES(12,'Second camera','rtsp://private@camera.invalid/101','Second zone',1,'2026');
                INSERT INTO camera_store_assignments VALUES(11,2,'2026'),(12,2,'2026');
                INSERT INTO employee_store_assignments VALUES(1,1,1,'2026'),(2,2,1,'2026');
                INSERT INTO employee_shift_assignment_history VALUES(3,1,'2026-01-01');
            """)
        for employee, name, department in ((1, "Employee One", "Department A"), (2, "Employee Two", "Department B"),
                                            (3, "History employee", "Department C"), (4, "Legacy unassigned", "Private department")):
            self.db.execute("INSERT INTO students(id,student_code,full_name,faculty,class_name,consent_at,created_at,updated_at) VALUES(?,?,?,?,?,'2026','2026','2026')",
                            (employee, f"EMP{employee}", name, department, "Position"))
        self.context.ensure_demo_schema()
        for name in ("camera_appearances", "recognition_history"):
            spec = importlib.util.spec_from_file_location(self.db.__package__ + "." + name, SOURCE / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            setattr(self, name, module)
        self.camera_appearances.ensure_appearance_schema()
        self.manager = {"role": "MANAGER", "store_id": 1}

    def add(self, *, day="2026-10-08", event_at="2026-10-08T02:00:00+00:00", store=1, camera=11,
            status="RECOGNIZED", student=1, passed=True, zone="Old zone", store_name="Old Store A", camera_name="Old camera", detail=None):
        return self.db.execute("INSERT INTO recognition_events(student_id,camera_id,store_id,zone_name,store_name,camera_name,"
                               "status,anti_spoof_passed,event_at,business_date,detail_json,created_at,camera_source) "
                               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (student, camera, store, zone, store_name, camera_name, status, int(passed), event_at,
                                day, json.dumps(detail or {}), event_at, "rtsp://never-search:private@camera.invalid/101"))

    def query(self, start="2026-10-08", end=None, **kwargs):
        return self.recognition_history.query_recognition_history(start, end or start, **kwargs)

    def test_scope_is_in_sql_before_count_and_read_legacy_unknown_attribution(self):
        allowed = self.add()
        self.add(store=2, student=2)
        legacy = self.add(store=None, camera=None, day=None, student=4)
        self.statements.clear()
        restricted = self.query(allowed_store_ids={1})
        self.assertEqual([row["id"] for row in restricted["items"]], [allowed])
        self.assertEqual(restricted["total"], 1)
        reads = [(sql, params) for sql, params in self.statements if "SELECT" in sql and "recognition_events" in sql]
        self.assertEqual(len(reads), 2)
        self.assertTrue(all("e.store_id IN (?)" in sql and params[0] == 1 for sql, params in reads))
        global_rows = self.query()
        self.assertEqual(global_rows["total"], 3)
        self.assertIn(legacy, [row["id"] for row in global_rows["items"]])
        self.statements.clear()
        self.assertEqual(self.query(allowed_store_ids=set())["items"], [])
        self.assertEqual(self.statements, [])
        with self.assertRaisesRegex(PermissionError, "STORE_SCOPE_DENIED"):
            self.query(allowed_store_ids={1}, store_id=2)

    def test_historical_camera_filter_uses_frozen_store_after_move(self):
        old = self.add()
        self.add(store=2, zone="Current zone", camera_name="Current moved camera", store_name="Store B")
        self.statements.clear()
        page = self.query(allowed_store_ids={1}, store_id=1, camera_id=11, zone_name="Old zone")
        self.assertEqual([row["id"] for row in page["items"]], [old])
        self.assertEqual(page["items"][0]["store_name"], "Old Store A")
        self.assertFalse(any("camera_devices" in sql or "camera_store_assignments" in sql for sql, _ in self.statements))
        self.assertEqual(self.query(allowed_store_ids={1}, zone_name="Current zone")["total"], 0)

    def test_new_appearance_business_date_overrides_utc_and_mutable_location(self):
        # Camera-local first appearance date can differ from VN report calendar.
        frozen = self.add(day="2026-10-07", event_at="2026-10-08T02:00:00+00:00")
        self.assertEqual(self.query("2026-10-07")["items"][0]["id"], frozen)
        self.assertEqual(self.query("2026-10-08")["total"], 0)
        self.db.execute("UPDATE camera_devices SET name='Renamed again',zone_name='New zone' WHERE id=11")
        self.assertEqual(self.query("2026-10-07")["items"][0]["camera_name"], "Old camera")

    def test_legacy_window_is_vietnam_calendar_inclusive_and_no_backfill(self):
        previous = self.add(day=None, event_at="2026-10-07T16:59:59.999999+00:00")
        first = self.add(day=None, event_at="2026-10-07T17:00:00+00:00")
        last = self.add(day=None, event_at="2026-10-08T16:59:59.999999+00:00")
        following = self.add(day=None, event_at="2026-10-08T17:00:00+00:00")
        page = self.query()
        self.assertEqual({row["id"] for row in page["items"]}, {first, last})
        self.assertNotIn(previous, [row["id"] for row in page["items"]])
        self.assertNotIn(following, [row["id"] for row in page["items"]])
        self.assertTrue(all(row["business_date"] is None for row in page["items"]))

    def test_month_year_leap_boundaries_and_date_range_validation(self):
        leap = self.add(day="2024-02-29")
        march = self.add(day="2024-03-01")
        self.assertEqual(self.query("2024-02-01", "2024-02-29")["items"][0]["id"], leap)
        self.assertEqual(self.query("2024-01-01", "2024-12-31")["total"], 2)
        self.assertEqual(self.query("2024-03-01")["items"][0]["id"], march)
        for start, end in (("2023-02-29", "2023-03-01"), ("2026-1-01", "2026-01-02"),
                           ("2026-10-09", "2026-10-08"), ("2024-01-01", "2025-01-01")):
            with self.assertRaises(ValueError):
                self.query(start, end)

    def test_subject_classification_and_result_whitelist(self):
        employee = self.add()
        visitor = self.add(status="UNREGISTERED", student=None, passed=False)
        spoof = self.add(status="SPOOF_BLOCKED", student=1, passed=False)
        pending = self.add(status="ANALYZING", student=None, passed=False)
        invalid = self.add(status="RECOGNIZED", student=1, passed=False)
        deleted = self.add(status="RECOGNIZED", student=None, passed=True)
        legacy = self.add(status="LEGACY_REVIEW", student=None, passed=False)
        self.assertEqual([row["id"] for row in self.query(subject_type="EMPLOYEE")["items"]], [employee])
        self.assertEqual([row["id"] for row in self.query(subject_type="VISITOR")["items"]], [visitor])
        self.assertEqual({row["id"] for row in self.query(subject_type="UNKNOWN")["items"]}, {spoof, pending, invalid, deleted, legacy})
        self.assertEqual(self.query(result="SPOOF_BLOCKED")["items"][0]["id"], spoof)
        self.assertEqual(self.query(subject_type="EMPLOYEE", result="SPOOF_BLOCKED")["total"], 0)
        with self.assertRaises(ValueError): self.query(result="PENDING")
        with self.assertRaises(ValueError): self.query(subject_type="CUSTOMER_SQL")

    def test_filters_employee_store_zone_and_search_safe_snapshot_fields(self):
        first = self.add(student=1, camera=11, zone="Gold counter", camera_name="Legacy Main", store_name="Legacy Shop")
        self.add(student=2, store=2, camera=12, zone="Silver counter")
        page = self.query(store_id=1, employee_id=1, camera_id=11, zone_name="Gold counter", search="EMP1", result="RECOGNIZED")
        self.assertEqual(page["items"][0]["id"], first)
        for term in ("Employee One", "Legacy Main", "Legacy Shop", "Gold counter", "Department A"):
            self.assertEqual(self.query(search=term)["items"][0]["id"], first)
        self.assertEqual(self.query(search="never-search")["total"], 0)

    def test_sql_injection_and_wildcards_are_literal_not_executable(self):
        literal = self.add(camera_name="Sales 100%_Store")
        self.add(camera_name="Sales 100X-Store")
        self.assertEqual(self.query(search="100%_")["items"][0]["id"], literal)
        self.assertEqual(self.query(search="100%_")["total"], 1)
        self.assertEqual(self.query(search="' OR 1=1; DROP TABLE students; --")["total"], 0)
        self.assertEqual(self.query(zone_name="' OR 1=1--")["total"], 0)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM students")["n"], 4)
        self.add(detail={"private_note": "secret-evidence-search"})
        self.assertEqual(self.query(search="secret-evidence-search")["total"], 0)

    def test_vietnamese_search_case_folding_works_offline_in_sqlite(self):
        self.db.execute("UPDATE students SET full_name='Đặng Ngọc Ước' WHERE id=1")
        expected = self.add(camera_name="QUẦY VÀNG")
        self.assertEqual(self.query(search="đặng ngọc ước")["items"][0]["id"], expected)
        self.assertEqual(self.query(search="quầy vàng")["items"][0]["id"], expected)

    def test_count_before_offset_and_keyset_pagination_no_duplicate_or_truncated_export(self):
        ids = [self.add() for _ in range(13)]
        first = self.query(limit=5)
        self.assertEqual((first["total"], first["limit"], first["offset"]), (13, 5, 0))
        self.assertEqual([row["id"] for row in first["items"]], list(reversed(ids[-5:])))
        offset = self.query(limit=5, offset=5)
        keyset = self.query(limit=5, before_id=min(row["id"] for row in first["items"]))
        self.assertEqual([row["id"] for row in offset["items"]], [row["id"] for row in keyset["items"]])
        self.assertEqual(keyset["total"], 13)
        collected, cursor = [], None
        while True:
            page = self.query(limit=5, before_id=cursor)
            if not page["items"]: break
            collected.extend(row["id"] for row in page["items"])
            cursor = min(row["id"] for row in page["items"])
        self.assertEqual(collected, list(reversed(ids)))
        self.assertEqual(self.query(limit=1000)["limit"], 200)
        self.assertEqual(self.query(offset=100)["total"], 13)
        self.assertEqual(self.query(offset=100)["items"], [])

    def test_invalid_numeric_or_text_filters_are_rejected(self):
        for kwargs in ({"camera_id": "11 OR 1=1"}, {"store_id": 0}, {"employee_id": True}, {"before_id": -2},
                       {"limit": 0}, {"offset": -1}, {"zone_name": "z" * 121}, {"search": "s" * 201}):
            with self.assertRaises(ValueError): self.query(**kwargs)
        for day in ("0001-01-01", "9999-12-31"):
            with self.assertRaises(ValueError): self.query(day)

    def test_options_union_historical_camera_after_move_and_sql_scope(self):
        self.add()
        self.add(store=2, camera=12, zone="Second zone", camera_name="Second camera", store_name="Store B")
        self.statements.clear()
        options = self.recognition_history.recognition_filter_options(self.manager)
        self.assertEqual(options["stores"], [{"id": 1, "store_name": "Store A"}])
        self.assertEqual(options["zones"], [{"store_id": 1, "zone_name": "Old zone"}])
        self.assertEqual(options["cameras"], [{"id": 11, "camera_id": 11, "camera_name": "Old camera", "store_id": 1, "zone_name": "Old zone"}])
        self.assertFalse(any("source" in key or "detail" in key for item in options["cameras"] for key in item))
        event_read = next((sql, params) for sql, params in self.statements if "SELECT DISTINCT e.store_id" in sql)
        self.assertIn("e.store_id IN (?)", event_read[0])
        self.assertEqual(event_read[1], [1])
        self.assertNotIn("rtsp:", json.dumps(options))

    def test_employee_options_use_current_assignment_effective_history_and_scoped_events(self):
        self.add(student=2)  # Store B employee historically recognized at A.
        self.add(student=4, store=None, camera=None, day=None)
        restricted = self.recognition_history.recognition_filter_options(self.manager)
        self.assertEqual({item["id"] for item in restricted["employees"]}, {1, 2, 3})
        self.assertEqual({item["department"] for item in restricted["departments"]}, {"Department A", "Department B", "Department C"})
        self.assertTrue(all(item["department"] == item["faculty"] for item in restricted["employees"]))
        global_options = self.recognition_history.recognition_filter_options({"role": "ADMIN"})
        self.assertEqual(len(global_options["employees"]), 4)
        self.assertTrue(any(item["camera_name"] == "Current moved camera" for item in global_options["cameras"]))
        self.assertEqual(self.recognition_history.recognition_filter_options({"role": "MANAGER", "store_id": None}),
                         {"stores": [], "zones": [], "cameras": [], "employees": [], "departments": []})

    def test_deleted_camera_store_snapshots_and_ambiguous_current_camera_options(self):
        self.add(camera=99, camera_name="Deleted camera", store=1, zone="Historical zone")
        self.add(camera=100, store=3, store_name="Deleted Store", camera_name="Historic third", zone="Historic zone")
        self.db.execute("INSERT INTO camera_store_assignments VALUES(12,1,'2026')")
        restricted = self.recognition_history.recognition_filter_options(self.manager)
        self.assertTrue(any(item["id"] == 99 for item in restricted["cameras"]))
        self.assertFalse(any(item["id"] == 12 for item in restricted["cameras"]))
        global_options = self.recognition_history.recognition_filter_options({"role": "SUPER_ADMIN"})
        self.assertIn({"id": 3, "store_name": "Deleted Store"}, global_options["stores"])
        self.assertEqual(self.query(store_id=3, camera_id=100)["total"], 1)

    def test_option_names_are_redacted_and_legacy_z_timestamp_boundary_supported(self):
        inside = self.add(day=None, event_at="2026-10-07T17:00:00Z", camera=99,
                          camera_name="rtsp://user:secret@camera.invalid/101", zone="192.0.2.4")
        self.add(day=None, event_at="2026-10-08T17:00:00Z", camera=100)
        self.assertEqual([item["id"] for item in self.query()["items"]], [inside])
        options = self.recognition_history.recognition_filter_options(self.manager)
        serialized = json.dumps(options)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("192.0.2.4", serialized)
        self.assertIn("[redacted]", serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
