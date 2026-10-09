"""Run directly: real in-memory SQLite transactions, no camera/models/customer data."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import types
import unittest

from test_demo_context import load_isolated_modules

SOURCE = Path(__file__).resolve().parents[1] / "module_app"


def at(text="2026-10-08T02:00:00+00:00"):
    return datetime.fromisoformat(text)


class CameraAppearanceTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(raw.close)
        lock = threading.RLock()

        @contextmanager
        def connection():
            with lock:
                try:
                    yield self.db._CompatConnection(raw, "sqlite")
                    raw.commit()
                except Exception:
                    raw.rollback()
                    raise

        self.db.connection = connection
        self.db.init_db()
        self.db.execute("INSERT INTO students(id,student_code,full_name,consent_at,created_at,updated_at) VALUES(1,'E1','Employee','2026','2026','2026')")
        # Attribution migration inspects camera_devices but never creates cameras.
        self.context.ensure_demo_schema()
        spec = importlib.util.spec_from_file_location(self.db.__package__ + ".camera_appearances", SOURCE / "camera_appearances.py")
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)
        self.module.ensure_appearance_schema()
        self.manager = self.module.AppearanceManager()
        self.module.APPEARANCES = self.manager
        self.camera = {"camera_id": 11, "store_id": 1, "camera_name": "Entrance", "store_name": "Store A",
                       "zone_name": "Door", "timezone_name": "Asia/Ho_Chi_Minh"}
        self.bbox = (100, 100, 80, 80)

    def prepare(self, assignments=None, stamp=None, camera=None, owner="pipeline-1", manager=None):
        with (manager or self.manager).frame(camera or self.camera, owner, stamp or at()) as frame:
            return frame.prepare(assignments if assignments is not None else [(1, self.bbox)], 1000, 1000)

    def row(self, event_id):
        return self.db.fetchone("SELECT * FROM recognition_events WHERE id=?", (event_id,))

    def test_schema_idempotence_and_legacy_rows_stay_unnumbered(self):
        self.db.execute("INSERT INTO recognition_events(track_id,status,event_at,created_at) VALUES('legacy','UNREGISTERED','2026','2026')")
        self.module.ensure_appearance_schema()
        self.module.ensure_appearance_schema()
        legacy = self.db.fetchone("SELECT * FROM recognition_events WHERE track_id='legacy'")
        self.assertIsNone(legacy["appearance_id"])
        self.assertIsNone(legacy["business_date"])
        self.assertIsNone(legacy["daily_sequence"])
        self.assertEqual(self.db.fetchall("SELECT * FROM camera_appearance_counters"), [])
        indexes = self.db.fetchall("PRAGMA index_list(recognition_events)")
        self.assertTrue(any(row["name"] == "idx_recognition_camera_day_sequence" and row["unique"] for row in indexes))

    def test_allocation_analyzing_immutable_attribution_and_monotonic_event_id(self):
        self.db.execute("INSERT INTO recognition_events(track_id,event_at,created_at) VALUES('legacy','2026','2026')")
        first = self.prepare()[1]
        row = self.row(first["event_id"])
        self.assertEqual((row["status"], row["daily_sequence"], row["direction"]), ("ANALYZING", 1, "OBSERVATION"))
        self.assertEqual(row["event_at"], at().isoformat())
        self.assertEqual((row["camera_id"], row["store_id"], row["zone_name"]), (11, 1, "Door"))
        moved = {**self.camera, "store_id": 2, "camera_name": "Renamed", "store_name": "Store B"}
        same = self.prepare(stamp=at() + timedelta(seconds=.2), camera=moved)[1]
        self.assertEqual(same, first)
        self.assertEqual(self.row(first["event_id"])["store_id"], 1)
        next_day = self.prepare(stamp=at() + timedelta(days=1))[1]
        self.assertEqual(next_day["daily_sequence"], 1)
        self.assertGreater(next_day["event_id"], first["event_id"])

    def test_unknown_to_verified_same_event_verification_timestamp_and_repeated_no_mutation(self):
        with self.manager.frame(self.camera, "pipeline-1", at()) as frame:
            first = frame.prepare([(1, self.bbox)], 1000, 1000)[1]
            unknown = self.db.add_unknown_event("camera-11:1", {"reason": "UNKNOWN"}, camera_source="Entrance")
            self.assertFalse(unknown["deduplicated"])
            self.assertEqual(unknown["id"], first["event_id"])
        evidence = json.loads(self.row(first["event_id"])["detail_json"])
        evidence["snapshot_path"] = "evidence/existing.jpg"
        self.db.execute("UPDATE recognition_events SET detail_json=? WHERE id=?", (json.dumps(evidence), first["event_id"]))
        verified_at = at() + timedelta(seconds=.5)
        with self.manager.frame(self.camera, "pipeline-1", verified_at) as frame:
            frame.prepare([(1, self.bbox)], 1000, 1000)
            verified = self.db.add_event(1, "camera-11:g3:1", .92, {"reason": "PASS", "snapshot_path": "new.jpg"})
            self.assertFalse(verified["deduplicated"])
            self.assertEqual(verified["id"], first["event_id"])
            self.assertEqual(verified["event_at"], at().isoformat())
            self.assertEqual(verified["recognized_at"], verified_at.isoformat())
            stored = self.row(first["event_id"])
            self.assertEqual(json.loads(stored["detail_json"])["snapshot_path"], "evidence/existing.jpg")
            repeated = self.db.add_event(1, "camera-11:1", .99, {"reason": "new wording"})
            self.assertTrue(repeated["deduplicated"])
            self.assertEqual(self.row(first["event_id"]), stored)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM recognition_events")["n"], 1)

    def test_confirmed_spoof_cannot_be_downgraded_by_unknown(self):
        with self.manager.frame(self.camera, "pipeline-1", at()) as frame:
            frame.prepare([(1, self.bbox)], 1000, 1000)
            spoof = self.db.add_spoof_event("camera-11:1", {"reason": "SPOOF"})
            unknown = self.db.add_unknown_event("camera-11:1", {"reason": "UNKNOWN"})
            self.assertEqual(unknown["status"], "SPOOF_BLOCKED")
            self.assertTrue(unknown["deduplicated"])
            self.assertEqual(spoof["id"], unknown["id"])

    def test_daily_sequence_resets_at_camera_local_midnight_camera_and_owner_isolation(self):
        before = at("2026-10-08T16:59:59.800000+00:00")
        previous = self.prepare(stamp=before)[1]
        second = self.prepare([(2, (700, 100, 80, 80))], stamp=before + timedelta(seconds=.1))[2]
        self.assertEqual((previous["business_date"], previous["daily_sequence"], second["daily_sequence"]), ("2026-10-08", 1, 2))
        tomorrow = self.prepare(stamp=before + timedelta(seconds=.3))[1]
        self.assertEqual((tomorrow["business_date"], tomorrow["daily_sequence"]), ("2026-10-09", 1))
        other_camera = self.prepare(stamp=before, camera={**self.camera, "camera_id": 12})[1]
        self.assertEqual(other_camera["daily_sequence"], 1)
        reset_owner = self.prepare(stamp=before + timedelta(seconds=.05), owner="pipeline-2")[1]
        self.assertEqual(reset_owner["daily_sequence"], 3)
        self.assertNotEqual(previous["appearance_id"], reset_owner["appearance_id"])

    def test_timezone_not_utc_controls_business_date(self):
        stamp = at("2026-10-08T01:00:00+00:00")
        west = self.prepare(stamp=stamp, camera={**self.camera, "timezone_name": "America/New_York"})[1]
        self.assertEqual(west["business_date"], "2026-10-07")
        missing_timezone = self.prepare(stamp=stamp, camera={**self.camera, "camera_id": 12, "timezone_name": None})[1]
        self.assertEqual(missing_timezone["business_date"], "2026-10-08")

    def test_midnight_cached_verified_and_final_unknown_states_finish_new_daily_rows(self):
        before = at("2026-10-08T16:59:59.900000+00:00")
        tracks = [{"track_id": 1, "recognized": True, "student_id": 1, "confidence": .95,
                   "liveness": {"status": "PASS", "score": .99}, "stale": False},
                  {"track_id": 2, "unknown": True, "status": "UNREGISTERED", "liveness": {"status": "PASS"}}]
        assignments = [(1, self.bbox), (2, (700, 100, 80, 80))]
        with self.manager.frame(self.camera, "pipeline-1", before) as frame:
            previous = frame.prepare(assignments, 1000, 1000)
            frame.annotate({"tracks": tracks})
        after = before + timedelta(seconds=.2)
        with self.manager.frame(self.camera, "pipeline-1", after) as frame:
            current = frame.prepare(assignments, 1000, 1000)
            frame.annotate({"tracks": tracks})
            self.assertEqual(self.row(current[1]["event_id"])["status"], "RECOGNIZED")
            self.assertEqual(self.row(current[2]["event_id"])["status"], "UNREGISTERED")
            self.assertEqual(json.loads(self.row(current[1]["event_id"])["detail_json"])["recognized_at"], after.isoformat())
            self.assertNotEqual(current[1]["event_id"], previous[1]["event_id"])
            # Stable accepted state adds no SQL in the annotation path.
            old_connection = self.db.connection

            @contextmanager
            def forbid_sql():
                raise AssertionError("cached classification must not open SQL")
                yield

            self.db.connection = forbid_sql
            try:
                frame.annotate({"tracks": tracks})
            finally:
                self.db.connection = old_connection

    def test_cached_state_sync_rejects_stale_grace_and_contradictory_spoof(self):
        assignments = [(i, (100 * i, 100, 80, 80)) for i in range(1, 6)]
        tracks = [{"track_id": i, "recognized": True, "student_id": 1, "liveness": {"status": "PASS"}} for i in range(1, 6)]
        tracks[0]["stale"] = True
        tracks[1]["tracking_grace"] = True
        tracks[2]["observation_age_ms"] = 100
        tracks[3]["liveness"]["status"] = "PENDING"
        tracks[4]["spoof_blocked"] = True
        with self.manager.frame(self.camera, "pipeline-1", at()) as frame:
            values = frame.prepare(assignments, 1000, 1000)
            frame.annotate({"tracks": tracks})
        self.assertEqual([self.row(values[i]["event_id"])["status"] for i in range(1, 5)], ["ANALYZING"] * 4)
        self.assertEqual(self.row(values[5]["event_id"])["status"], "SPOOF_BLOCKED")

    def test_short_loss_uniquely_reacquires_with_resolution_independent_geometry(self):
        previous = self.prepare()[1]
        with self.manager.frame(self.camera, "pipeline-1", at() + timedelta(seconds=.7)) as frame:
            # Same normalized bbox, actual WalkBy Track/FaceObservation shape.
            values = frame.prepare([(types.SimpleNamespace(id=8), types.SimpleNamespace(bbox=(52, 50, 40, 40)))], 500, 500)
            self.assertEqual(values[8]["appearance_id"], previous["appearance_id"])
            result = {"tracks": [{"track_id": 8, "recognized": False}, {"track_id": 1, "stale": True}]}
            frame.annotate(result)
            self.assertEqual(result["tracks"][0]["daily_sequence"], 1)
            self.assertNotIn("daily_sequence", result["tracks"][1])
        distant = self.prepare([(9, (800, 700, 80, 80))], stamp=at() + timedelta(seconds=.8))[9]
        self.assertEqual(distant["daily_sequence"], 2)

    def test_long_loss_and_ambiguous_crowd_get_new_appearance(self):
        first = self.prepare([(1, self.bbox), (2, (120, 100, 80, 80))])
        ambiguous = self.prepare([(3, (110, 100, 80, 80))], stamp=at() + timedelta(seconds=.2))[3]
        self.assertNotIn(ambiguous["appearance_id"], [item["appearance_id"] for item in first.values()])
        long_lost = self.prepare([(4, self.bbox)], stamp=at() + timedelta(seconds=4))[4]
        self.assertNotEqual(long_lost["appearance_id"], first[1]["appearance_id"])
        self.assertEqual(long_lost["daily_sequence"], 4)

    def test_visible_person_and_new_track_never_share_appearance(self):
        first = self.prepare()[1]
        both = self.prepare([(1, self.bbox), (2, (105, 100, 80, 80))], stamp=at() + timedelta(seconds=.1))
        self.assertEqual(both[1]["appearance_id"], first["appearance_id"])
        self.assertNotEqual(both[1]["appearance_id"], both[2]["appearance_id"])
        # Old/new aliases of a reacquired track also cannot label two visible objects alike.
        reacquired = self.prepare([(3, self.bbox)], stamp=at() + timedelta(seconds=2))[3]
        aliases = self.prepare([(3, self.bbox), (4, (102, 100, 80, 80))], stamp=at() + timedelta(seconds=2.1))
        self.assertEqual(aliases[3]["appearance_id"], reacquired["appearance_id"])
        self.assertNotEqual(aliases[3]["appearance_id"], aliases[4]["appearance_id"])

    def test_no_allocation_from_stale_display_or_invalid_geometry(self):
        with self.manager.frame(self.camera, "pipeline-1", at()) as frame:
            self.assertEqual(frame.prepare([(1, (float("nan"), 0, 80, 80)), (2, (10, 10, -1, 5))], 1000, 1000), {})
            frame.annotate({"tracks": [{"track_id": 1, "stale": True, "bbox": self.bbox}]})
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM recognition_events")["n"], 0)
        first = self.prepare()[1]
        with self.manager.frame(self.camera, "pipeline-1", at() + timedelta(seconds=.5)) as frame:
            frame.prepare([], 1000, 1000)
            result = {"tracks": [{"track_id": 1, "stale": True}]}
            frame.annotate(result)
            self.assertEqual(result["tracks"][0]["event_id"], first["event_id"])
            self.assertIsNone(self.module.persist_classification("camera-11:1", 1, "RECOGNIZED", .9, 1., True, {}, "Entrance"))

    def test_counter_and_initial_event_rollback_together(self):
        self.db.execute("CREATE TRIGGER fail_appearance BEFORE INSERT ON recognition_events "
                        "WHEN NEW.appearance_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.prepare()
        self.assertEqual(self.db.fetchall("SELECT * FROM camera_appearance_counters"), [])
        self.assertEqual(self.manager._records, {})
        self.db.execute("DROP TRIGGER fail_appearance")
        self.assertEqual(self.prepare()[1]["daily_sequence"], 1)

    def test_independent_concurrent_allocators_get_unique_atomic_sequences(self):
        barrier = threading.Barrier(8)
        allocated, failures = [], []

        def worker(index):
            try:
                manager = self.module.AppearanceManager()
                barrier.wait()
                allocated.append(self.prepare(owner=str(index), manager=manager)[1])
            except Exception as exc:
                failures.append(exc)

        workers = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
        self.assertEqual(failures, [])
        self.assertEqual(sorted(item["daily_sequence"] for item in allocated), list(range(1, 9)))
        self.assertEqual(len({item["event_id"] for item in allocated}), 8)
        self.assertEqual(self.db.fetchone("SELECT last_sequence FROM camera_appearance_counters")["last_sequence"], 8)

    def test_context_nesting_threads_and_unbound_legacy_writer(self):
        self.assertIsNone(self.module.persist_classification(1, 1, "RECOGNIZED", .9, 1., True, {}, "Entrance"))
        with self.manager.frame(self.camera, "outer", at()) as outer:
            first = outer.prepare([(1, self.bbox)], 1000, 1000)[1]
            seen = []
            thread = threading.Thread(target=lambda: seen.append(self.module.persist_classification(1, 1, "RECOGNIZED", .9, 1., True, {}, "Entrance")))
            thread.start()
            thread.join(5)
            self.assertEqual(seen, [None])
            with self.manager.frame({**self.camera, "camera_id": 12}, "inner", at()) as inner:
                other = inner.prepare([(1, self.bbox)], 1000, 1000)[1]
                classified = self.db.add_event(1, "camera-12:1", .9, {})
                self.assertEqual(classified["id"], other["event_id"])
            classified = self.db.add_event(1, "camera-11:1", .9, {})
            self.assertEqual(classified["id"], first["event_id"])
        legacy = self.db.add_unknown_event("legacy:99", {}, camera_source="Legacy camera")
        self.assertIsNone(self.row(legacy["id"])["appearance_id"])

    def test_cache_and_aliases_have_hard_limits_and_touch_is_throttled(self):
        manager = self.module.AppearanceManager(max_cache=3)
        values = self.prepare([(i, (i * 100, 100, 80, 80)) for i in range(8)], manager=manager)
        self.assertEqual(len(values), 8)
        self.assertEqual(len(manager._records), 3)
        self.assertLessEqual(len(manager._aliases), 3)
        first = self.prepare()[1]
        original = self.row(first["event_id"])["detail_json"]
        self.prepare(stamp=at() + timedelta(seconds=.5))
        self.assertEqual(self.row(first["event_id"])["detail_json"], original)
        self.prepare(stamp=at() + timedelta(seconds=1.1))
        self.assertEqual(json.loads(self.row(first["event_id"])["detail_json"])["last_seen"], (at() + timedelta(seconds=1.1)).isoformat())
        # Frequent short-loss churn stays one appearance with a bounded alias set.
        for i in range(2, 25):
            same = self.prepare([(i, self.bbox)], stamp=at() + timedelta(seconds=1.1 + i / 10))[i]
            self.assertEqual(same["appearance_id"], first["appearance_id"])
        self.assertLessEqual(len(self.manager._aliases), 8)

    def test_missing_camera_owner_and_naive_time_do_not_bind(self):
        self.assertEqual(self.prepare(camera={"timezone_name": "Asia/Ho_Chi_Minh"}), {})
        self.assertEqual(self.prepare(owner=""), {})
        with self.assertRaisesRegex(ValueError, "AWARE_TIMESTAMP"):
            with self.manager.frame(self.camera, "owner", datetime(2026, 10, 8)):
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
