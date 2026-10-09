"""Authenticated account profile/password operations using existing auth policy.

No new tables, public registration or factor enrollment. Contacts/store remain
administrator-managed profile data. Password changes reuse the existing hash,
current-password throttling, five-minute factor proof, and global revocation.
"""
from __future__ import annotations

import sqlite3
import threading

from . import auth, db
from . import sms_auth_v542 as sms
from .demo_context import _positive_id

_MUTATION_LOCK = threading.RLock()


class AccountError(ValueError):
    def __init__(self, message, code="INVALID_ACCOUNT_INPUT", status=400, field=""):
        self.code, self.status, self.field = code, status, field
        super().__init__(message)


def _user(token):
    user = auth.user_for_token(str(token or ""))
    if not user:
        raise AccountError("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.", "SESSION_EXPIRED", 401)
    row = db.fetchone("SELECT * FROM system_users WHERE id=?", (user["id"],))
    if not row or not row.get("active"):
        raise AccountError("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.", "SESSION_EXPIRED", 401)
    return row


def _factor_guard(row, token):
    enabled = bool(sms.factor(row["id"]) or auth._mfa_record(row["id"]).get("enabled"))
    if enabled and not auth.factor_is_fresh(token):
        raise AccountError("Hãy xác minh lại trong Bảo mật tài khoản rồi thực hiện thao tác này.", "STEP_UP_REQUIRED", 403)


def _name(value):
    name = str(value or "").strip()
    if not name or len(name) > 120 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise AccountError("Tên hiển thị cần có từ 1 đến 120 ký tự.", field="display_name")
    return name


def _password(password, confirmation, *, optional_confirmation=False):
    if not isinstance(password, str) or len(password) > 256:
        raise AccountError("Mật khẩu không hợp lệ.", field="new_password")
    if confirmation is not None or not optional_confirmation:
        if not isinstance(confirmation, str) or password != confirmation:
            raise AccountError("Mật khẩu xác nhận chưa khớp.", "PASSWORD_CONFIRMATION_MISMATCH", field="confirm_password")
    try:
        auth._validate_password_strength(password, 12)
    except ValueError as exc:
        raise AccountError(str(exc), "WEAK_PASSWORD", field="new_password") from None


def get_self_profile(token):
    row = _user(token)
    user = auth._public_user(row)
    store = db.fetchone("SELECT store_name FROM stores WHERE id=?", (user["store_id"],)) if user.get("store_id") else None
    user["store_name"] = str((store or {}).get("store_name") or "")
    return {"user": user, "editable_fields": ["display_name"],
            "security": {"enabled": user["mfa_enabled"], "method": user["mfa_method"],
                         "fresh_verification": auth.factor_is_fresh(token)},
            "password_policy": {"minimum_length": 12, "uppercase": True, "lowercase": True, "digit": True, "special": True}}


def update_self_profile(token, *, display_name):
    name = _name(display_name)
    with _MUTATION_LOCK:
        row = _user(token)
        db.execute("UPDATE system_users SET display_name=?,updated_at=? WHERE id=?", (name, db.utc_now(), row["id"]))
        # Display-name changes do not affect credentials. Refresh only the cached
        # public name; never extend expiry or factor freshness of any session.
        with auth._lock:
            for session, (expiry, public) in list(auth._sessions.items()):
                if public.get("id") == row["id"]:
                    auth._sessions[session] = (expiry, {**public, "display_name": name})
        return get_self_profile(token)


def change_self_password(token, *, current_password, new_password, confirm_password):
    _password(new_password, confirm_password)
    if not isinstance(current_password, str) or not 1 <= len(current_password) <= 256:
        raise AccountError("Nhập mật khẩu hiện tại.", field="current_password")
    with _MUTATION_LOCK:
        row = _user(token)
        _factor_guard(row, token)
        try:
            confirmed = auth._authenticate_password(row["username"], current_password)
        except ValueError as exc:
            lock = auth.login_lock_status(row["username"])
            raise AccountError(str(exc), "PASSWORD_RATE_LIMITED" if lock.get("locked") else "CURRENT_PASSWORD_INVALID",
                               429 if lock.get("locked") else 400, "current_password") from None
        if confirmed["id"] != row["id"]:
            raise AccountError("Phiên đăng nhập đã thay đổi. Hãy đăng nhập lại.", "SESSION_EXPIRED", 401)
        try:
            auth.reset_user_password(row["id"], new_password,
                                     expected_credentials=(confirmed["password_salt"], confirmed["password_hash"]))
        except ValueError as exc:
            raise AccountError(str(exc), "CREDENTIALS_CHANGED", 409) from None
    return {"ok": True, "relogin_required": True}


