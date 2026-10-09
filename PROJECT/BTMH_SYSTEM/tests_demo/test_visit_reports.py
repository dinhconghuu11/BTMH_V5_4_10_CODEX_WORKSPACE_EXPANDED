"""Phase G: scoped real SQLite aggregates and real assigned-shift attendance."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import types
import unittest
from zoneinfo import ZoneInfo

from test_demo_context import load_isolated_modules

SOURCE = Path(__file__).resolve().parents[1] / "module_app"


class VisitReportTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
        sys.modules[self.db.__package__ + ".config"].DATA_ROOT = Path(__file__).resolve().parent
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        raw.row_factory = sqlite3.Row
        self.addCleanup(raw.close)
        lock = threading.RLock()
        self.statements = []
        db = self.db

        class LoggedConnection(db._CompatConnection):
            def execute(adapter, sql, params=()):
                self.statements.append((sql, list(params)))
                return super().execute(sql, params)

        @contextmanager
        def memory_connection():
            with lock:
                try:
                    yield LoggedConnection(raw, "sqlite")
                    raw.commit()
                except Exception:
                    raw.rollback()
                    raise

        self.db.connection = memory_connection
        self.db.init_db()
        self.db.execute("CREATE TABLE runtime_settings(setting_key TEXT PRIMARY KEY,setting_value TEXT,updated_at TEXT)")
        self.db.execute("CREATE TABLE camera_devices(id INTEGER PRIMARY KEY,name TEXT,source TEXT,zone_name TEXT,enabled INTEGER,updated_at TEXT)")
        for name in ("shift_attendance", "platform_v5", "camera_appearances", "entrance_visits", "visit_reports"):
            spec = importlib.util.spec_from_file_location(self.db.__package__ + "." + name, SOURCE / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            setattr(self, name, module)
        self.platform_v5.CLIP_ROOT = types.SimpleNamespace(mkdir=lambda **kwargs: None)
        self.platform_v5._sync_event = lambda *args, **kwargs: None
        self.platform_v5.ensure_platform_v5_schema()
        self.context.ensure_demo_schema()
        self.camera_appearances.ensure_appearance_schema()
        self.entrance_visits.ensure_entrance_visits_schema()
        self.db.execute("UPDATE stores SET store_name='Current Store A' WHERE id=1")
        self.db.execute("INSERT INTO stores(id,store_code,store_name,timezone_name,created_at,updated_at) "
                        "VALUES(2,'S2','Current Store B','Asia/Ho_Chi_Minh','2026','2026')")
        self.db.execute("INSERT INTO camera_devices(id,name,source,zone_name,enabled,updated_at) VALUES"
                        "(11,'Door A','rtsp://operator:PRIVATE@camera.invalid/101','Front',1,'2026'),"
                        "(12,'Door B','rtsp://operator:OTHER_PRIVATE@camera.invalid/101','Rear',1,'2026')")
        self.enable(11, 1)
        self.context.save_camera_configuration(12, 2, "Rear", False, False, False)
        for employee, store in ((1, 1), (2, 2), (3, None)):
            self.db.execute("INSERT INTO students(id,student_code,full_name,class_name,faculty,consent_at,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,'2026','2026','2026')", (employee, f"EMP{employee}", f"Employee {employee}", "Role", "Team"))
            if store:
                self.db.execute("INSERT INTO employee_store_assignments VALUES(?,?,1,'2026')", (employee, store))
        self.now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
        self.counter = 0

    def enable(self, camera, store):
        return self.context.save_camera_configuration(camera, store, "Front", True, True, True,
                                                     {"enabled": True, "anchor": "face_center"})

    def visit(self, local="2026-10-08T09:00:00", *, store=1, camera=11, zone="Asia/Ho_Chi_Minh",
              status="VISITOR", name="Historical Store A", business_date=None, exited=None):
        stamp = datetime.fromisoformat(local)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo(zone))
        day = business_date or stamp.astimezone(ZoneInfo(zone)).date().isoformat()
        utc = stamp.astimezone(timezone.utc).isoformat()
        self.counter += 1
        self.db.execute("INSERT INTO entrance_visits(visit_id,participant_id,camera_id,store_id,camera_name,store_name,zone_name,"
                        "timezone_name,business_date,entered_at,exited_at,entry_track_ref,appearance_id,anchor_basis,visit_status,"
                        "confirmed_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"visit-{self.counter}", f"participant-{self.counter}", camera, store, "Historical Door", name, "Entry",
                         zone, day, utc, exited, "track", "appearance", "FACE", status, utc, utc, utc))
        return utc

    def report(self, date="2026-10-08", **kwargs):
        return self.visit_reports.query_visits_report(date, now=self.now, **kwargs)

    def management(self, date="2026-10-08", **kwargs):
        return self.visit_reports.query_management_summary(date, now=self.now, **kwargs)

    def event(self, *, store=1, student=1, status="RECOGNIZED", passed=True,
              day="2026-10-08", stamp="2026-10-08T02:00:00+00:00", detail=None):
        return self.db.execute("INSERT INTO recognition_events(student_id,camera_id,store_id,camera_name,store_name,zone_name,"
                               "status,anti_spoof_passed,event_at,business_date,detail_json,created_at,camera_source) "
                               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (student, 11, store, "Historical Door", "Historical Store A", "Entry", status, int(passed), stamp,
                                day, json.dumps(detail or {}), stamp, "rtsp://operator:INTERNAL_ONLY@camera.invalid/101"))

    def assign_shift(self, employee=1, store=1):
        shift = self.platform_v5.save_shift({"shift_code": f"D{store}", "shift_name": "Day", "store_id": store,
                                             "start_time": "08:00", "end_time": "17:30", "workdays": list(range(7)),
                                             "late_grace_minutes": 5, "early_leave_grace_minutes": 5}, "owner")
        self.platform_v5.assign_employee_shift(employee, shift["id"], "owner", "2026-10-01")
        return shift

    def test_valid_in_counts_exclude_reclassified_and_legacy_observations(self):
        self.visit()
        self.visit(status="EMPLOYEE")
        self.visit(status="SPOOF")
        self.visit("2026-10-07T09:00:00")
        self.visit("2026-10-06T09:00:00")
        self.db.execute("CREATE TABLE visitor_sessions(id INTEGER PRIMARY KEY,entry_at TEXT)")
        self.db.execute("INSERT INTO visitor_sessions VALUES(1,'2026-10-08')")
        result = self.report()
        self.assertEqual(result["totals"]["selected"], 1)
        self.assertEqual(result["totals"]["previous"], 1)
        self.assertFalse(result["legacy_observations_used"])
        self.assertEqual(result["source"], "ENTRANCE_VALID_IN")

    def test_zero_safe_comparisons_have_no_infinite_or_fake_percent(self):
        self.assertEqual(self.report()["totals"]["percent"], 0)
        self.visit()
        new = self.report()["totals"]
        self.assertIsNone(new["percent"])
        self.assertEqual(new["change_state"], "NEW_ACTIVITY")
        self.visit("2026-10-07T09:00:00")
        self.visit("2026-10-07T10:00:00")
        fallen = self.report()["totals"]
        self.assertEqual(fallen["percent"], -50)
        self.assertEqual(fallen["delta"], -1)

    def test_hour_buckets_follow_frozen_half_quarter_hour_timezones(self):
        self.visit("2026-10-07T18:45:00+00:00", zone="Asia/Kathmandu")  # local 00:30
        self.visit("2026-10-07T19:00:00+00:00", zone="Asia/Kolkata")   # local 00:30
        self.visit("2026-10-07T17:00:00+00:00")  # local VN midnight
        result = self.report()
        self.assertEqual(result["totals"]["selected"], 3)
        self.assertEqual(len(result["hourly"]), 24)
        self.assertEqual(result["hourly"][0]["selected"], 3)
        self.assertEqual(sum(row["selected"] for row in result["hourly"]), 3)

    def test_dst_repeated_local_hour_is_counted_twice_in_one_display_bucket(self):
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        self.visit("2026-11-01T05:30:00+00:00", zone="America/New_York")
        self.visit("2026-11-01T06:30:00+00:00", zone="America/New_York")
        result = self.report("2026-11-01")
        self.assertEqual(result["hourly"][1]["selected"], 2)
        self.assertEqual(result["totals"]["selected"], 2)

    def test_business_date_and_names_are_not_rewritten_by_current_store_mapping(self):
        self.visit("2026-10-08T09:00:00", name="Before rename", zone="Asia/Kathmandu", business_date="2026-10-07")
        self.visit("2026-10-08T10:00:00", name="Recorded name")
        self.db.execute("UPDATE stores SET store_name='New Current Name',timezone_name='UTC' WHERE id=1")
        result = self.report()
        row = next(row for row in result["stores"] if row["store_id"] == 1)
        self.assertEqual(row["store_name"], "Recorded name")
        self.assertEqual(row["previous_store_name"], "Before rename")
        self.assertEqual(row["current_store_name"], "New Current Name")
        self.assertEqual(row["hourly"][10]["selected"], 1)
        self.assertEqual(row["selected"], 1)
        self.assertEqual(row["previous"], 1)

    def test_scope_is_applied_in_sql_before_aggregate_and_camera_configuration(self):
        self.visit()
        self.visit(store=2, camera=12, name="Other Store")
        self.statements.clear()
        result = self.report(allowed_store_ids={1})
        self.assertEqual(result["totals"]["selected"], 1)
        self.assertEqual([row["store_id"] for row in result["stores"]], [1])
        visit_reads = [(sql, params) for sql, params in self.statements if "FROM entrance_visits" in sql]
        self.assertEqual(len(visit_reads), 1)
        self.assertIn("v.store_id IN (?)", visit_reads[0][0])
        self.assertEqual(visit_reads[0][1][0], 1)
        config_reads = [sql for sql, _ in self.statements if "FROM camera_devices" in sql]
        self.assertTrue(all("a.store_id IN (?)" in sql for sql in config_reads))
        self.assertFalse(any("source" in sql for sql, _ in self.statements))
        self.statements.clear()
        self.assertEqual(self.report(allowed_store_ids=set())["stores"], [])
        self.assertEqual(self.statements, [])
        with self.assertRaisesRegex(PermissionError, "STORE_SCOPE_DENIED"):
            self.report(allowed_store_ids={1}, store_id=2)

    def test_configuration_states_do_not_turn_historical_actual_counts_into_zero(self):
        self.visit(store=2, camera=12, name="Old Store B")
        partial = self.report()
        self.assertEqual(partial["configuration_state"], "PARTIAL")
        old = next(row for row in partial["stores"] if row["store_id"] == 2)
        self.assertEqual(old["selected"], 1)
        self.assertEqual(old["configuration_state"], "UNCONFIGURED")
        self.assertFalse(old["comparison_eligible"])
        self.enable(12, 2)
        self.assertEqual(self.report()["configuration_state"], "READY")
        self.db.execute("UPDATE camera_devices SET ai_enabled=0")
        result = self.report()
        self.assertEqual(result["configuration_state"], "UNCONFIGURED")
        self.assertEqual(result["totals"]["selected"], 1)
        self.assertIsNone(result["max_rise"])

    def test_ambiguous_or_invalid_camera_configuration_is_not_ready(self):
        self.db.execute("INSERT INTO camera_store_assignments VALUES(11,2,'2026')")
        self.assertEqual(self.report(allowed_store_ids={1})["configuration_state"], "UNCONFIGURED")
        self.db.execute("DELETE FROM camera_store_assignments WHERE camera_device_id=11 AND store_id=2")
        self.db.execute("UPDATE camera_devices SET entrance_config_json=? WHERE id=11", ('{"enabled":true,"x1":"bad"}',))
        self.assertEqual(self.report(allowed_store_ids={1})["configuration_state"], "UNCONFIGURED")

    def test_extremes_use_configured_sources_and_zero_safe_values(self):
        self.visit()
        for _ in range(4):
            self.visit(store=2, camera=12, name="Other Store")
        result = self.report()
        self.assertEqual(result["max_rise"]["store_id"], 1)
        self.assertIsNone(result["max_rise"]["percent"])
        self.assertIsNone(result["max_fall"])
        self.enable(12, 2)
        self.assertEqual(self.report()["max_rise"]["store_id"], 2)

    def test_unknown_hour_data_is_counted_but_not_falsely_ranked(self):
        self.visit(zone="Asia/Ho_Chi_Minh")
        self.db.execute("UPDATE entrance_visits SET timezone_name='INVALID/TIMEZONE'")
        result = self.report(allowed_store_ids={1})
        self.assertEqual(result["totals"]["selected"], 1)
        self.assertEqual(result["stores"][0]["hourly_unknown"], 1)
        self.assertIsNone(result["max_rise"])

    def test_current_day_is_partial_future_rows_are_excluded_and_dates_validated(self):
        self.visit("2026-10-08T23:00:00")  # after injected now
        result = self.report(allowed_store_ids={1})
        self.assertTrue(result["selected_day_in_progress"])
        self.assertEqual(result["totals"]["selected"], 0)
        self.assertEqual(result["comparison_mode"], "DAY_TOTALS")
        self.assertFalse(result["historical_coverage_known"])
        for bad in ("2026-1-01", "2026-02-29", "0001-01-01", "x", True):
            with self.assertRaises(ValueError):
                self.report(bad)
        with self.assertRaisesRegex(ValueError, "TIMEZONE_REQUIRED"):
            self.visit_reports.query_visits_report(now=datetime(2026, 10, 8))
        with self.assertRaises(ValueError):
            self.report(store_id=True)

    def test_report_indexes_are_idempotent(self):
        self.entrance_visits.ensure_entrance_visits_schema()
        names = {row["name"] for row in self.db.fetchall("PRAGMA index_list(entrance_visits)")}
        self.assertIn("idx_entrance_visits_store_date_status", names)
        self.assertIn("idx_entrance_visits_date_status", names)

    def test_management_uses_real_shift_report_not_recognition_as_attendance(self):
        self.assign_shift()
        self.event()  # recognition evidence is not a trusted gate IN
        self.now = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)  # local16 before end
        before = self.management(allowed_store_ids={1})
        self.assertEqual(before["attendance"]["scheduled_shifts"], 1)
        self.assertEqual(before["attendance"]["absent_days"], 0)
        self.assertEqual(before["attendance"]["present_shifts"], 0)
        self.assertTrue(before["attendance"]["configured"])
        self.assertEqual(before["employee_with_valid_data_today"], 1)
        self.now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
        self.assertEqual(self.management(allowed_store_ids={1})["attendance"]["absent_days"], 1)
        context = self.context.camera_context(11)
        self.shift_attendance.register_attendance_in(1, context, "2026-10-08T01:06:00+00:00", source_type="GATE_IN")
        admitted = self.management(allowed_store_ids={1})
        self.assertEqual(admitted["attendance"]["present_shifts"], 1)
        self.assertEqual(admitted["attendance"]["late_cases"], 1)
        self.assertEqual(admitted["attendance"]["missing_out"], 1)
        self.assertEqual(admitted["attendance"]["absent_days"], 0)
        self.assertNotIn("working_hours", admitted)
        self.assertNotIn("employee_present_now", admitted)

    def test_management_events_employees_and_incidents_are_scoped_in_sql(self):
        allowed = self.event()
        self.event(store=2, student=2)
        self.event(store=None, student=3, day=None)
        self.event(status="RECOGNIZED", passed=False)
        self.event(status="UNREGISTERED", student=None, passed=False)
        self.event(status="SPOOF_BLOCKED", passed=False)
        self.db.execute("INSERT INTO face_templates(student_id,embedding_blob,created_at,updated_at) VALUES(?,?,?,?)", (1, b"private-vector", "2026", "2026"))
        self.db.execute("INSERT INTO face_templates(student_id,embedding_blob,created_at,updated_at) VALUES(?,?,?,?)", (2, b"other-private-vector", "2026", "2026"))
        for code, store, status in (("A", 1, "OPEN"), ("B", 2, "OPEN"), ("U", None, "OPEN"), ("C", 1, "CLOSED")):
            self.db.execute("INSERT INTO incidents(incident_id,store_id,title,status,occurred_at,created_by,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,'owner','2026','2026')", (code, store, "Case", status, "2026-10-08"))
        self.statements.clear()
        result = self.management(allowed_store_ids={1})
        self.assertEqual(result["employee_with_valid_data_today"], 1)
        self.assertEqual(result["recognition"], {"recognized_events": 1, "unknown_events": 1, "spoof_blocked_events": 1})
        self.assertEqual(result["employees"], {"total": 1, "faceid": 1, "faceid_coverage_percent": 100})
        self.assertEqual(result["incidents"]["open"], 1)
        self.assertTrue(result["incidents"]["count_known"])
        self.assertTrue(all(row["store_id"] == 1 for row in result["latest"]))
        self.assertIn(allowed, [row["id"] for row in result["latest"]])
        relevant = [(sql, params) for sql, params in self.statements if "FROM recognition_events e" in sql or "FROM incidents i" in sql]
        self.assertTrue(all("store_id IN (?)" in sql and params[0] == 1 for sql, params in relevant))
        global_result = self.management()
        self.assertEqual(global_result["employee_with_valid_data_today"], 3)
        self.assertEqual(global_result["incidents"]["open"], 3)
        self.assertEqual(global_result["employees"]["total"], 3)

    def test_management_latest_is_bounded_and_detail_is_internal_only(self):
        for _ in range(15):
            self.event(detail={"appearance_timezone": "Asia/Ho_Chi_Minh", "server_only": "internal"})
        self.db.execute("UPDATE students SET full_name='rtsp://user:private@camera.invalid/101' WHERE id=1")
        result = self.management(allowed_store_ids={1})
        self.assertEqual(len(result["latest"]), 12)
        self.assertEqual(result["recognition"]["recognized_events"], 15)
        self.assertEqual(result["employee_with_valid_data_today"], 1)
        self.assertTrue(all("detail_json" in row and "camera_source" not in row for row in result["latest"]))
        self.assertTrue(all(row["full_name"] == "[redacted]" for row in result["latest"]))
        self.assertNotIn("INTERNAL_ONLY", json.dumps(result))
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_management_legacy_date_window_and_frozen_business_date(self):
        self.event(day=None, stamp="2026-10-07T16:59:59+00:00")
        first = self.event(day=None, stamp="2026-10-07T17:00:00+00:00")
        frozen_other_day = self.event(day="2026-10-07", stamp="2026-10-08T02:00:00+00:00")
        result = self.management(allowed_store_ids={1})
        self.assertEqual(result["recognition"]["recognized_events"], 1)
        self.assertEqual([row["id"] for row in result["latest"]], [first])
        self.assertNotIn(frozen_other_day, [row["id"] for row in result["latest"]])

    def test_management_missing_incident_scope_is_unknown_not_guessed(self):
        self.db.execute("DROP TABLE incidents")
        self.db.execute("CREATE TABLE incidents(incident_id TEXT PRIMARY KEY,status TEXT,employee_id INTEGER)")
        self.db.execute("INSERT INTO incidents VALUES('X','OPEN',1)")
        result = self.management(allowed_store_ids={1})
        self.assertIsNone(result["incidents"]["open"])
        self.assertFalse(result["incidents"]["count_known"])
        self.assertEqual(self.management()["incidents"]["open"], 1)

    def test_management_empty_scope_has_no_data_queries_or_global_fallback(self):
        self.event()
        self.statements.clear()
        result = self.management(allowed_store_ids=set())
        self.assertEqual(result["employee_with_valid_data_today"], 0)
        self.assertFalse(result["attendance"]["configured"])
        self.assertEqual(result["latest"], [])
        self.assertEqual(self.statements, [])
        with self.assertRaisesRegex(PermissionError, "STORE_SCOPE_DENIED"):
            self.management(allowed_store_ids={1}, store_id=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
