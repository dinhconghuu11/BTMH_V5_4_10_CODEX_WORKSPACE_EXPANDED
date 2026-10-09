"""Focused real localhost HTTP smoke, with no hardware/dependency downloads.

Run from BTMH_SYSTEM using an existing installed Python: python -B
tests_browser/smoke_ui_preview.py. Each run gets a separate test SQLite profile.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from module_app.ui_preview import prepare_environment


class PreviewHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Never select an operational root and never seed a default password.
        cls.root = prepare_environment(profile="tests/http-" + secrets.token_hex(6))
        import uvicorn
        from module_app import main
        cls.main = main
        cls.patches = []

        def forbidden(*args, **kwargs):
            raise AssertionError("Preview attempted hardware, model load or child process")

        for owner, member in [
            (main.CAMERA, "start"), (main.AI_RUNTIME, "start"),
            (main.MEDIA_GATEWAY, "start"), (main.RECORDER_V4, "start"),
            (main.EDGE_SYNC_WORKER, "start"), (main.OFFICE, "start"),
            (main.PILOT, "start"), (main.INDEX, "load"),
            (main, "gpu_status"), (subprocess, "Popen"),
        ]:
            guard = patch.object(owner, member, side_effect=forbidden)
            guard.start()
            cls.patches.append(guard)
        original_connect = socket.socket.connect

        def local_connect(sock, address):
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
                raise AssertionError("Preview attempted non-loopback network")
            return original_connect(sock, address)

        network_guard = patch.object(socket.socket, "connect", local_connect)
        network_guard.start()
        cls.patches.append(network_guard)
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        cls.port = cls.sock.getsockname()[1]
        cls.url = f"http://127.0.0.1:{cls.port}"
        cls.server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=cls.port,
            proxy_headers=False, access_log=False, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [cls.sock]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 20
        while not cls.server.started and cls.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        if not cls.server.started:
            cls.tearDownClass()
            raise RuntimeError("Preview HTTP server did not start")
        cls.jar = http.cookiejar.CookieJar()
        cls.client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                 urllib.request.HTTPCookieProcessor(cls.jar))
        cls.anonymous = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cls.password = "Ui!9" + secrets.token_urlsafe(18)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.should_exit = True
            cls.thread.join(10)
            if cls.thread.is_alive():
                raise RuntimeError("Preview server failed to stop")
        if hasattr(cls, "sock"):
            cls.sock.close()
        for guard in reversed(cls.patches):
            guard.stop()

    def request(self, path, *, method="GET", data=None, anonymous=False, host=None):
        headers = {"Origin": self.url}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if host:
            headers["Host"] = host
        request = urllib.request.Request(self.url + path, method=method, headers=headers,
            data=json.dumps(data).encode() if data is not None else None)
        try:
            response = (self.anonymous if anonymous else self.client).open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, response.headers, response.read()

    def payload(self, path, **kwargs):
        code, headers, raw = self.request(path, **kwargs)
        return code, headers, json.loads(raw)

    def test_01_startup_isolated_no_workers_no_fake_data(self):
        main = self.main
        self.assertEqual(main.runtime_config.DATA_ROOT, self.root)
        self.assertEqual(main.runtime_config.DB_MODE, "sqlite")
        self.assertTrue(main.runtime_config.PAD_ENABLED)
        for table in ["system_users", "students", "face_templates", "recognition_events",
                      "attendance_records", "hr_events", "hr_presence_sessions", "camera_devices"]:
            self.assertEqual(main.fetchone(f"SELECT COUNT(*) AS n FROM {table}")["n"], 0, table)
        for service in [main.AI_RUNTIME, main.RECORDER_V4, main.EDGE_SYNC_WORKER]:
            self.assertIsNone(service._thread)
        code, _, health = self.payload("/api/v1/health")
        self.assertEqual(code, 200)
        self.assertEqual(health["mode"], "UI_PREVIEW")
        self.assertFalse(health["local_ai_pipeline"])
        self.assertFalse(health["camera"]["opened"])
        self.assertFalse(health["database"]["production"])

    def test_02_frontend_and_referenced_assets(self):
        assets = set()
        for page in ["/", "/mobile", "/enroll"]:
            code, _, raw = self.request(page)
            self.assertEqual(code, 200, page)
            html = raw.decode("utf-8")
            assets.update(re.findall(r'(?:src|href)=["\'](/static/[^"\']+)', html))
            self.assertIn("btmh-ui-preview-notice", html)
            if page == "/":
                self.assertIn("/static/js/app.js", html)
                self.assertIn('id="authGate"', html)
        for asset in sorted(assets):
            code, _, raw = self.request(asset)
            self.assertEqual(code, 200, asset)
            self.assertGreater(len(raw), 0, asset)
        print(f"  Frontend pages: 3; referenced local assets: {len(assets)} PASS", flush=True)
        self.assertEqual(self.request("/docs")[0], 503)
        self.assertEqual(self.request("/openapi.json")[0], 503)

    def test_03_localhost_boundary_and_real_owner_setup(self):
        code, _, status = self.payload("/api/v1/auth/status")
        self.assertEqual(code, 200)
        self.assertTrue(status["setup_required"])
        self.assertEqual(self.request("/", host="outside.invalid")[0], 403)
        self.assertEqual(self.request("/", host="[")[0], 403)
        # Real password validation: no permissive preview login shortcut.
        self.assertEqual(self.request("/api/v1/auth/bootstrap-local", method="POST", data={
            "username": "preview-owner", "display_name": "Preview Owner", "password": "short"})[0], 400)
        code, _, _ = self.payload("/api/v1/auth/bootstrap-local", method="POST", data={
            "username": "preview-owner", "display_name": "Preview Owner", "password": self.password})
        self.assertEqual(code, 200)
        self.assertTrue(any(cookie.has_nonstandard_attr("HttpOnly") for cookie in self.jar))
        self.assertEqual(self.request("/api/v1/admin/users", anonymous=True)[0], 401)
        self.assertEqual(self.request("/api/v1/admin/users")[0], 200)
        self.assertEqual(self.request("/api/v1/auth/bootstrap-local", method="POST", data={
            "username": "second-owner", "password": self.password})[0], 409)

    def test_04_independent_ui_apis_and_qr_management(self):
        code, _, created = self.payload('/api/v1/stores', method='POST', data={
            'store_code': 'QA-CATALOG', 'store_name': 'Cửa hàng kiểm thử danh mục',
            'timezone_name': 'Asia/Ho_Chi_Minh'})
        self.assertEqual(code, 200)
        self.assertTrue(created['ok'])
        self.__class__.catalog_store_id = created['store']['id']
        code, _, listed = self.payload('/api/v1/stores')
        self.assertEqual(code, 200)
        self.assertTrue(any(row['id'] == self.catalog_store_id and row['store_code'] == 'QA-CATALOG' for row in listed['items']))
        self.assertEqual(self.request('/api/v1/stores', method='POST', data={
            'store_code': 'QA-CATALOG', 'store_name': 'Duplicate'})[0], 400)
        self.assertEqual(self.request('/api/v1/stores', anonymous=True)[0], 401)
        # Explicitly migrate this disposable test DB, never the product startup.
        from module_app.catalog_migration import apply_mapping
        self.assertEqual(self.payload('/api/v1/zones')[2]['available'], False)
        apply_mapping(test_database=True)
        code, _, updated = self.payload(f'/api/v1/stores/{self.catalog_store_id}', method='PATCH', data={'store_name': 'Cửa hàng đã sửa'})
        self.assertEqual(code, 200)
        self.assertEqual(updated['store']['id'], self.catalog_store_id)
        code, _, zone = self.payload('/api/v1/zones', method='POST', data={'store_id': self.catalog_store_id, 'zone_name': 'Quầy kiểm thử'})
        self.assertEqual(code, 200)
        zid = zone['item']['id']
        self.assertEqual(self.payload('/api/v1/zones')[2]['items'][0]['id'], zid)
        self.assertEqual(self.request(f'/api/v1/zones/{zid}', method='PATCH', data={'zone_name': 'Quầy đã sửa'})[0], 200)
        self.assertEqual(self.request(f'/api/v1/zones/{zid}', method='PATCH', data={'status': 'ARCHIVED'})[0], 200)
        self.assertEqual(self.request(f'/api/v1/zones/{zid}', method='DELETE')[0], 200)
        self.assertEqual(self.request(f'/api/v1/stores/{self.catalog_store_id}', method='PATCH', data={'status': 'ARCHIVED'})[0], 200)
        self.assertEqual(self.request(f'/api/v1/stores/{self.catalog_store_id}', method='PATCH', data={'status': 'ACTIVE'})[0], 200)
        self.assertEqual(self.request('/api/v1/zones', anonymous=True)[0], 401)
        for path in ["/api/v1/auth/profile", "/api/v1/auth/sms/security", "/api/v1/admin/roles", "/api/v1/stores",
                     "/api/v1/work-shifts", "/api/v1/students", "/api/v1/dashboard/summary",
                     "/api/v1/history/filters", "/api/v1/history/recognition",
                     "/api/v1/history/attendance", "/api/v1/hr-report/summary",
                     "/api/v1/recognition/cameras", "/api/v1/recognition/recent",
                     "/api/v1/admin/face-enrollment/requests"]:
            self.assertEqual(self.request(path)[0], 200, path)
        code, _, employee = self.payload("/api/v1/students", method="POST", data={
            "student_code": "UI-PREVIEW-ONLY", "full_name": "Nhân viên kiểm thử giao diện", "consent": True})
        self.assertEqual(code, 200)
        employee_id = employee["id"]
        _, _, stores = self.payload("/api/v1/stores")
        store_id = stores["items"][0]["id"]
        code, _, invitation = self.payload("/api/v1/admin/face-enrollment/invitations", method="POST",
            data={"student_id": employee_id, "store_id": store_id, "invitation_minutes": 5})
        self.assertEqual(code, 200)
        self.assertFalse(invitation["capture_https_ready"])
        self.assertTrue(invitation["qr_url"].startswith(self.url + "/enroll#invite="))
        self.assertTrue(invitation["qr_data_url"].startswith("data:image/png;base64,"))
        # Preserve HTTPS guard; do not redeem an employee token over HTTP.
        self.assertEqual(self.request("/api/v1/qr-enrollment/redeem", method="POST", data={
            "invite_secret": "x" * 48})[0], 403)

    def test_05_hardware_and_external_calls_unavailable(self):
        cases = [
            ("GET", "/api/v1/media/capabilities"),
            ("POST", "/api/v1/media/gateway/restart"),
            ("POST", "/api/v1/camera/reconnect"),
            ("GET", "/api/v1/camera/frame.jpg"),
            ("POST", "/api/v1/cameras/devices"),
            ("GET", "/api/v1/admin/mobile-access"),
            ("POST", "/api/v1/recognition/frame"),
            ("POST", "/api/v1/video/clips"),
            ("POST", "/api/v1/backups/import/preview"),
            ("POST", "/api/v1/sync/receive"),
            ("POST", "/api/v1/auth/sms/send"),
        ]
        for method, path in cases:
            code, _, payload = self.payload(path, method=method, data={} if method == "POST" else None)
            # Existing sensitive-action guard may block earlier; either way no operation.
            self.assertIn(code, {403, 503}, (path, payload))
            if code == 503:
                self.assertEqual(payload["code"], "UI_PREVIEW_UNAVAILABLE", path)
        self.assertEqual(self.request("/api/v1/camera/reconnect", method="POST", data={}, anonymous=True)[0], 401)
        for table in ["recognition_events", "attendance_records", "face_templates", "hr_events"]:
            self.assertEqual(self.main.fetchone(f"SELECT COUNT(*) AS n FROM {table}")["n"], 0, table)

    def test_06_logout_and_login_actual_sessions(self):
        self.assertEqual(self.request("/api/v1/auth/logout", method="POST", data={})[0], 200)
        self.assertEqual(self.request("/api/v1/admin/users")[0], 401)
        self.assertEqual(self.request("/api/v1/auth/login", method="POST", data={
            "username": "preview-owner", "password": self.password})[0], 200)
        _, _, status = self.payload("/api/v1/auth/status")
        self.assertTrue(status["authenticated"])

    def test_06b_manager_cannot_access_owner_admin_apis(self):
        code, _, _ = self.payload("/api/v1/admin/users", method="POST", data={
            "username": "preview-manager", "display_name": "Preview Manager",
            "role": "MANAGER", "password": self.password, "confirm_password": self.password})
        self.assertEqual(code, 200)
        self.assertEqual(self.request("/api/v1/auth/logout", method="POST", data={})[0], 200)
        self.assertEqual(self.request("/api/v1/auth/login", method="POST", data={
            "username": "preview-manager", "password": self.password})[0], 200)
        self.assertEqual(self.request("/api/v1/admin/users")[0], 403)
        self.assertEqual(self.request("/api/v1/admin/face-enrollment/requests")[0], 403)
        self.assertEqual(self.request('/api/v1/stores', method='POST', data={
            'store_code': 'DENIED-CATALOG', 'store_name': 'Must not be saved'})[0], 403)
        self.assertEqual(self.request(f'/api/v1/stores/{self.catalog_store_id}', method='PATCH', data={'store_name': 'Denied'})[0], 403)
        self.assertEqual(self.request('/api/v1/zones', method='POST', data={'store_id': self.catalog_store_id, 'zone_name': 'Denied'})[0], 403)
        self.assertEqual(self.payload('/api/v1/zones')[2]['items'], [])
        self.assertEqual(self.request(f'/api/v1/dashboard/summary?store_id={self.catalog_store_id}')[0], 403)

    def test_07_production_still_fails_closed_before_database(self):
        from module_app import mediamtx_runtime
        with patch.object(self.main, "UI_PREVIEW", False), \
             patch.dict("os.environ", {"BTMH_ENV": "production"}), \
             patch.object(mediamtx_runtime, "resolve_mediamtx",
                          return_value=mediamtx_runtime.MediaMTXRuntime(None, "MEDIAMTX_NOT_INSTALLED")), \
             patch.object(self.main, "init_db") as initialize:
            with self.assertRaisesRegex(RuntimeError, "MEDIAMTX_NOT_INSTALLED"):
                self.main.startup()
            initialize.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
