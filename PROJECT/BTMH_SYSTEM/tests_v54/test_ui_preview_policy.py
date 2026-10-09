"""Focused UI Preview boundary tests; no application/config or hardware imports.

Run with the existing Python runtime:
    python -B tests_v54/test_ui_preview_policy.py -v
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_app import mediamtx_runtime, ui_preview


class EnvironmentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_preview_requires_explicit_flag(self):
        for value in (None, "0", "true", "development"):
            with self.subTest(value=value):
                if value is None:
                    os.environ.pop("BTMH_UI_PREVIEW", None)
                else:
                    os.environ["BTMH_UI_PREVIEW"] = value
                self.assertFalse(ui_preview.validated_preview())

    def test_default_and_test_profiles_are_private_sqlite_loopback(self):
        for profile in ("default", "tests/policy-smoke"):
            with self.subTest(profile=profile):
                root = ui_preview.prepare_environment(profile=profile, port=8810)
                self.assertEqual(root, (ui_preview.PREVIEW_DIRECTORY / profile).absolute())
                self.assertTrue(ui_preview.validated_preview())
                self.assertEqual(os.environ["CAMPUSFACE_DB_MODE"], "sqlite")
                self.assertEqual(os.environ["MODULE_HOST"], "127.0.0.1")
                self.assertEqual(os.environ["BTMH_ENV"], "development")

    def test_customer_settings_are_not_inherited(self):
        inherited = {
            "CAMPUSFACE_DATA_ROOT": str(ROOT / "production-data"),
            "CAMPUSFACE_DB_MODE": "postgres",
            "CAMPUSFACE_HIKVISION_PROFILE": "must-be-removed",
            "CAMPUSFACE_PAD_THRESHOLD": "must-be-removed",
            "BTMH_MEDIAMTX_BIN": "must-be-removed",
            "BTMH_ALLOW_FIRST_RUN_OWNER": "1",
            "MODULE_HOST": "0.0.0.0",
            "FACE_DEMO_KEY": "must-be-removed",
            "OPENCV_FFMPEG_CAPTURE_OPTIONS": "must-be-removed",
            "UNRELATED_PREVIEW_TEST_VARIABLE": "preserve",
        }
        os.environ.update(inherited)
        ui_preview.prepare_environment()
        for key in inherited:
            if key not in {"CAMPUSFACE_DATA_ROOT", "CAMPUSFACE_DB_MODE", "MODULE_HOST",
                           "UNRELATED_PREVIEW_TEST_VARIABLE"}:
                with self.subTest(key=key):
                    self.assertNotIn(key, os.environ)
        self.assertEqual(os.environ["UNRELATED_PREVIEW_TEST_VARIABLE"], "preserve")
        self.assertNotEqual(os.environ["CAMPUSFACE_DATA_ROOT"], inherited["CAMPUSFACE_DATA_ROOT"])

    def test_preview_rejects_production_or_unapproved_data_paths(self):
        ui_preview.prepare_environment()
        for root in (ROOT / "production-data", ui_preview.PREVIEW_DIRECTORY,
                     ui_preview.PREVIEW_DIRECTORY / "other",
                     ui_preview.PREVIEW_DIRECTORY / "tests" / "nested" / "child"):
            with self.subTest(root=str(root)):
                os.environ["CAMPUSFACE_DATA_ROOT"] = str(root)
                with self.assertRaisesRegex(RuntimeError, "private SQLite"):
                    ui_preview.validated_preview()

    def test_preview_rejects_postgres_lan_binding_or_production_mode(self):
        for key, value in (("CAMPUSFACE_DB_MODE", "postgres"),
                           ("MODULE_HOST", "0.0.0.0"),
                           ("BTMH_ENV", "production")):
            with self.subTest(key=key):
                ui_preview.prepare_environment()
                os.environ[key] = value
                with self.assertRaises(RuntimeError):
                    ui_preview.validated_preview()

    def test_redirected_private_root_is_rejected_without_following_it(self):
        root = ui_preview.prepare_environment()
        original_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == root:
                return (ROOT / "production-data").absolute()
            return original_resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve):
            with self.assertRaisesRegex(RuntimeError, "must not be redirected"):
                ui_preview.validated_preview()

    def test_profile_and_port_validation(self):
        for profile in ("../production-data", str(ROOT / "production-data")):
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    ui_preview.prepare_environment(profile=profile)
        for port in (0, 65536, -1):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    ui_preview.prepare_environment(port=port)

    def test_existing_child_redirects_are_rejected_before_product_imports(self):
        root = ui_preview.prepare_environment(profile="tests/policy-tree")
        child = root / "recognition_module.db"
        directory = SimpleNamespace(st_mode=stat.S_IFDIR, st_nlink=1, st_file_attributes=0)
        for kind in ("symlink", "reparse-point", "hardlink", "outside-root"):
            with self.subTest(kind=kind):
                file_info = SimpleNamespace(
                    st_mode=stat.S_IFREG,
                    st_nlink=2 if kind == "hardlink" else 1,
                    st_file_attributes=0x400 if kind == "reparse-point" else 0,
                )

                def resolve(path, *args, **kwargs):
                    if path == child and kind == "outside-root":
                        return (ROOT / "production-data" / child.name).absolute()
                    return path.absolute()

                with patch.object(Path, "exists", return_value=True), \
                     patch.object(Path, "lstat", lambda path: directory if path == root else file_info), \
                     patch.object(Path, "iterdir", lambda path: iter([child]) if path == root else iter([])), \
                     patch.object(Path, "is_symlink", lambda path: path == child and kind == "symlink"), \
                     patch.object(Path, "resolve", resolve):
                    with self.assertRaisesRegex(RuntimeError, "must not contain redirected data"):
                        ui_preview.validated_preview()

    def test_existing_regular_profile_is_permitted(self):
        root = ui_preview.prepare_environment(profile="tests/policy-tree")
        child = root / "recognition_module.db"
        directory = SimpleNamespace(st_mode=stat.S_IFDIR, st_nlink=1, st_file_attributes=0)
        regular = SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=1, st_file_attributes=0)
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "lstat", lambda path: directory if path == root else regular), \
             patch.object(Path, "iterdir", lambda path: iter([child]) if path == root else iter([])), \
             patch.object(Path, "is_symlink", return_value=False), \
             patch.object(Path, "resolve", lambda path: path.absolute()):
            self.assertTrue(ui_preview.validated_preview())


class APIBoundaryTests(unittest.TestCase):
    def test_independent_auth_and_management_routes_remain_available(self):
        routes = (
            ("/api/v1/health", "GET"),
            ("/api/v1/auth/status", "GET"),
            ("/api/v1/auth/bootstrap-local", "POST"),
            ("/api/v1/auth/login", "POST"),
            ("/api/v1/auth/logout", "POST"),
            ("/api/v1/auth/profile", "GET"),
            ("/api/v1/auth/password", "POST"),
            ("/api/v1/auth/admin-security", "GET"),
            ("/api/v1/admin/users", "POST"),
            ("/api/v1/students", "GET"),
            ("/api/v1/stores", "GET"),
            ("/api/v1/recognition/recent", "GET"),
            ("/api/v1/recognition/cameras", "GET"),
            ("/api/v1/history/recognition", "GET"),
            ("/api/v1/dashboard/summary", "GET"),
            ("/api/v1/hr-report/monthly", "GET"),
            ("/api/v1/admin/face-enrollment/invitations", "POST"),
            ("/api/v1/admin/face-enrollment/requests/1/reject", "POST"),
            ("/api/v1/admin/face-enrollment/requests/1/reenrollment", "POST"),
        )
        for path, method in routes:
            with self.subTest(path=path, method=method):
                self.assertFalse(ui_preview.hardware_unavailable(path, method))

    def test_camera_ai_network_and_unknown_integrations_are_unavailable(self):
        routes = (
            ("/api/v1/camera/select", "POST"),
            ("/api/v1/camera/test-source", "POST"),
            ("/api/v1/camera/frame.jpg", "GET"),
            ("/api/v1/media/gateway/restart", "POST"),
            ("/api/v1/media/whep", "POST"),
            ("/api/v1/office/start", "POST"),
            ("/api/v1/recordings/status", "GET"),
            ("/api/v1/system/diagnostics", "GET"),
            ("/api/v1/sync/receive", "POST"),
            ("/api/v1/auth/sms/send", "POST"),
            ("/api/v1/auth/admin-security", "PUT"),
            ("/api/v1/admin/face-enrollment/requests/1/approve", "POST"),
            ("/api/v1/admin/face-enrollment/requests/1/frame", "POST"),
            ("/api/v1/admin/face-enrollment/requests/1/finalize", "POST"),
            ("/api/v1/history/recognition", "POST"),
            ("/api/v1/operations/summary", "GET"),
            ("/api/v1/future-hardware/start", "POST"),
        )
        for path, method in routes:
            with self.subTest(path=path, method=method):
                self.assertTrue(ui_preview.hardware_unavailable(path, method))

    def test_cdn_backed_api_documentation_is_unavailable_offline(self):
        for path in ("/docs", "/docs/", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            with self.subTest(path=path):
                self.assertTrue(ui_preview.hardware_unavailable(path, "GET"))

        # Use the actual app declaration without importing the application or
        # triggering its configuration/key creation side effects.
        tree = ast.parse((ROOT / "module_app" / "main.py").read_text(encoding="utf-8"))
        declaration = next(
            node.value for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name) and node.value.func.id == "FastAPI"
        )
        factory = Mock()
        expression = ast.fix_missing_locations(ast.Expression(body=declaration))
        for enabled in (True, False):
            with self.subTest(preview=enabled):
                factory.reset_mock()
                eval(compile(expression, "preview-documentation-policy", "eval"),
                     {"FastAPI": factory, "UI_PREVIEW": enabled,
                      "APP_NAME": "policy-test", "APP_VERSION": "policy-test"})
                for key in ("docs_url", "redoc_url", "openapi_url"):
                    if enabled:
                        self.assertIsNone(factory.call_args.kwargs[key])
                if not enabled:
                    self.assertEqual(factory.call_args.kwargs["docs_url"], "/docs")
                    self.assertEqual(factory.call_args.kwargs["openapi_url"], "/openapi.json")

    def test_frontend_assets_are_not_blocked_or_authentication_removed(self):
        for path in ("/", "/static/js/app.js", "/mobile", "/enroll"):
            self.assertFalse(ui_preview.hardware_unavailable(path, "GET"))
        original = '<html><body><div id="authGate"></div><script src="/static/js/app.js"></script></body></html>'
        # This check concerns HTML preservation, so no temporary files or
        # filesystem permissions are needed to exercise it.
        with patch.object(Path, "read_text", return_value=original):
            decorated = ui_preview.preview_html(ROOT / "frontend" / "index.html")
        self.assertIn('<div id="authGate"></div>', decorated)
        self.assertIn('<script src="/static/js/app.js"></script>', decorated)
        self.assertIn('id="btmh-ui-preview-notice"', decorated)
        self.assertIn(ui_preview.NOTICE, decorated)


class LocalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, *, client="127.0.0.1", host="127.0.0.1:8810", kind="http"):
        messages = []
        called = []

        async def application(scope, receive, send):
            called.append(scope["type"])
            if scope["type"] == "http":
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"OK"})

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {"type": kind, "client": (client, 12345), "path": "/", "method": "GET",
                 "headers": [(b"host", host.encode("latin1"))], "http_version": "1.1"}
        await ui_preview.LocalPreviewMiddleware(application)(scope, receive, send)
        return called, messages

    async def test_only_loopback_clients_and_local_hosts_reach_application(self):
        for client, host in (("127.0.0.1", "127.0.0.1:8810"),
                             ("127.0.0.1", "localhost:8810"),
                             ("::1", "[::1]:8810")):
            with self.subTest(client=client, host=host):
                called, messages = await self.invoke(client=client, host=host)
                self.assertEqual(called, ["http"])
                self.assertEqual(messages[0]["status"], 200)

    async def test_remote_clients_dns_rebinding_and_missing_host_are_rejected(self):
        for client, host in (("192.0.2.44", "127.0.0.1:8810"),
                             ("127.0.0.1", "attacker.example:8810"),
                             ("127.0.0.1", ""),
                             ("not-an-address", "localhost")):
            with self.subTest(client=client, host=host):
                called, messages = await self.invoke(client=client, host=host)
                self.assertEqual(called, [])
                self.assertEqual(messages[0]["status"], 403)
                self.assertIn("detail", json.loads(messages[1]["body"]))

    async def test_malformed_host_is_rejected(self):
        for host in ("[", "localhost:not-a-port", "127.0.0.1:65536",
                     "user@localhost:8810", "user:password@127.0.0.1:8810",
                     "localhost:8810/path", "localhost:8810?query=1", "localhost:8810#fragment"):
            with self.subTest(host=host):
                called, messages = await self.invoke(host=host)
                self.assertEqual(called, [])
                self.assertEqual(messages[0]["status"], 403)

    async def test_websockets_are_closed_without_starting_realtime_application(self):
        for client, host in (("127.0.0.1", "localhost:8810"),
                             ("192.0.2.44", "attacker.example")):
            with self.subTest(client=client):
                called, messages = await self.invoke(client=client, host=host, kind="websocket")
                self.assertEqual(called, [])
                self.assertEqual(messages[0]["type"], "websocket.close")
                self.assertEqual(messages[0]["code"], 1008)

    async def test_lifespan_passes_through(self):
        called, messages = await self.invoke(kind="lifespan")
        self.assertEqual(called, ["lifespan"])
        self.assertEqual(messages, [])


class ProductionCompatibilityTests(unittest.TestCase):
    def test_missing_mediamtx_still_fails_closed_outside_explicit_development(self):
        missing = mediamtx_runtime.MediaMTXRuntime(None, "MEDIAMTX_NOT_INSTALLED")
        with patch.object(mediamtx_runtime, "resolve_mediamtx", return_value=missing):
            for value in (None, "production", "dev", ""):
                with self.subTest(mode=value), patch.dict(os.environ, {}, clear=True):
                    if value is not None:
                        os.environ["BTMH_ENV"] = value
                    with self.assertRaisesRegex(RuntimeError, "^MEDIAMTX_NOT_INSTALLED$"):
                        mediamtx_runtime.require_mediamtx(ROOT / "unused-preview-test-path")
            with patch.dict(os.environ, {"BTMH_ENV": "development"}, clear=True):
                self.assertIs(mediamtx_runtime.require_mediamtx(ROOT / "unused-preview-test-path"), missing)

    def test_actual_production_startup_checks_gateway_before_database_or_workers(self):
        tree = ast.parse((ROOT / "module_app" / "main.py").read_text(encoding="utf-8"))
        startup = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "startup")
        startup.decorator_list = []
        isolated_tree = ast.fix_missing_locations(ast.Module(body=[startup], type_ignores=[]))
        database = Mock(name="init_db")
        gateway = Mock(name="require_mediamtx", side_effect=RuntimeError("MEDIAMTX_NOT_INSTALLED"))
        namespace = {"UI_PREVIEW": False, "DATA_ROOT": ROOT / "unused-preview-test-path",
                     "require_mediamtx": gateway, "init_db": database}
        exec(compile(isolated_tree, "production-startup-policy", "exec"), namespace)
        with self.assertRaisesRegex(RuntimeError, "^MEDIAMTX_NOT_INSTALLED$"):
            namespace["startup"]()
        gateway.assert_called_once_with(namespace["DATA_ROOT"])
        database.assert_not_called()


if __name__ == "__main__":
    unittest.main()
