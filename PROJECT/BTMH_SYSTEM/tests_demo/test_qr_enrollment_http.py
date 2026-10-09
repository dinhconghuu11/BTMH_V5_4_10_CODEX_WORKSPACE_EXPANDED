"""Actual QR HTTP handlers/middleware, compiled without app/model/DB boot.

FastAPI import is sandbox-blocked by typing_extensions permissions. This suite
uses tiny HTTP/app adapters and actual production function bodies. It verifies
the installed exception handler directly, not the unavailable ASGI parser.
"""
from __future__ import annotations

import ast
import asyncio
import base64
from collections import OrderedDict
from contextlib import contextmanager
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import threading
import time
import types
import unittest
from urllib.parse import urlsplit

import cv2
import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / "module_app"


class HTTPException(Exception):
    def __init__(self, status_code, detail=None, headers=None):
        super().__init__(str(detail))
        self.status_code, self.detail, self.headers = status_code, detail, headers or {}


class RequestValidationError(Exception):
    pass


class Response:
    def __init__(self, content=None, status_code=200, headers=None, media_type=None, **kwargs):
        self.content, self.status_code = content, status_code
        self.headers, self.media_type = dict(headers or {}), media_type
        self.cookie_calls = []

    @property
    def body(self):
        return json.dumps(self.content, ensure_ascii=False).encode()

    def set_cookie(self, key, value, **kwargs):
        self.cookie_calls.append((key, value, kwargs))
        cookie = SimpleCookie()
        cookie[key] = value
        for name, val in kwargs.items():
            cookie[key][name.replace("_", "-")] = val
        self.headers["Set-Cookie"] = cookie.output(header="").strip()

    async def __call__(self, scope, receive, send):
        headers = [(key.lower().encode("ascii"), str(value).encode("ascii")) for key, value in self.headers.items()]
        await send({"type": "http.response.start", "status": self.status_code, "headers": headers})
        await send({"type": "http.response.body", "body": self.body, "more_body": False})


class Request:
    def __init__(self, path, *, scheme="https", method="POST", host="store.example:9443", headers=None, cookie=None):
        url = scheme + "://" + host + path
        parsed = urlsplit(url)
        self.url = types.SimpleNamespace(path=parsed.path, scheme=parsed.scheme, hostname=parsed.hostname)
        self.base_url = scheme + "://" + host + "/"
        self.headers = {"origin": scheme + "://" + host, "content-type": "application/json"}
        self.headers.update(headers or {})
        self.method = method
        self.cookies = {"btmh_enrollment_capture": cookie} if cookie else {}
        self.client = types.SimpleNamespace(host="test-client")
        self.query_params = {}


class App:
    def __init__(self):
        self.routes = {}
        self.exception_handlers = {}
        self.middleware_classes = []

    def add_middleware(self, middleware):
        self.middleware_classes.append(middleware)

    def _route(self, method, path):
        def register(fn):
            self.routes[method, path] = fn
            return fn
        return register

    def get(self, path):
        return self._route("GET", path)

    def post(self, path):
        return self._route("POST", path)

    def middleware(self, kind):
        return lambda fn: fn

    def exception_handler(self, kind):
        def register(fn):
            self.exception_handlers[kind] = fn
            return fn
        return register


class EnrollmentError(Exception):
    def __init__(self, message, code="INVALID_REQUEST", status=400, field=None):
        super().__init__(message)
        self.code, self.status, self.field = code, status, field


