"""Reviewed QR/desktop enrollment; exactly two additive tables, no import writes.

Drafts never enter the active index. Only explicit authenticated review publishes
the existing encrypted template format, inside the shared publication transaction.
Capture transport/TLS/CSRF/rate limits belong to the HTTP adapter; quality and PAD
decisions belong to the existing shared enrollment capture wrapper.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import uuid

from . import auth, db
from .demo_context import _positive_id, _safe_name, scoped_store_ids

ACTIVE = ("CAPTURING", "PENDING_REVIEW", "NEEDS_DUPLICATE_REVIEW")
PENDING = ("PENDING_REVIEW", "NEEDS_DUPLICATE_REVIEW")
STATUSES = (*ACTIVE, "APPROVED", "REJECTED", "EXPIRED", "CANCELLED")
CAPTURE_MINUTES = 30
REVIEW_HOURS = 72
MAX_BLOB_BYTES = 3 * 1024 * 1024
_PUBLICATION_LOCK = threading.RLock()
_FRAME_LOCK = threading.Lock()
_INFLIGHT: set[str] = set()
_CALLBACKS: dict = {}


class EnrollmentError(ValueError):
    def __init__(self, message, code="INVALID_ENROLLMENT_INPUT", status=400, field=""):
        self.code, self.status, self.field = code, status, field
        super().__init__(message)


@dataclass(frozen=True)
class PreparedDraft:
    template_blob: bytes
    preview_blob: bytes | None
    pose_count: int
    quality: dict
    pad: dict
    duplicate: dict | None = None


def _now(value=None):
    value = value or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EnrollmentError("Thời gian máy chủ không hợp lệ.")
    return value.astimezone(timezone.utc)


def _stamp(value):
    return value.isoformat()


def _date(value):
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


def _rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


@contextmanager
def publication_transaction():
    """Also used by the existing consent-withdrawal transaction adapter.

    SQLite takes a write reservation; PostgreSQL takes a cross-process advisory
    transaction lock. Retirement/index callbacks must run after this commits.
    """
    with _PUBLICATION_LOCK, db.connection() as conn:
        if conn.mode == "postgres":
            conn.execute("SELECT pg_advisory_xact_lock(54100119)")
        else:
            raw = getattr(conn, "raw", None)
            if raw is not None and not raw.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
        yield conn


def ensure_qr_enrollment_schema():
    """Only CREATE TABLE/INDEX; does not migrate any existing rows or schema."""
    with publication_transaction() as conn:
        integer = "BIGINT" if conn.mode == "postgres" else "INTEGER"
        blob = "BYTEA" if conn.mode == "postgres" else "BLOB"
        conn.execute(f"""CREATE TABLE IF NOT EXISTS face_enrollment_requests (
            id TEXT PRIMARY KEY,
            student_id {integer} NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            store_id {integer} NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            source_kind TEXT NOT NULL CHECK(source_kind IN ('DESKTOP','QR_MOBILE')),
            status TEXT NOT NULL CHECK(status IN ('CAPTURING','PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW','APPROVED','REJECTED','EXPIRED','CANCELLED')),
            template_blob {blob}, preview_blob {blob}, pose_count INTEGER NOT NULL DEFAULT 0,
            quality_json TEXT NOT NULL DEFAULT '{{}}', pad_json TEXT NOT NULL DEFAULT '{{}}', duplicate_json TEXT NOT NULL DEFAULT '{{}}',
            created_by_user_id {integer} NOT NULL REFERENCES system_users(id),
            submitted_at TEXT, expires_at TEXT NOT NULL,
            reviewed_by_user_id {integer} REFERENCES system_users(id) ON DELETE SET NULL, reviewed_at TEXT,
            review_reason TEXT NOT NULL DEFAULT '', duplicate_override INTEGER NOT NULL DEFAULT 0 CHECK(duplicate_override IN (0,1)),
            revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS qr_enrollment_invites (
            id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES face_enrollment_requests(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_by_user_id {integer} NOT NULL REFERENCES system_users(id),
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL, redeemed_at TEXT, revoked_at TEXT,
            session_hash TEXT UNIQUE, session_expires_at TEXT
        )""")
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_face_enrollment_review ON face_enrollment_requests(status,submitted_at)",
            "CREATE INDEX IF NOT EXISTS idx_face_enrollment_employee ON face_enrollment_requests(student_id,created_at)",
            "CREATE INDEX IF NOT EXISTS idx_face_enrollment_store ON face_enrollment_requests(store_id,status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_face_enrollment_one_active ON face_enrollment_requests(student_id) WHERE status IN ('CAPTURING','PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW')",
        ):
            conn.execute(sql)


def bind_runtime_callbacks(*, retire_capture=None, reset_capture=None, refresh_active_index=None,
                           save_approved_preview=None, duplicate_checker=None):
    """Optional isolated-test adapter; normal runtime uses lazy existing modules."""
    for key, value in locals().copy().items():
        if value is not None:
            if not callable(value):
                raise TypeError("Enrollment callback must be callable")
            _CALLBACKS[key] = value


def _callback(name):
    if name in _CALLBACKS:
        return _CALLBACKS[name]
    if name == "duplicate_checker":
        from .registry import recheck_prepared_duplicate
        return recheck_prepared_duplicate
    from . import enrollment_capture
    if name in {"retire_capture", "reset_capture"}:
        return getattr(enrollment_capture.CAPTURE, name)
    return getattr(enrollment_capture, name)


def retire_requests(request_ids):
    # Durable status already rejects every late frame even if transient cleanup
    # fails. Never undo a committed decision because a cleanup callback failed.
    for request_id in set(request_ids):
        try:
            _callback("retire_capture")(request_id)
        except Exception:
            pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _decoded(value):
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _audit(conn, row, action, now, actor_id=None, reason=""):
    detail = {"request_id": row["id"], "store_id": row["store_id"], "actor_id": actor_id,
              "action": action, "reason": reason, "source_kind": row["source_kind"]}
    conn.execute("INSERT INTO audit_events(category,event_type,status,student_id,camera_source,event_at,detail_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 ("ENROLLMENT", action, "INFO", row["student_id"], "", _stamp(now), _json(detail), _stamp(now)))


def _admin(conn, actor):
    actor_id = _positive_id((actor or {}).get("id"))
    user = _one(conn, "SELECT id,role,active FROM system_users WHERE id=?", (actor_id,)) if actor_id else None
    if not user or not user["active"] or user["role"] not in {"SUPER_ADMIN", "ADMIN"}:
        raise EnrollmentError("Chỉ Chủ sở hữu hoặc Quản trị viên được quản lý đăng ký FaceID.", "ENROLLMENT_FORBIDDEN", 403)
    public = {**(actor or {}), **user, "permissions": auth.permissions_for_role(user["role"])}
    if not auth.has_permission(public, "employee.enroll"):
        raise EnrollmentError("Tài khoản không có quyền đăng ký FaceID.", "ENROLLMENT_FORBIDDEN", 403)
    return public


def _scope_sql(actor, alias="r"):
    stores = scoped_store_ids(actor)
    if stores is None:
        return "", []
    values = sorted({_positive_id(x) for x in stores} - {None})
    if not values:
        return " AND 1=0", []
    return f" AND {alias}.store_id IN ({','.join('?' for _ in values)})", values


def _target(conn, student_id, store_id, actor=None, *, consent=False):
    sid, store = _positive_id(student_id), _positive_id(store_id)
    if not sid or not store:
        raise EnrollmentError("Chọn nhân viên và cửa hàng đăng ký hợp lệ.", field="store_id")
    if actor is not None:
        allowed = scoped_store_ids(actor)
        if allowed is not None and store not in allowed:
            raise EnrollmentError("Cửa hàng nằm ngoài phạm vi tài khoản.", "STORE_SCOPE_DENIED", 403)
    employee = _one(conn, "SELECT id,student_code,full_name,biometric_consent_status FROM students WHERE id=?", (sid,))
    location = _one(conn, "SELECT id,store_name,status FROM stores WHERE id=?", (store,))
    if not employee or not location or location["status"] != "ACTIVE":
        raise EnrollmentError("Nhân viên hoặc cửa hàng đăng ký không còn khả dụng.", "ENROLLMENT_TARGET_UNAVAILABLE", 409)
    assignments = _rows(conn, "SELECT store_id FROM employee_store_assignments WHERE student_id=?", (sid,))
    # The explicit enrollment store is not an HR assignment. With no assignment,
    # preserve the authorized request binding; never auto-select/insert a store.
    if assignments and store not in {int(x["store_id"]) for x in assignments}:
        raise EnrollmentError("Cửa hàng đăng ký không khớp phân công hiện tại.", "STORE_ASSIGNMENT_MISMATCH", 403)
    if consent and employee["biometric_consent_status"] != "GRANTED":
        raise EnrollmentError("Cần sự đồng ý sinh trắc học hiện tại của nhân viên.", "CONSENT_REQUIRED", 403)
    return employee, location


def _request(conn, request_id, actor=None):
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise EnrollmentError("Không tìm thấy yêu cầu đăng ký.", "REQUEST_NOT_FOUND", 404)
    scope, params = _scope_sql(actor) if actor is not None else ("", [])
    row = _one(conn, "SELECT r.* FROM face_enrollment_requests r WHERE r.id=?" + scope, [request_id, *params])
    if not row:
        raise EnrollmentError("Không tìm thấy yêu cầu đăng ký.", "REQUEST_NOT_FOUND", 404)
    return row


def _dto(conn, row, *, mobile=False):
    employee = _one(conn, "SELECT student_code,full_name,biometric_consent_status FROM students WHERE id=?", (row["student_id"],)) or {}
    store = _one(conn, "SELECT store_name FROM stores WHERE id=?", (row["store_id"],)) or {}
    fields = ("id", "student_id", "store_id", "source_kind", "status", "revision", "expires_at", "submitted_at", "created_at", "updated_at", "pose_count")
    result = {key: row.get(key) for key in fields}
    result.update(student_code=_safe_name(employee.get("student_code")), full_name=_safe_name(employee.get("full_name")),
                  store_name=_safe_name(store.get("store_name")), consent_status=employee.get("biometric_consent_status", "NOT_GRANTED"),
                  has_preview=bool(row.get("preview_blob")), quality=_decoded(row.get("quality_json")), pad=_decoded(row.get("pad_json")))
    if not mobile:
        result.update(duplicate=_decoded(row.get("duplicate_json")), duplicate_override=bool(row.get("duplicate_override")),
                      reviewed_by_user_id=row.get("reviewed_by_user_id"), reviewed_at=row.get("reviewed_at"),
                      review_reason=row.get("review_reason", ""), created_by_user_id=row["created_by_user_id"])
    return result


def _reason(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise EnrollmentError("Nhập lý do quyết định từ 1 đến 500 ký tự.", "REVIEW_REASON_REQUIRED", field="reason")
    return _safe_name(value.strip(), 500)


def _revision(row, expected):
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != row["revision"]:
        raise EnrollmentError("Yêu cầu đã thay đổi. Hãy tải lại trước khi quyết định.", "REVISION_CONFLICT", 409)


def _terminal(conn, row, status, reason, now, actor_id=None):
    conn.execute("UPDATE face_enrollment_requests SET status=?,template_blob=NULL,preview_blob=NULL,review_reason=?,reviewed_by_user_id=?,reviewed_at=?,revision=revision+1,updated_at=? WHERE id=?",
                 (status, reason, actor_id, _stamp(now), _stamp(now), row["id"]))
    conn.execute("UPDATE qr_enrollment_invites SET revoked_at=COALESCE(revoked_at,?),session_hash=NULL WHERE request_id=?", (_stamp(now), row["id"]))
    _audit(conn, row, status, now, actor_id, reason)


def expire_requests(*, now=None):
    now = _now(now)
    retired = []
    with publication_transaction() as conn:
        for row in _rows(conn, "SELECT * FROM face_enrollment_requests WHERE status IN ('CAPTURING','PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW') AND expires_at<=?", (_stamp(now),)):
            _terminal(conn, row, "EXPIRED", "DEADLINE_EXPIRED", now)
            retired.append(row["id"])
    retire_requests(retired)
    return len(retired)


def recover_incomplete_captures(*, now=None):
    now = _now(now)
    retired = []
    with publication_transaction() as conn:
        for row in _rows(conn, "SELECT * FROM face_enrollment_requests WHERE status='CAPTURING'"):
            _terminal(conn, row, "EXPIRED", "SERVER_RESTART", now)
            retired.append(row["id"])
    retire_requests(retired)
    expire_requests(now=now)
    return len(retired)


def _secret_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise EnrollmentError("Liên kết hoặc phiên đăng ký không còn khả dụng.", "CAPTURE_UNAVAILABLE", 410)
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _minutes(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 5 <= value <= 60:
        raise EnrollmentError("Thời hạn lời mời phải từ 5 đến 60 phút.", field="invitation_minutes")
    return value


def _create(conn, actor, student_id, store_id, source, now, minutes=15):
    _target(conn, student_id, store_id, actor)
    retired = []
    for old in _rows(conn, "SELECT * FROM face_enrollment_requests WHERE student_id=? AND status IN ('CAPTURING','PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW')", (student_id,)):
        _terminal(conn, old, "CANCELLED", "REPLACED_BY_NEW_REQUEST", now, actor["id"])
        retired.append(old["id"])
    deadline = now + timedelta(minutes=minutes if source == "QR_MOBILE" else CAPTURE_MINUTES)
    rid = uuid.uuid4().hex
    conn.execute("INSERT INTO face_enrollment_requests(id,student_id,store_id,source_kind,status,created_by_user_id,expires_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                 (rid, student_id, store_id, source, "CAPTURING", actor["id"], _stamp(deadline), _stamp(now), _stamp(now)))
    row = _request(conn, rid)
    _audit(conn, row, "REQUEST_CREATED", now, actor["id"])
    result = {"request": _dto(conn, row)}
    if source == "QR_MOBILE":
        secret = secrets.token_urlsafe(32)
        iid = uuid.uuid4().hex
        conn.execute("INSERT INTO qr_enrollment_invites(id,request_id,token_hash,created_by_user_id,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                     (iid, rid, _secret_hash(secret), actor["id"], _stamp(now), _stamp(deadline)))
        result.update(invite_id=iid, invite_secret=secret, qr_path="/enroll#invite=" + secret, invite_expires_at=_stamp(deadline))
    return result, retired


def issue_invitation(actor, student_id, store_id, *, invitation_minutes=15, now=None):
    now, minutes = _now(now), _minutes(invitation_minutes)
    expire_requests(now=now)
    with publication_transaction() as conn:
        actor = _admin(conn, actor)
        result, retired = _create(conn, actor, student_id, store_id, "QR_MOBILE", now, minutes)
    retire_requests(retired)
    return result


def start_desktop_request(actor, student_id, store_id, *, now=None):
    now = _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        actor = _admin(conn, actor)
        result, retired = _create(conn, actor, student_id, store_id, "DESKTOP", now)
    retire_requests(retired)
    return result


def redeem_invitation(invite_secret, *, now=None):
    now, digest = _now(now), _secret_hash(invite_secret)
    expire_requests(now=now)
    with publication_transaction() as conn:
        invite = _one(conn, "SELECT * FROM qr_enrollment_invites WHERE token_hash=?", (digest,))
        if not invite or invite["redeemed_at"] or invite["revoked_at"] or not _date(invite["expires_at"]) or _date(invite["expires_at"]) <= now:
            raise EnrollmentError("Lời mời đã dùng, thu hồi hoặc hết hạn.", "INVITATION_UNAVAILABLE", 410)
        row = _request(conn, invite["request_id"])
        if row["status"] != "CAPTURING" or row["source_kind"] != "QR_MOBILE":
            raise EnrollmentError("Lời mời không còn khả dụng.", "INVITATION_UNAVAILABLE", 410)
        _target(conn, row["student_id"], row["store_id"])
        session = secrets.token_urlsafe(32)
        deadline = now + timedelta(minutes=CAPTURE_MINUTES)
        cursor = conn.execute("UPDATE qr_enrollment_invites SET redeemed_at=?,session_hash=?,session_expires_at=? WHERE id=? AND redeemed_at IS NULL AND revoked_at IS NULL AND expires_at>?",
                              (_stamp(now), _secret_hash(session), _stamp(deadline), invite["id"], _stamp(now)))
        if cursor.rowcount != 1:
            raise EnrollmentError("Lời mời không còn khả dụng.", "INVITATION_UNAVAILABLE", 410)
        conn.execute("UPDATE face_enrollment_requests SET expires_at=?,updated_at=? WHERE id=?", (_stamp(deadline), _stamp(now), row["id"]))
        row = _request(conn, row["id"])
        _audit(conn, row, "INVITATION_REDEEMED", now)
        return {"capture_secret": session, "request": _dto(conn, row, mobile=True), "session_expires_at": _stamp(deadline)}


def _session(conn, secret, now, *, capturing=False, consent=False):
    digest = _secret_hash(secret)
    invite = _one(conn, "SELECT * FROM qr_enrollment_invites WHERE session_hash=?", (digest,))
    if not invite or not invite["redeemed_at"] or invite["revoked_at"] or not _date(invite["session_expires_at"]) or _date(invite["session_expires_at"]) <= now:
        raise EnrollmentError("Phiên đăng ký đã hết hạn hoặc thu hồi.", "CAPTURE_UNAVAILABLE", 410)
    row = _request(conn, invite["request_id"])
    if row["status"] not in ACTIVE or not _date(row["expires_at"]) or _date(row["expires_at"]) <= now:
        raise EnrollmentError("Phiên đăng ký đã kết thúc.", "CAPTURE_UNAVAILABLE", 410)
    if capturing and row["status"] != "CAPTURING":
        raise EnrollmentError("Bản đăng ký đã gửi và đang chờ duyệt.", "ALREADY_SUBMITTED", 409)
    _target(conn, row["student_id"], row["store_id"], consent=consent)
    return row, invite


def capture_status(session_secret, *, now=None):
    now = _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        row, invite = _session(conn, session_secret, now)
        result = _dto(conn, row, mobile=True)
        result.update(session_expires_at=invite["session_expires_at"], capture_allowed=row["status"] == "CAPTURING" and result["consent_status"] == "GRANTED",
                      can_consent=row["status"] == "CAPTURING" and result["consent_status"] == "NOT_GRANTED", can_submit=False)
        return {"request": result, "session_expires_at": invite["session_expires_at"]}


def accept_capture_consent(session_secret, *, granted=True, now=None):
    if granted is not True:
        raise EnrollmentError("Cần xác nhận đồng ý trước khi quét FaceID.", "CONSENT_REQUIRED", 403)
    now = _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        row, _ = _session(conn, session_secret, now, capturing=True)
        employee, _ = _target(conn, row["student_id"], row["store_id"])
        if employee["biometric_consent_status"] == "WITHDRAWN":
            raise EnrollmentError("Sự đồng ý đã bị thu hồi; cần quản trị viên xử lý lại.", "CONSENT_WITHDRAWN", 403)
        if employee["biometric_consent_status"] != "GRANTED":
            conn.execute("UPDATE students SET biometric_consent_status='GRANTED',biometric_consent_at=?,biometric_consent_withdrawn_at=NULL,updated_at=? WHERE id=?",
                         (_stamp(now), _stamp(now), row["student_id"]))
            _audit(conn, row, "CONSENT_GRANTED", now)
    return capture_status(session_secret, now=now)


def _desktop(conn, actor, request_id, student_id, now, *, consent=True):
    actor = _admin(conn, actor)
    row = _request(conn, request_id, actor)
    if row["source_kind"] != "DESKTOP" or row["created_by_user_id"] != actor["id"]:
        raise EnrollmentError("Phiên quét không thuộc tài khoản này.", "CAPTURE_FORBIDDEN", 403)
    if student_id is not None and _positive_id(student_id) != row["student_id"]:
        raise EnrollmentError("Nhân viên không khớp phiên quét.", "CAPTURE_TARGET_MISMATCH", 403)
    if row["status"] not in ACTIVE or not _date(row["expires_at"]) or _date(row["expires_at"]) <= now:
        raise EnrollmentError("Phiên đăng ký đã kết thúc.", "CAPTURE_UNAVAILABLE", 410)
    _target(conn, row["student_id"], row["store_id"], actor, consent=consent)
    return row


@contextmanager
def _lease(load, now):
    expire_requests(now=now)
    with publication_transaction() as conn:
        row = load(conn)
        if row["status"] != "CAPTURING":
            raise EnrollmentError("Bản đăng ký đã gửi và đang chờ duyệt.", "ALREADY_SUBMITTED", 409)
        binding = {key: row[key] for key in ("id", "student_id", "store_id", "revision", "source_kind", "expires_at")}
    with _FRAME_LOCK:
        if binding["id"] in _INFLIGHT or len(_INFLIGHT) >= 32:
            raise EnrollmentError("Đang xử lý ảnh trước. Hãy thử lại.", "FRAME_BUSY", 409)
        _INFLIGHT.add(binding["id"])
    try:
        yield binding
        # Reject results that completed after revocation, reset, consent withdrawal
        # or their fixed deadline. No inference work holds the publication lock.
        check_now = _now() if now is None else now
        with publication_transaction() as conn:
            current = load(conn)
            if current["status"] != "CAPTURING" or current["revision"] != binding["revision"] or _date(current["expires_at"]) <= check_now:
                raise EnrollmentError("Phiên đăng ký đã thay đổi hoặc kết thúc.", "CAPTURE_UNAVAILABLE", 410)
    finally:
        with _FRAME_LOCK:
            _INFLIGHT.discard(binding["id"])


def capture_frame_lease(session_secret, *, now=None):
    instant = _now(now)
    return _lease(lambda conn: _session(conn, session_secret, _now() if now is None else instant, capturing=True, consent=True)[0], instant)


def desktop_capture_lease(actor, request_id, student_id=None, *, now=None):
    instant = _now(now)
    return _lease(lambda conn: _desktop(conn, actor, request_id, student_id, _now() if now is None else instant), instant)


def reset_capture(session_secret=None, *, actor=None, request_id=None, now=None):
    now = _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        row = _session(conn, session_secret, now, capturing=True, consent=True)[0] if session_secret is not None else _desktop(conn, actor, request_id, None, now)
        if row["status"] != "CAPTURING":
            raise EnrollmentError("Bản đăng ký đã gửi.", "ALREADY_SUBMITTED", 409)
        with _FRAME_LOCK:
            if row["id"] in _INFLIGHT:
                raise EnrollmentError("Đang xử lý ảnh trước.", "FRAME_BUSY", 409)
        conn.execute("UPDATE face_enrollment_requests SET revision=revision+1,updated_at=? WHERE id=?", (_stamp(now), row["id"]))
        result = {"request": _dto(conn, _request(conn, row["id"]), mobile=session_secret is not None)}
        # Retire old sample/PAD evidence before exposing the new revision to any
        # frame/finalize lease. A failed transient reset rolls back this revision.
        _callback("reset_capture")(row["id"])
    return result


def _summary(draft, now, *, submitting=True):
    if not isinstance(draft, PreparedDraft) or not isinstance(draft.template_blob, bytes) or not 0 < len(draft.template_blob) <= MAX_BLOB_BYTES:
        raise EnrollmentError("Bản đăng ký chưa sẵn sàng.", "DRAFT_NOT_READY", 409)
    if isinstance(draft.pose_count, bool) or not isinstance(draft.pose_count, int) or draft.pose_count <= 0 or not isinstance(draft.quality, dict) or draft.quality.get("ready") is not True or draft.quality.get("scan_passes") != 2:
        raise EnrollmentError("Cần hoàn tất đủ hai vòng quét.", "QUALITY_NOT_READY", 409)
    if not isinstance(draft.pad, dict) or draft.pad.get("status") != "PASS" or not _date(draft.pad.get("verified_at")):
        raise EnrollmentError("Cần xác minh người thật hiện tại.", "PAD_NOT_READY", 409)
    age = (now - _date(draft.pad["verified_at"])).total_seconds()
    if submitting and not -1 <= age <= 5:
        raise EnrollmentError("Xác minh người thật đã hết hiệu lực; hãy quét lại.", "PAD_STALE", 409)
    if draft.preview_blob is not None and (not isinstance(draft.preview_blob, bytes) or not 0 < len(draft.preview_blob) <= MAX_BLOB_BYTES):
        raise EnrollmentError("Ảnh xem trước không hợp lệ.", "DRAFT_NOT_READY", 409)
    from .crypto import decrypt_bytes
    try:
        if not decrypt_bytes(draft.template_blob):
            raise ValueError()
        if draft.preview_blob and len(decrypt_bytes(draft.preview_blob)) > 2 * 1024 * 1024:
            raise ValueError()
    except Exception:
        raise EnrollmentError("Bản đăng ký mã hóa không hợp lệ.", "DRAFT_NOT_READY", 409) from None
    quality = {key: draft.quality[key] for key in ("ready", "scan_passes", "pose_counts", "target", "mode", "minimum_sample_quality") if key in draft.quality}
    pad = {key: draft.pad[key] for key in ("status", "score", "observations", "reason", "source", "verified_at", "decision_version") if key in draft.pad}
    # All inputs here originate in the shared server wrapper. Still reject invalid
    # JSON/nonfinite values and avoid arbitrary fields in persisted/public summaries.
    try:
        _json(quality), _json(pad)
    except (ValueError, TypeError):
        raise EnrollmentError("Kết quả quét không hợp lệ.", "DRAFT_NOT_READY", 409) from None
    return quality, pad, _duplicate(draft.duplicate)


def _duplicate(value):
    if not value:
        return {}
    sid = _positive_id(value.get("student_id")) if isinstance(value, dict) else None
    try:
        score = float(value.get("score"))
    except (TypeError, ValueError):
        score = float("nan")
    if not sid or not math.isfinite(score):
        raise EnrollmentError("Kết quả kiểm tra trùng không hợp lệ.", "DRAFT_NOT_READY", 409)
    return {"student_id": sid, "score": score, "strong": bool(value.get("strong")),
            "student_code": _safe_name(value.get("student_code")), "full_name": _safe_name(value.get("full_name"))}


def stage_prepared_request(request_id, prepared, *, actor=None, session_secret=None, expected_revision=None, now=None):
    now = _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        row = _session(conn, session_secret, now, consent=True)[0] if session_secret is not None else _desktop(conn, actor, request_id, None, now)
        if row["id"] != request_id:
            raise EnrollmentError("Bản đăng ký không khớp phiên quét.", "CAPTURE_TARGET_MISMATCH", 403)
        if row["status"] in PENDING:
            return {"request": _dto(conn, row, mobile=session_secret is not None), "already_submitted": True}
        if expected_revision is not None:
            _revision(row, expected_revision)
        with _FRAME_LOCK:
            if row["id"] in _INFLIGHT:
                raise EnrollmentError("Đang xử lý ảnh trước.", "FRAME_BUSY", 409)
        quality, pad, duplicate = _summary(prepared, now)
        status = "NEEDS_DUPLICATE_REVIEW" if duplicate else "PENDING_REVIEW"
        conn.execute("UPDATE face_enrollment_requests SET status=?,template_blob=?,preview_blob=?,pose_count=?,quality_json=?,pad_json=?,duplicate_json=?,submitted_at=?,expires_at=?,revision=revision+1,updated_at=? WHERE id=?",
                     (status, prepared.template_blob, prepared.preview_blob, prepared.pose_count, _json(quality), _json(pad), _json(duplicate), _stamp(now), _stamp(now + timedelta(hours=REVIEW_HOURS)), _stamp(now), row["id"]))
        _audit(conn, row, "DRAFT_SUBMITTED", now, actor_id=(actor or {}).get("id"))
        result = {"request": _dto(conn, _request(conn, row["id"]), mobile=session_secret is not None), "already_submitted": False}
    # Session digest remains usable for own pending status/idempotent submit until
    # its original deadline; status forbids frames, consent/reset and new evidence.
    retire_requests([row["id"]])
    return result


def list_requests(actor, *, store_id=None, student_id=None, status="", limit=100, offset=0, now=None):
    now = _now(now)
    expire_requests(now=now)
    if status and status not in STATUSES:
        raise EnrollmentError("Trạng thái đăng ký không hợp lệ.", field="status")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200 or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise EnrollmentError("Phân trang không hợp lệ.")
    with publication_transaction() as conn:
        actor = _admin(conn, actor)
        scope, params = _scope_sql(actor)
        where = " WHERE 1=1" + scope
        if store_id is not None:
            store = _positive_id(store_id)
            if not store:
                raise EnrollmentError("Cửa hàng không hợp lệ.", field="store_id")
            allowed = scoped_store_ids(actor)
            if allowed is not None and store not in allowed:
                raise EnrollmentError("Cửa hàng nằm ngoài phạm vi tài khoản.", "STORE_SCOPE_DENIED", 403)
            where += " AND r.store_id=?"
            params.append(store)
        if status:
            where += " AND r.status=?"
            params.append(status)
        if student_id is not None:
            sid = _positive_id(student_id)
            if not sid:
                raise EnrollmentError("Nhân viên không hợp lệ.", field="student_id")
            where += " AND r.student_id=?"
            params.append(sid)
        total = _one(conn, "SELECT COUNT(*) AS n FROM face_enrollment_requests r" + where, params)["n"]
        rows = _rows(conn, "SELECT r.* FROM face_enrollment_requests r" + where + " ORDER BY r.created_at DESC,r.id DESC LIMIT ? OFFSET ?", [*params, limit, offset])
        return {"items": [_dto(conn, row) for row in rows], "total": total, "limit": limit, "offset": offset}


def get_request(actor, request_id, *, now=None):
    now = _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        actor = _admin(conn, actor)
        return {"request": _dto(conn, _request(conn, request_id, actor))}


def get_preview(actor, request_id, *, now=None):
    now = _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        actor = _admin(conn, actor)
        row = _request(conn, request_id, actor)
        if row["status"] not in PENDING or not row["preview_blob"]:
            raise EnrollmentError("Ảnh xem trước không còn khả dụng.", "PREVIEW_UNAVAILABLE", 404)
        from .crypto import decrypt_bytes
        try:
            raw = decrypt_bytes(bytes(row["preview_blob"]))
            if len(raw) > 2 * 1024 * 1024 or not raw.startswith(b"\xff\xd8"):
                raise ValueError()
        except Exception:
            raise EnrollmentError("Ảnh xem trước không còn khả dụng.", "PREVIEW_UNAVAILABLE", 404) from None
        return raw


def approve_request(actor, request_id, *, expected_revision, reason="", duplicate_override=False, now=None):
    if not isinstance(duplicate_override, bool):
        raise EnrollmentError("Quyết định kiểm tra trùng không hợp lệ.", field="duplicate_override")
    reason = _reason(reason) if reason or duplicate_override else ""
    now = _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        actor = _admin(conn, actor)
        row = _request(conn, request_id, actor)
        _revision(row, expected_revision)
        if row["status"] not in PENDING:
            raise EnrollmentError("Bản đăng ký không còn chờ duyệt.", "REQUEST_NOT_PENDING", 409)
        _target(conn, row["student_id"], row["store_id"], actor, consent=True)
        draft = PreparedDraft(bytes(row["template_blob"] or b""), bytes(row["preview_blob"]) if row["preview_blob"] else None,
                              row["pose_count"], _decoded(row["quality_json"]), _decoded(row["pad_json"]))
        _summary(draft, now, submitting=False)
        duplicate = _duplicate(_callback("duplicate_checker")(draft.template_blob, row["student_id"], conn))
        if duplicate and not duplicate_override:
            # Persist refreshed duplicate evidence as a review transition; report
            # the conflict only after commit so the UI can retrieve current state.
            conn.execute("UPDATE face_enrollment_requests SET status='NEEDS_DUPLICATE_REVIEW',duplicate_json=?,revision=revision+1,updated_at=? WHERE id=?",
                         (_json(duplicate), _stamp(now), row["id"]))
            _audit(conn, row, "DUPLICATE_REVIEW_REQUIRED", now, actor["id"])
            conflict = True
        else:
            conflict = False
            stamp = _stamp(now)
            conn.execute("""INSERT INTO face_templates(student_id,embedding_blob,pose_count,created_at,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(student_id) DO UPDATE SET embedding_blob=excluded.embedding_blob,pose_count=excluded.pose_count,updated_at=excluded.updated_at""",
                         (row["student_id"], draft.template_blob, draft.pose_count, stamp, stamp))
            conn.execute("""INSERT INTO face_enrollment_validations(student_id,status,camera_source,score,margin,validated_at,validated_by,note,created_at,updated_at)
                VALUES(?,'PENDING_STORE_VALIDATION','',0,0,NULL,'',?,?,?)
                ON CONFLICT(student_id) DO UPDATE SET status='PENDING_STORE_VALIDATION',camera_source='',score=0,margin=0,validated_at=NULL,validated_by='',note=excluded.note,updated_at=excluded.updated_at""",
                         (row["student_id"], "APPROVED_REQUEST:" + row["id"], stamp, stamp))
            conn.execute("UPDATE face_enrollment_requests SET status='APPROVED',template_blob=NULL,preview_blob=NULL,duplicate_json=?,duplicate_override=?,review_reason=?,reviewed_by_user_id=?,reviewed_at=?,revision=revision+1,updated_at=? WHERE id=?",
                         (_json(duplicate), int(duplicate_override), reason, actor["id"], stamp, stamp, row["id"]))
            conn.execute("UPDATE qr_enrollment_invites SET revoked_at=COALESCE(revoked_at,?),session_hash=NULL WHERE request_id=?", (stamp, row["id"]))
            _audit(conn, row, "APPROVED", now, actor["id"], reason)
        result = {"request": _dto(conn, _request(conn, row["id"]))}
    if conflict:
        raise EnrollmentError("Phát hiện FaceID có thể trùng. Cần quyết định ghi đè kèm lý do hoặc quét lại.", "DUPLICATE_REVIEW_REQUIRED", 409)
    retire_requests([row["id"]])
    try:
        _callback("refresh_active_index")()
    except Exception:
        result["index_refresh_pending"] = True
    if draft.preview_blob:
        try:
            # Publication has committed, but consent/deletion/replacement may
            # have happened during index refresh. Revalidate this generation and
            # save via the same connection while holding the publication guard.
            with publication_transaction() as conn:
                current = _one(conn, "SELECT s.biometric_consent_status,f.embedding_blob FROM students s JOIN face_templates f ON f.student_id=s.id WHERE s.id=?", (row["student_id"],))
                if current and current["biometric_consent_status"] == "GRANTED" and hmac.compare_digest(bytes(current["embedding_blob"]), draft.template_blob):
                    result["portrait_saved"] = bool(_callback("save_approved_preview")(row["student_id"], draft.preview_blob, conn=conn))
                else:
                    result["portrait_saved"] = False
        except Exception:
            result["portrait_saved"] = False
    return result


def _decision(actor, request_id, status, expected_revision, reason, now):
    reason, now = _reason(reason), _now(now)
    expire_requests(now=now)
    with publication_transaction() as conn:
        actor = _admin(conn, actor)
        row = _request(conn, request_id, actor)
        _revision(row, expected_revision)
        permitted = PENDING if status == "REJECTED" else ACTIVE
        if row["status"] not in permitted:
            raise EnrollmentError("Yêu cầu đã kết thúc hoặc không còn chờ duyệt.", "REQUEST_NOT_PENDING", 409)
        _terminal(conn, row, status, reason, now, actor["id"])
        result = {"request": _dto(conn, _request(conn, row["id"]))}
    retire_requests([row["id"]])
    return result


def reject_request(actor, request_id, *, expected_revision, reason, now=None):
    return _decision(actor, request_id, "REJECTED", expected_revision, reason, now)


def cancel_request(actor, request_id, *, expected_revision, reason, now=None):
    return _decision(actor, request_id, "CANCELLED", expected_revision, reason, now)


def request_reenrollment(actor, request_id, *, expected_revision, reason, invitation_minutes=15, now=None):
    reason, now, minutes = _reason(reason), _now(now), _minutes(invitation_minutes)
    expire_requests(now=now)
    with publication_transaction() as conn:
        actor = _admin(conn, actor)
        row = _request(conn, request_id, actor)
        _revision(row, expected_revision)
        if row["status"] not in PENDING:
            raise EnrollmentError("Bản đăng ký không còn chờ duyệt.", "REQUEST_NOT_PENDING", 409)
        _target(conn, row["student_id"], row["store_id"], actor)
        _terminal(conn, row, "REJECTED", reason, now, actor["id"])
        _audit(conn, row, "REQUEST_REENROLLMENT", now, actor["id"], reason)
        result, retired = _create(conn, actor, row["student_id"], row["store_id"], "QR_MOBILE", now, minutes)
        result["previous_request"] = _dto(conn, _request(conn, row["id"]))
    retire_requests([row["id"], *retired])
    return result


def cancel_employee_requests(student_id, *, reason="CONSENT_WITHDRAWN", actor=None, conn=None, now=None):
    """Synchronize with existing withdrawal, without changing its policy.

    With an external publication_transaction connection, return retired IDs and
    call retire_requests only after that outer transaction commits.
    """
    sid, reason, now = _positive_id(student_id), _reason(reason), _now(now)
    if not sid:
        raise EnrollmentError("Nhân viên không hợp lệ.")
    if conn is None:
        with publication_transaction() as own:
            retired = cancel_employee_requests(sid, reason=reason, actor=actor, conn=own, now=now)
        retire_requests(retired)
        return retired
    if conn.mode == "postgres":
        exists = _one(conn, "SELECT to_regclass('face_enrollment_requests') AS name")
        if not exists or not exists["name"]:
            return []
    elif not _one(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='face_enrollment_requests'"):
        return []
    retired = []
    for row in _rows(conn, "SELECT * FROM face_enrollment_requests WHERE student_id=? AND status IN ('CAPTURING','PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW')", (sid,)):
        _terminal(conn, row, "CANCELLED", reason, now, (actor or {}).get("id"))
        retired.append(row["id"])
    return retired
