"""Actual auth/password/session code with private SQLite and a test-only codec.

No app startup, customer database, SMS delivery, installed encryption or models.
Database transactions use the real db.connection(), including separate thread
connections. PostgreSQL lock ordering is checked with a SQL adapter only.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from test_demo_context import load_isolated_modules

SOURCE = Path(__file__).resolve().parents[1] / "module_app"
PW = "OnlyForBootstrapTests!550"


class AuthBootstrapRegressionTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
        directory = tempfile.TemporaryDirectory(prefix=".tmp_auth_regression_", dir=Path(__file__).resolve().parent)
        self.addCleanup(directory.cleanup)
        self.db.SQLITE_PATH = Path(directory.name) / "private-auth.db"
        self.db.init_db()
        with self.db.connection() as conn:
            conn.executescript("""CREATE TABLE system_users(
              id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,
              display_name TEXT NOT NULL,role TEXT NOT NULL,password_salt TEXT NOT NULL,
              password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,updated_at TEXT NOT NULL);""")
        package = self.db.__package__
        crypto = types.ModuleType(package + ".crypto")
        crypto.encrypt_bytes, crypto.decrypt_bytes = base64.b64encode, base64.b64decode
        sys.modules[crypto.__name__] = crypto
        provider = types.ModuleType(package + ".sms_provider_v542")
        provider.configured = lambda: False
        provider.get_provider = lambda: (_ for _ in ()).throw(AssertionError("no SMS in isolated tests"))
        sys.modules[provider.__name__] = provider
        for name in ("auth", "sms_auth_v542"):
            spec = importlib.util.spec_from_file_location(package + "." + name, SOURCE / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            setattr(self, name, module)
        self.auth._ARGON2 = None  # Existing PBKDF2 path; no optional runtime needed.
        self.auth.ensure_rbac_schema()

    def owner(self):
        return self.auth.bootstrap_admin("testowner", "Test Owner", PW, phone_verified=False)

    def test_first_owner_login_logout_and_login_again(self):
        self.assertEqual(self.auth.user_count(), 0)
        owner = self.owner()
        self.assertEqual(owner["role"], "SUPER_ADMIN")
        self.assertEqual(self.auth.user_count(), 1)
        row = self.db.fetchone("SELECT * FROM system_users WHERE id=?", (owner["id"],))
        self.assertNotIn(PW, str(row))
        first = self.auth.login("testowner", PW)["token"]
        self.assertEqual(self.auth.user_for_token(first)["id"], owner["id"])
        self.auth.logout(first)
        self.assertIsNone(self.auth.user_for_token(first))
        second = self.auth.login("testowner", PW)["token"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.auth.user_for_token(second)["id"], owner["id"])

    def test_wrong_credentials_do_not_issue_session(self):
        self.owner()
        for username, password in (("testowner", "wrong"), ("missing", PW)):
            with self.subTest(username=username), self.assertRaises(ValueError):
                self.auth.login(username, password)
        self.assertEqual(self.auth._sessions, {})

    def test_second_owner_and_disabled_privileged_records_never_reopen_bootstrap(self):
        owner = self.owner()
        self.db.execute("UPDATE system_users SET active=0 WHERE id=?", (owner["id"],))
        self.assertEqual(self.auth.user_count(), 1)
        with self.assertRaises(ValueError):
            self.auth.bootstrap_admin("secondowner", "Second Owner", PW, phone_verified=False)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM system_users")["n"], 1)
        with self.assertRaises(PermissionError):
            self.auth.require_role("", {"ADMIN"})
        with self.assertRaises(ValueError):
            self.auth.login("testowner", PW)

    def test_concurrent_different_usernames_create_exactly_one_first_owner(self):
        original = self.auth._new_password
        barrier = threading.Barrier(2)

        def password(*args, **kwargs):
            result = original(*args, **kwargs)
            barrier.wait(timeout=10)
            return result

        def attempt(username):
            try:
                return self.auth.bootstrap_admin(username, "Test Owner", PW, phone_verified=False)["id"]
            except ValueError:
                return None

        with patch.object(self.auth, "_new_password", password), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ("ownerone", "ownertwo")))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.auth.user_count(), 1)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM system_users")["n"], 1)

    def test_existing_totp_requires_bound_factor_and_rejects_bad_code(self):
        owner = self.owner()
        secret = self.auth._totp_secret()
        self.auth._persist_mfa_setup(owner["id"], secret, self.auth._totp_step() - 1)
        challenge = self.auth.login("testowner", PW, binding="private-test-browser")
        self.assertTrue(challenge["mfa_required"])
        self.assertNotIn("token", challenge)
        self.assertEqual(self.auth._sessions, {})
        with self.assertRaises(ValueError):
            self.auth.complete_mfa_challenge(challenge["challenge_id"], "invalid-code", binding="private-test-browser")
        with self.assertRaises(ValueError):
            self.auth.complete_mfa_challenge(challenge["challenge_id"], self.auth._totp_code(secret), binding="other-browser")
        verified = self.auth.complete_mfa_challenge(challenge["challenge_id"], self.auth._totp_code(secret), binding="private-test-browser")
        self.assertTrue(verified["mfa_verified"])
        self.assertEqual(self.auth.user_for_token(verified["token"])["id"], owner["id"])

    def test_rbac_remains_server_enforced_after_setup(self):
        self.owner()
        viewer = self.auth.create_user("testviewer", "Test Viewer", "VIEWER", PW)
        token = self.auth.login("testviewer", PW)["token"]
        self.assertEqual(self.auth.require_permission("Bearer " + token, "camera.live")["id"], viewer["id"])
        with self.assertRaises(PermissionError):
            self.auth.require_permission("Bearer " + token, "employee.enroll")
        with self.assertRaises(PermissionError):
            self.auth.require_role("Bearer " + token, {"ADMIN"})
        with self.assertRaises(PermissionError):
            self.auth.require_permission("", "camera.live")

    def test_postgres_adapter_locks_before_count_and_inserts_with_returning(self):
        statements = []

        class Cursor:
            def __init__(self, row): self.row = row
            def fetchone(self): return self.row

        class Connection:
            mode = "postgres"
            def execute(self, sql, params=()):
                statements.append(sql)
                return Cursor({"n": 0} if "COUNT(*)" in sql else {"id": 81})

        @contextmanager
        def connection():
            yield Connection()

        with patch.object(self.auth, "connection", connection), patch.object(self.auth, "ensure_rbac_schema"), \
             patch.object(self.auth, "_public_user", side_effect=lambda row: row):
            result = self.owner()
        self.assertEqual(result["id"], 81)
        self.assertIn("LOCK TABLE system_users", statements[0])
        self.assertIn("COUNT(*)", statements[1])
        self.assertTrue(statements[2].endswith(" RETURNING id"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