class FakeService:
    EnrollmentError = EnrollmentError

    def __init__(self):
        self.calls = []
        self.reset_before_stage = False
        self.rows = {
            "desktop": {"id": "desktop", "student_id": 7, "store_id": 3, "source_kind": "DESKTOP",
                        "created_by_user_id": 1, "status": "CAPTURING", "revision": 0},
            "mobile": {"id": "mobile", "student_id": 7, "store_id": 3, "source_kind": "QR_MOBILE",
                       "created_by_user_id": 1, "status": "CAPTURING", "revision": 0},
        }

    def _row(self, request_id):
        if request_id not in self.rows:
            raise EnrollmentError("Không tìm thấy phiên đăng ký", "REQUEST_NOT_FOUND", 404)
        return self.rows[request_id]

    def get_request(self, actor, request_id):
        self.calls.append(("get", request_id))
        return {"request": dict(self._row(request_id))}

    @contextmanager
    def desktop_capture_lease(self, actor, request_id, student_id=None):
        row = self._row(request_id)
        if row["source_kind"] != "DESKTOP" or row["created_by_user_id"] != actor["id"] or (student_id is not None and student_id != row["student_id"]):
            raise EnrollmentError("Không khớp phiên đăng ký", "CAPTURE_FORBIDDEN", 403)
        if row["status"] != "CAPTURING":
            raise EnrollmentError("Đã gửi bản đăng ký", "ALREADY_SUBMITTED", 409)
        self.calls.append(("desktop_lease", request_id))
        yield dict(row)

    def _session(self, secret):
        if secret != "capture-secret-only-cookie":
            raise EnrollmentError("Phiên đăng ký không hợp lệ", "CAPTURE_FORBIDDEN", 403)
        return self.rows["mobile"]

    def capture_status(self, secret):
        self.calls.append(("status", secret))
        return {"request": dict(self._session(secret))}

    @contextmanager
    def capture_frame_lease(self, secret):
        row = self._session(secret)
        if row["status"] != "CAPTURING":
            raise EnrollmentError("Đã gửi bản đăng ký", "ALREADY_SUBMITTED", 409)
        self.calls.append(("mobile_lease", secret))
        yield dict(row)

    def stage_prepared_request(self, request_id, prepared, **kwargs):
        self.calls.append(("stage", request_id, prepared, kwargs))
        if self.reset_before_stage:
            self.rows[request_id]["revision"] += 1
        if kwargs.get("expected_revision") is not None and kwargs["expected_revision"] != self.rows[request_id]["revision"]:
            raise EnrollmentError("Phiên đăng ký đã thay đổi", "REVISION_CONFLICT", 409)
        self.rows[request_id]["status"] = "PENDING_REVIEW"
        return {"request": dict(self.rows[request_id])}

    def redeem_invitation(self, secret):
        self.calls.append(("redeem", secret))
        return {"request": dict(self.rows["mobile"]), "capture_secret": "capture-secret-only-cookie"}

    def issue_invitation(self, actor, student_id, store_id, **kwargs):
        self.calls.append(("invite", actor, student_id, store_id))
        return {"request": dict(self.rows["mobile"]), "invite_secret": "invite-secret",
                "qr_path": "/enroll#invite=invite-secret"}

    def start_desktop_request(self, actor, student_id, store_id):
        self.calls.append(("start", actor, student_id, store_id))
        return {"request": dict(self.rows["desktop"])}

    def reset_capture(self, secret=None, **kwargs):
        self.calls.append(("reset", secret, kwargs))
        return {"request": dict(self.rows["mobile" if secret else kwargs["request_id"]])}


class FakeCapture:
    def __init__(self):
        self.calls = []
        self.draft = object()

    def frame_upload(self, request_id, student_id, image):
        self.calls.append(("upload", request_id, student_id, image))
        return {"accepted": False, "pad": {"status": "CHECKING"}}

    def prepare(self, request_id, student_id):
        self.calls.append(("prepare", request_id, student_id))
        return self.draft


def production_functions(path, namespace, *, names=None):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = [node for node in tree.body if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                or isinstance(node, ast.ClassDef) and node.name == "EnrollmentBodyLimitMiddleware")
                and (names is None or node.name in names)]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)] + selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)


class EnrollmentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.original_flag = os.environ.get("BTMH_QR_ENROLLMENT_ENABLED")
        os.environ["BTMH_QR_ENROLLMENT_ENABLED"] = "1"
        self.addCleanup(self.restore_flag)
        self.service, self.capture, self.app = FakeService(), FakeCapture(), App()
        self.actor = {"id": 1, "role": "ADMIN"}
        self.permissions = []
        async def previous(request, exc):
            return Response({"legacy": True}, status_code=422)
        self.app.exception_handlers[RequestValidationError] = previous
        self.env = dict(os=os, time=time, threading=threading, base64=base64, OrderedDict=OrderedDict,
                        Path=Path, HTTPException=HTTPException, Request=Request, Response=Response,
                        JSONResponse=Response, FileResponse=Response, RequestValidationError=RequestValidationError,
                        request_validation_exception_handler=previous, service=self.service, CAPTURE=self.capture,
                        QR_COOKIE="btmh_enrollment_capture", QR_PREFIX="/api/v1/qr-enrollment",
                        ADMIN_PREFIX="/api/v1/admin/face-enrollment", _RATE_LOCK=threading.Lock(), _RATE=OrderedDict())
        production_functions(SOURCE / "qr_enrollment_routes.py", self.env)
        def auth(request, permission):
            self.permissions.append(permission)
            return self.actor
        self.env["install_qr_routes"](self.app, SOURCE.parent / "frontend", auth)

    def restore_flag(self):
        if self.original_flag is None:
            os.environ.pop("BTMH_QR_ENROLLMENT_ENABLED", None)
        else:
            os.environ["BTMH_QR_ENROLLMENT_ENABLED"] = self.original_flag

    def handler(self, path, method="POST"):
        return self.app.routes[method, path]

    def payload(self, **kwargs):
        defaults = {"request_id": "desktop", "student_id": 7, "image": "frame-data", "confirm_duplicate": False}
        defaults.update(kwargs)
        return types.SimpleNamespace(**defaults)

    def middleware(self, request, *, signed_in=True, permission=True):
        next_calls = []
        async def run_thread(fn, *args):
            return fn(*args)
        async def call_next(req):
            next_calls.append(req.url.path)
            return Response({"next": True})
        env = dict(self.env, app=self.app, re=re, run_in_threadpool=run_thread,
                   browser_guard=lambda req: None, LEGACY_OTP_API_PATHS=set(), PUBLIC_API_PATHS=set(),
                   MOBILE_PUBLIC_API_PATHS=set(), _AUTHENTICATED_ONLY="authenticated",
                   user_count=lambda: 1, _request_user=lambda req: self.actor if signed_in else None,
                   _request_mobile_user=lambda req: None, has_permission=lambda actor, perm: permission,
                   _request_token=lambda req: "portal-token", sensitive_action_guard=lambda *args: None,
                   _camera_scope_context=lambda *args: None)
        production_functions(SOURCE / "main.py", env,
                             names={"_api_permission_for", "_enforce_camera_request_scope", "_campusface_security_headers"})
        response = asyncio.run(env["_campusface_security_headers"](request, call_next))
        return response, next_calls

    def test_actual_main_middleware_rejects_http_and_cross_origin_before_handler(self):
        for request, code in (
            (Request("/api/v1/qr-enrollment/redeem", scheme="http"), "HTTPS_REQUIRED"),
            (Request("/api/v1/qr-enrollment/frame", headers={"origin": "https://attacker.example"}), "ORIGIN_REJECTED"),
            (Request("/api/v1/qr-enrollment/frame", headers={"content-type": "text/plain"}), "JSON_REQUIRED"),
        ):
            response, calls = self.middleware(request, signed_in=False)
            self.assertEqual(response.content["code"], code)
            self.assertFalse(calls)

    def test_http_guard_exact_origin_port_and_json_get_still_https(self):
        guard = self.env["capability_http_guard"]
        for origin in ("", "https://store.example", "https://store.example:9444", "https://store.example.evil:9443"):
            self.assertEqual(guard(Request("/api/v1/qr-enrollment/frame", headers={"origin": origin})).status_code, 403)
        self.assertEqual(guard(Request("/api/v1/qr-enrollment/frame", headers={"sec-fetch-site": "cross-site"})).status_code, 403)
        self.assertIsNone(guard(Request("/api/v1/qr-enrollment/frame", headers={"content-type": "application/json; charset=utf-8"})))
        self.assertEqual(guard(Request("/api/v1/qr-enrollment/status", scheme="http", method="GET")).status_code, 403)
        self.assertEqual(guard(Request("/api/v1/qr-enrollment/frame", headers={"content-length": "3145729"})).status_code, 413)

    def body_limit(self, path, chunks):
        delivered, received, messages = [], [], []

        async def receive():
            index = len(received)
            received.append(index)
            if index >= len(chunks):
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": chunks[index], "more_body": index + 1 < len(chunks)}

        async def consumer(scope, receive_body, send):
            while True:
                message = await receive_body()
                delivered.append(message["body"])
                if not message.get("more_body"):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"accepted", "more_body": False})

        async def send(message):
            messages.append(message)

        middleware = self.env["EnrollmentBodyLimitMiddleware"](consumer)
        scope = {"type": "http", "method": "POST", "path": path, "headers": []}
        asyncio.run(middleware(scope, receive, send))
        return delivered, received, messages

    def test_real_asgi_body_guard_bounds_chunked_frame_before_consumer_buffers_all(self):
        self.assertIn(self.env["EnrollmentBodyLimitMiddleware"], self.app.middleware_classes)
        chunk = b"x" * (1024 * 1024)
        delivered, received, messages = self.body_limit("/api/v1/qr-enrollment/frame", [chunk, chunk, chunk, b"x", b"unread-tail"])
        self.assertEqual(sum(map(len, delivered)), 3 * 1024 * 1024)
        self.assertEqual(len(received), 4)
        self.assertEqual(messages[0]["status"], 413)
        self.assertEqual(json.loads(messages[1]["body"])["detail"]["code"], "PAYLOAD_TOO_LARGE")
        self.assertIn((b"cache-control", b"no-store"), messages[0]["headers"])

    def test_real_asgi_body_guard_accepts_exact_limit_and_leaves_unrelated_routes(self):
        for path, limit in (("/api/v1/qr-enrollment/frame", 3 * 1024 * 1024),
                            ("/api/v1/qr-enrollment/redeem", 16 * 1024),
                            ("/api/v1/admin/face-enrollment/requests", 16 * 1024)):
            delivered, received, messages = self.body_limit(path, [b"x" * (limit - 1), b"x"])
            self.assertEqual(sum(map(len, delivered)), limit)
            self.assertEqual(messages[0]["status"], 200)
        delivered, received, messages = self.body_limit("/api/v1/unrelated", [b"x" * (3 * 1024 * 1024 + 1)])
        self.assertEqual(len(delivered[0]), 3 * 1024 * 1024 + 1)
        self.assertEqual(messages[0]["status"], 200)

    def test_preparser_redeem_rate_limit_stops_before_route_or_body_consumption(self):
        request = Request("/api/v1/qr-enrollment/redeem")
        for _ in range(10):
            self.assertIsNone(self.env["capability_http_guard"](request))
        response, next_calls = self.middleware(request, signed_in=False)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.content["detail"]["code"], "RATE_LIMITED")
        self.assertEqual(next_calls, [])
        self.assertEqual(self.service.calls, [])

    def test_feature_flag_disables_only_enrollment_not_existing_recognition(self):
        os.environ["BTMH_QR_ENROLLMENT_ENABLED"] = "0"
        for path in ("/api/v1/qr-enrollment/status", "/api/v1/admin/face-enrollment/requests", "/api/v1/enrollment/frame"):
            response, calls = self.middleware(Request(path, method="GET"))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.content["code"], "ENROLLMENT_DISABLED")
            self.assertFalse(calls)
        response, calls = self.middleware(Request("/api/v1/recognition/frame"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(calls)

    def test_qr_capability_has_no_portal_or_viewer_authority(self):
        response, calls = self.middleware(Request("/api/v1/qr-enrollment/status", method="GET", cookie="capture-secret-only-cookie"), signed_in=False)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(calls)
        response, calls = self.middleware(Request("/api/v1/employees", method="GET", cookie="capture-secret-only-cookie"), signed_in=False)
        self.assertEqual(response.status_code, 401)
        self.assertFalse(calls)
        response, calls = self.middleware(Request("/api/v1/mobile/cameras", method="GET", cookie="capture-secret-only-cookie"), signed_in=False)
        self.assertEqual(response.status_code, 401)
        self.assertFalse(calls)

    def test_redeem_secret_only_narrow_secure_cookie_and_safe_json(self):
        request = Request("/api/v1/qr-enrollment/redeem")
        response = self.handler(request.url.path)(self.payload(invite_secret="invite-secret"), request)
        self.assertNotIn("capture_secret", response.content)
        self.assertNotIn("capture-secret-only-cookie", response.body.decode())
        self.assertNotIn("invite-secret", response.body.decode())
        key, value, attrs = response.cookie_calls[0]
        self.assertEqual(key, "btmh_enrollment_capture")
        self.assertEqual(value, "capture-secret-only-cookie")
        self.assertEqual(attrs, {"max_age": 1800, "httponly": True, "secure": True,
                                 "samesite": "strict", "path": "/api/v1/qr-enrollment"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_installed_validation_handler_never_echoes_input_and_preserves_legacy(self):
        handler = self.app.exception_handlers[RequestValidationError]
        exc = RequestValidationError("invalid payload SECRET_IMAGE_OR_PASSWORD")
        exc.body = {"invite_secret": "SECRET_IMAGE_OR_PASSWORD", "image": "data:PRIVATE"}
        for path in ("/api/v1/qr-enrollment/redeem", "/api/v1/admin/face-enrollment/requests", "/api/v1/enrollment/frame"):
            response = asyncio.run(handler(Request(path), exc))
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("SECRET", response.body.decode())
            self.assertNotIn("data:PRIVATE", response.body.decode())
        response = asyncio.run(handler(Request("/api/v1/auth/login"), exc))
        self.assertEqual(response.content, {"legacy": True})

    def test_mobile_frame_binds_server_target_and_only_uses_uploaded_image(self):
        request = Request("/api/v1/qr-enrollment/frame", cookie="capture-secret-only-cookie")
        payload = self.payload(image="uploaded-image", student_id=999, store_id=888, camera_id=42,
                               request_id="attacker-request", session_id="attacker-session", confirm_duplicate=True)
        response = Response()
        self.handler(request.url.path)(payload, request, response)
        self.assertEqual(self.capture.calls, [("upload", "mobile", 7, "uploaded-image")])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        with self.assertRaises(HTTPException) as caught:
            self.handler(request.url.path)(payload, Request(request.url.path), Response())
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(len(self.capture.calls), 1)

    def test_owner_admin_role_required_even_with_employee_permission(self):
        handler = self.handler("/api/v1/admin/face-enrollment/requests")
        for role in ("VIEWER", "MANAGER", "EMPLOYEE"):
            self.actor["role"] = role
            with self.assertRaises(HTTPException) as caught:
                handler(self.payload(store_id=3), Request("/api/v1/admin/face-enrollment/requests"), Response())
            self.assertEqual(caught.exception.status_code, 403)
        self.assertFalse(self.service.calls)
        for role in ("ADMIN", "SUPER_ADMIN"):
            self.actor["role"] = role
            handler(self.payload(store_id=3), Request("/api/v1/admin/face-enrollment/requests"), Response())
        self.assertEqual(self.permissions, ["employee.enroll"] * 5)

    def test_actual_legacy_finalize_delegates_to_staging_never_direct_publish(self):
        app = App()
        permission_calls = []
        env = dict(self.env, app=app, _auth_permission=lambda req, perm: permission_calls.append(perm) or self.actor)
        production_functions(SOURCE / "main.py", env, names={"enrollment_frame", "enrollment_finalize", "enrollment_reset"})
        response = app.routes["POST", "/api/v1/enrollment/finalize"](self.payload(), Request("/api/v1/enrollment/finalize"))
        self.assertEqual(response["request"]["status"], "PENDING_REVIEW")
        self.assertEqual(self.capture.calls, [("prepare", "desktop", 7)])
        stage = [call for call in self.service.calls if call[0] == "stage"]
        self.assertEqual(stage[0][2], self.capture.draft)
        self.assertEqual(stage[0][3], {"actor": self.actor, "expected_revision": 0})
        self.assertEqual(permission_calls, ["employee.enroll"])

    def test_reset_between_prepare_and_stage_cannot_submit_previous_revision(self):
        self.service.reset_before_stage = True
        for mobile in (False, True):
            with self.assertRaises(HTTPException) as caught:
                if mobile:
                    request = Request("/api/v1/qr-enrollment/submit", cookie="capture-secret-only-cookie")
                    self.handler(request.url.path)(self.payload(), request, Response())
                else:
                    self.env["desktop_finalize"](self.payload(), Request("/api/v1/enrollment/finalize"), self.actor)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(self.service.rows["mobile" if mobile else "desktop"]["status"], "CAPTURING")

    def test_pending_mobile_and_desktop_replay_do_not_reprepare(self):
        self.service.rows["mobile"]["status"] = "NEEDS_DUPLICATE_REVIEW"
        request = Request("/api/v1/qr-enrollment/submit", cookie="capture-secret-only-cookie")
        result = self.handler(request.url.path)(self.payload(), request, Response())
        self.assertEqual(result["request"]["status"], "NEEDS_DUPLICATE_REVIEW")
        self.service.rows["desktop"]["status"] = "PENDING_REVIEW"
        result = self.env["desktop_finalize"](self.payload(), Request("/api/v1/enrollment/finalize"), self.actor)
        self.assertEqual(result["request"]["status"], "PENDING_REVIEW")
        self.assertFalse(self.capture.calls)
        self.assertFalse(any(call[0] == "stage" for call in self.service.calls))

    def test_pending_desktop_replay_keeps_original_creator_and_student_binding(self):
        self.service.rows["desktop"]["status"] = "PENDING_REVIEW"
        for payload, actor in ((self.payload(student_id=999), self.actor),
                               (self.payload(), {"id": 2, "role": "ADMIN"})):
            with self.assertRaises(HTTPException) as caught:
                self.env["desktop_finalize"](payload, Request("/api/v1/enrollment/finalize"), actor)
            self.assertEqual(caught.exception.status_code, 403)
        self.assertFalse(self.capture.calls)

    def test_absent_request_and_client_duplicate_override_cannot_stage(self):
        for payload, expected in ((self.payload(request_id=None), 409), (self.payload(request_id="unknown"), 404),
                                  (self.payload(confirm_duplicate=True), 403)):
            with self.assertRaises(HTTPException) as caught:
                self.env["desktop_finalize"](payload, Request("/api/v1/enrollment/finalize"), self.actor)
            self.assertEqual(caught.exception.status_code, expected)
        self.assertFalse(self.capture.calls)
        self.assertFalse(any(call[0] == "stage" for call in self.service.calls))

    def test_actual_local_qr_encode_decode_and_secret_fragment(self):
        function = self.env.get("_invitation_result")
        self.assertIsNotNone(function, "local QR function not implemented")
        url_request = Request("/api/v1/admin/face-enrollment/invitations")
        path = "/enroll#invite=" + "A" * 43
        result = function({"invite_secret": "A" * 43, "qr_path": path}, url_request)
        self.assertNotIn("invite_secret", result)
        self.assertTrue(result["capture_https_ready"])
        expected = "https://store.example:9443" + path
        self.assertEqual(result["qr_url"], expected)
        raw = base64.b64decode(result["qr_data_url"].split(",", 1)[1], validate=True)
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        value, points, _ = cv2.QRCodeDetector().detectAndDecode(image)
        self.assertIsNotNone(points)
        self.assertEqual(value, expected)
        local = function({"qr_path": path}, Request("/api/v1/admin/face-enrollment/invitations", host="localhost:8000", scheme="http"))
        self.assertFalse(local["capture_https_ready"])


if __name__ == "__main__":
    unittest.main()
