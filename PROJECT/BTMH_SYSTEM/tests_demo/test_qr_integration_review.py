"""Coordinated QR service boundary tests with isolated real SQLite.

No FastAPI/model/camera boot, customer database, or installed crypto key is used.
The existing service fixture supplies its documented authenticated test codec.
"""
from __future__ import annotations

import ast
import hashlib
import mimetypes
from pathlib import Path
import threading
import unittest

import test_qr_enrollment as service_tests


class QRIntegrationReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = service_tests.QREnrollmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.qr = self.fixture.qr

    def desktop(self):
        self.fixture.db.execute("UPDATE students SET biometric_consent_status='GRANTED' WHERE id=1")
        return self.qr.start_desktop_request(self.fixture.owner, 1, 1, now=self.fixture.now)["request"]

    def test_reset_purges_evidence_before_new_revision_lease_can_enter(self):
        row = self.desktop()
        callback_entered, callback_release, lease_entered = (threading.Event() for _ in range(3))
        errors, results = [], []

        def reset_evidence(request_id):
            self.assertEqual(request_id, row["id"])
            self.assertTrue(self.fixture.raw.in_transaction)
            callback_entered.set()
            if not callback_release.wait(3):
                raise AssertionError("reset callback was not released")

        self.qr.bind_runtime_callbacks(reset_capture=reset_evidence)

        def reset():
            try:
                results.append(self.qr.reset_capture(actor=self.fixture.owner, request_id=row["id"], now=self.fixture.now))
            except BaseException as exc:
                errors.append(exc)

        def capture():
            try:
                with self.qr.desktop_capture_lease(self.fixture.owner, row["id"], 1, now=self.fixture.now) as binding:
                    results.append(binding)
                    lease_entered.set()
            except BaseException as exc:
                errors.append(exc)

        reset_thread = threading.Thread(target=reset)
        capture_thread = threading.Thread(target=capture)
        reset_thread.start()
        try:
            self.assertTrue(callback_entered.wait(3), errors)
            capture_thread.start()
            self.assertFalse(lease_entered.wait(.05), "new capture used the reset revision before old evidence was purged")
        finally:
            callback_release.set()
            reset_thread.join(3)
            if capture_thread.ident is not None:
                capture_thread.join(3)
        self.assertFalse(reset_thread.is_alive())
        self.assertFalse(capture_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(lease_entered.is_set())
        self.assertEqual(results[0]["request"]["revision"], row["revision"] + 1)
        self.assertEqual(results[1]["revision"], row["revision"] + 1)
        self.assertEqual(self.fixture.stored(row["id"])["status"], "CAPTURING")

    def test_reset_callback_failure_rolls_back_revision_preserves_old_template(self):
        row = self.desktop()
        self.fixture.old_active()

        def failing_reset(request_id):
            self.assertTrue(self.fixture.raw.in_transaction)
            raise RuntimeError("isolated transient reset failure")

        self.qr.bind_runtime_callbacks(reset_capture=failing_reset)
        with self.assertRaisesRegex(RuntimeError, "isolated transient reset failure"):
            self.qr.reset_capture(actor=self.fixture.owner, request_id=row["id"], now=self.fixture.now)
        stored = self.fixture.stored(row["id"])
        self.assertEqual(stored["status"], "CAPTURING")
        self.assertEqual(stored["revision"], row["revision"])
        self.assertEqual(self.fixture.active(), b"old-face")
        self.assertEqual(self.fixture.refreshes, [])

    def test_postcommit_approval_cannot_restore_portrait_after_withdrawal(self):
        row, _ = self.fixture.pending()
        refresh_entered, refresh_release = threading.Event(), threading.Event()
        errors, portrait_consent = [], []

        def paused_refresh():
            self.assertFalse(self.fixture.raw.in_transaction)
            refresh_entered.set()
            if not refresh_release.wait(3):
                raise AssertionError("post-commit refresh was not released")

        def save_portrait(student_id, blob, *, conn=None):
            current = self.fixture.db.fetchone("SELECT biometric_consent_status FROM students WHERE id=?", (student_id,))
            portrait_consent.append(current["biometric_consent_status"] if current else "DELETED")

        self.qr.bind_runtime_callbacks(refresh_active_index=paused_refresh, save_approved_preview=save_portrait)

        def approve():
            try:
                self.fixture.approve(row)
            except BaseException as exc:
                errors.append(exc)

        approval_thread = threading.Thread(target=approve)
        approval_thread.start()
        try:
            self.assertTrue(refresh_entered.wait(3), errors)
            with self.qr.publication_transaction() as conn:
                conn.execute("UPDATE students SET biometric_consent_status='WITHDRAWN' WHERE id=1")
                conn.execute("DELETE FROM face_templates WHERE student_id=1")
                retired = self.qr.cancel_employee_requests(1, actor=self.fixture.owner, conn=conn, now=self.fixture.now)
            self.qr.retire_requests(retired)
            self.assertIsNone(self.fixture.active())
        finally:
            refresh_release.set()
            approval_thread.join(3)
        self.assertFalse(approval_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(portrait_consent, [], "approved portrait ran after consent was withdrawn")

    def test_old_approval_portrait_cannot_overwrite_new_approved_replacement(self):
        old, _ = self.fixture.pending(value=b"old-approved-face")
        refresh_entered, refresh_release = threading.Event(), threading.Event()
        errors, portrait_templates = [], []
        refresh_count = 0

        def paused_first_refresh():
            nonlocal refresh_count
            refresh_count += 1
            if refresh_count == 1:
                refresh_entered.set()
                if not refresh_release.wait(3):
                    raise AssertionError("first refresh was not released")

        def save_portrait(student_id, blob, *, conn=None):
            self.assertIsNotNone(conn, "portrait metadata must use its publication transaction")
            current = conn.execute("SELECT embedding_blob FROM face_templates WHERE student_id=?", (student_id,)).fetchone()
            portrait_templates.append(self.fixture.crypto.decrypt_bytes(bytes(current["embedding_blob"])))

        self.qr.bind_runtime_callbacks(refresh_active_index=paused_first_refresh, save_approved_preview=save_portrait)

        def approve_old():
            try:
                self.fixture.approve(old)
            except BaseException as exc:
                errors.append(exc)

        old_thread = threading.Thread(target=approve_old)
        old_thread.start()
        try:
            self.assertTrue(refresh_entered.wait(3), errors)
            newer, _ = self.fixture.pending(value=b"new-approved-face")
            self.fixture.approve(newer)
        finally:
            refresh_release.set()
            old_thread.join(3)
        self.assertFalse(old_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.fixture.active(), b"new-approved-face")
        self.assertEqual(portrait_templates, [b"new-approved-face"], "old approval rewrote the new profile portrait")

    def test_actual_photo_metadata_writer_uses_supplied_sqlite_transaction(self):
        source = Path(__file__).resolve().parents[1] / "module_app" / "student_media.py"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_upsert_photo"]
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *functions], type_ignores=[])

        def separate_connection(*args):
            raise AssertionError("photo metadata opened a second connection inside publication")

        namespace = {"hashlib": hashlib, "mimetypes": mimetypes,
                     "utc_now": lambda: self.fixture.now.isoformat(), "_relative": lambda path: path.as_posix(),
                     "fetchone": separate_connection, "execute": separate_connection}
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
        with self.qr.publication_transaction() as conn:
            conn.execute("CREATE TABLE student_photos(id INTEGER PRIMARY KEY,student_id INTEGER,photo_type TEXT,relative_path TEXT,mime_type TEXT,sha256 TEXT,created_at TEXT,updated_at TEXT)")
            inserted = namespace["_upsert_photo"](1, "PROFILE", Path("profile.jpg"), b"first-portrait", conn=conn)
            updated = namespace["_upsert_photo"](1, "PROFILE", Path("profile.jpg"), b"replacement-portrait", conn=conn)
            self.assertEqual(inserted["id"], updated["id"])
        rows = self.fixture.db.fetchall("SELECT * FROM student_photos")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sha256"], hashlib.sha256(b"replacement-portrait").hexdigest())


if __name__ == "__main__":
    unittest.main()