def provision_account(actor, token, *, username, display_name, role, password, confirm_password=None,
                      phone="", email="", store_id=None):
    """Owner/Admin only; user + optional existing profile persist atomically."""
    row = _user(token)
    if _positive_id((actor or {}).get("id")) != row["id"] or str(row["role"]).upper() not in {"SUPER_ADMIN", "ADMIN"}:
        raise AccountError("Chỉ Chủ sở hữu hoặc Quản trị viên được tạo tài khoản.", "ACCOUNT_PROVISION_DENIED", 403)
    _factor_guard(row, token)
    _password(password, confirm_password, optional_confirmation=True)
    username = str(username or "").strip().lower()
    if not 3 <= len(username) <= 80 or any(ord(char) < 32 or ord(char) == 127 for char in username):
        raise AccountError("Tên đăng nhập cần có từ 3 đến 80 ký tự.", field="username")
    display_name = _name(display_name or username)
    try:
        role = auth._validate_role(role)
    except ValueError as exc:
        raise AccountError(str(exc), field="role") from None
    if role == "SUPER_ADMIN" and str(row["role"]).upper() != "SUPER_ADMIN":
        raise AccountError("Chỉ Chủ sở hữu được tạo tài khoản Chủ sở hữu.", "ACCOUNT_PROVISION_DENIED", 403, "role")
    has_profile = bool(str(phone or "").strip() or str(email or "").strip() or store_id is not None)
    if has_profile and not str(phone or "").strip():
        raise AccountError("Cần số điện thoại để lưu email hoặc cửa hàng cho tài khoản.", "PROFILE_PHONE_REQUIRED", field="phone")
    try:
        phone = auth._normalize_phone(phone) if has_profile else ""
        email = auth._normalize_email(email) if str(email or "").strip() else ""
    except ValueError as exc:
        raise AccountError(str(exc), field="email" if "Email" in str(exc) else "phone") from None
    if store_id is not None:
        parsed_store = _positive_id(store_id)
        if parsed_store is None:
            raise AccountError("Chọn cửa hàng hợp lệ.", field="store_id")
        store_id = parsed_store
    salt, digest = auth._new_password(password, 12)
    now = db.utc_now()
    try:
        with _MUTATION_LOCK, db.connection() as conn:
            if conn.mode == "postgres":
                conn.execute("SELECT pg_advisory_xact_lock(54100075)")
            if conn.execute("SELECT id FROM system_users WHERE username=?", (username,)).fetchone():
                raise AccountError("Tên đăng nhập đã tồn tại.", "ACCOUNT_ALREADY_EXISTS", 409, "username")
            if has_profile and conn.execute("SELECT user_id FROM account_profiles WHERE phone=?", (phone,)).fetchone():
                raise AccountError("Số điện thoại đã được đăng ký.", "ACCOUNT_ALREADY_EXISTS", 409, "phone")
            if email and conn.execute("SELECT user_id FROM account_profiles WHERE LOWER(email)=?", (email,)).fetchone():
                raise AccountError("Email đã được đăng ký.", "ACCOUNT_ALREADY_EXISTS", 409, "email")
            if store_id is not None and not conn.execute("SELECT id FROM stores WHERE id=?", (store_id,)).fetchone():
                raise AccountError("Không tìm thấy cửa hàng đã chọn.", field="store_id")
            values = (username, display_name, role, salt, digest, 1, now, now)
            cursor = conn.execute("INSERT INTO system_users(username,display_name,role,password_salt,password_hash,active,created_at,updated_at) "
                                  "VALUES(?,?,?,?,?,?,?,?)" + (" RETURNING id" if conn.mode == "postgres" else ""), values)
            uid = int(dict(cursor.fetchone())["id"]) if conn.mode == "postgres" else int(cursor.lastrowid)
            if has_profile:
                conn.execute("INSERT INTO account_profiles(user_id,phone,email,account_status,phone_verified,email_verified,store_id,created_at,updated_at) "
                             "VALUES(?,?,?,'ACTIVE',0,0,?,?,?)", (uid, phone, email, store_id, now, now))
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505" or (isinstance(exc, sqlite3.IntegrityError) and "UNIQUE constraint" in str(exc)):
            raise AccountError("Thông tin tài khoản đã được đăng ký.", "ACCOUNT_ALREADY_EXISTS", 409) from None
        raise
    return auth._public_user({"id": uid, "username": username, "display_name": display_name, "role": role, "active": 1})
