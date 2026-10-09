from __future__ import annotations

import os

import base64
import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import quote

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError
    _ARGON2 = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
except Exception:  # fallback keeps old installations usable if argon2-cffi is unavailable
    PasswordHasher = None
    VerifyMismatchError = VerificationError = Exception
    _ARGON2 = None

from .db import connection, execute, fetchall, fetchone, utc_now
from .crypto import encrypt_bytes, decrypt_bytes

_ITERATIONS = 210_000
_SESSION_TTL = 8 * 60 * 60
_MOBILE_SESSION_TTL = 24 * 60 * 60
_lock = threading.RLock()
_sessions: dict[str, tuple[float, dict]] = {}
_mobile_sessions: dict[str, tuple[float, dict]] = {}
_failed_logins: dict[str, tuple[int, float]] = {}
_mobile_failed: dict[str, tuple[int, float]] = {}
_LOGIN_MAX_FAILURES = 5
_LOGIN_LOCK_SEC = 60

# V5.4.2: a second factor is required only after verified enrollment.
# Existing enabled TOTP is preserved until the owner securely migrates to SMS.
# TOTP is deliberately implemented with the Python standard library so the
# offline Windows bundle does not depend on a cloud MFA SDK.
_MFA_REQUIRED_ROLES = {"SUPER_ADMIN", "ADMIN"}
_MFA_CHALLENGE_TTL = 5 * 60
_MFA_ISSUER = "Bảo Tín Mạnh Hải"
_mfa_challenges: dict[str, dict] = {}
_session_factor_times: dict[str, float] = {}
_session_credential_tags: dict[str, str] = {}

# V5.3.3: ADMIN/SUPER_ADMIN use verified SMS/Email OTP as the normal
# second factor. The first successful password login is allowed before any
# destination exists, so the owner can complete contact verification inside
# the authenticated Settings area. Once one destination is verified, every
# later login requires an OTP before a browser session is issued.
_PRIVILEGED_LOGIN_CHALLENGE_TTL = 5 * 60
_privileged_login_challenges: dict[str, dict] = {}

# BTMH V3: roles are business roles. Existing route declarations still use the
# legacy ADMIN/OPERATOR/VIEWER access levels; ROLE_ROUTE_GRANTS maps business
# roles to those levels while new APIs can enforce granular permissions.
ROLE_DEFINITIONS: dict[str, dict] = {
    "SUPER_ADMIN": {"label": "Chủ sở hữu", "description": "Toàn quyền quản lý hệ thống, tài khoản, bảo mật và cấu hình cấp cao."},
    "ADMIN": {"label": "Quản trị viên", "description": "Quản lý tài khoản, vận hành và cấu hình trong phạm vi được giao."},
    "MANAGER": {"label": "Quản lý cửa hàng", "description": "Theo dõi vận hành, nhân sự, camera, chấm công và sự cố tại chi nhánh."},
    "HR": {"label": "Nhân sự", "description": "Quản lý hồ sơ nhân viên, FaceID, ca làm, chấm công và báo cáo HR."},
    "SECURITY": {"label": "Giám sát / Bảo vệ", "description": "Giám sát camera, nhận diện, xem lại và xử lý sự cố an ninh."},
    "TECHNICIAN": {"label": "Kỹ thuật", "description": "Quản lý sức khỏe hệ thống, camera, storage và chẩn đoán kỹ thuật."},
    "EMPLOYEE": {"label": "Nhân viên", "description": "Xem hồ sơ và lịch sử chấm công cá nhân theo quyền được cấp."},
    "VIEWER": {"label": "Chỉ xem (legacy)", "description": "Vai trò tương thích dữ liệu cũ, chỉ xem phạm vi được cấp."},
    "OPERATOR": {"label": "Vận hành (legacy)", "description": "Vai trò tương thích dữ liệu CampusFace cũ."},
}

DEFAULT_PERMISSIONS: dict[str, set[str]] = {
    "SUPER_ADMIN": {"*"},
    "ADMIN": {"*"},
    "MANAGER": {
        "dashboard.view", "employee.view", "employee.manage", "employee.enroll",
        "attendance.view", "attendance.manage", "attendance.adjust", "hr.report",
        "camera.live", "camera.playback", "camera.switch", "video.clip",
        "visitor.view", "visitor.review", "incident.view", "incident.manage", "evidence.export",
        "audit.view",
    },
    "HR": {
        "dashboard.view", "employee.view", "employee.manage", "employee.enroll",
        "attendance.view", "attendance.manage", "attendance.adjust", "hr.report", "audit.view",
    },
    "SECURITY": {
        "dashboard.view", "employee.view", "camera.live", "camera.playback", "camera.switch", "video.clip",
        "visitor.view", "visitor.review", "incident.view", "incident.manage", "evidence.export",
    },
    "TECHNICIAN": {
        "dashboard.view", "camera.live", "camera.switch", "camera.configure", "system.health", "audit.view",
    },
    "EMPLOYEE": {"attendance.view.self"},
    "VIEWER": {"dashboard.view", "employee.view", "attendance.view", "camera.live", "visitor.view"},
    "OPERATOR": {
        "dashboard.view", "employee.view", "employee.manage", "employee.enroll", "attendance.view",
        "attendance.manage", "camera.live", "camera.switch", "visitor.view", "visitor.review", "incident.view",
    },
}


ROLE_ROUTE_GRANTS: dict[str, set[str]] = {
    "SUPER_ADMIN": {"ADMIN", "OPERATOR", "VIEWER"},
    "ADMIN": {"ADMIN", "OPERATOR", "VIEWER"},
    "MANAGER": {"OPERATOR", "VIEWER"},
    "HR": {"OPERATOR", "VIEWER"},
    "SECURITY": {"OPERATOR", "VIEWER"},
    "TECHNICIAN": {"OPERATOR", "VIEWER"},
    "OPERATOR": {"OPERATOR", "VIEWER"},
    "EMPLOYEE": {"VIEWER"},
    "VIEWER": {"VIEWER"},
}


def _hash_password(password: str, salt: bytes) -> str:
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return base64.b64encode(raw).decode("ascii")


def _validate_password_strength(password: str, min_length: int = 12) -> None:
    raw = str(password or "")
    if len(raw) < int(min_length):
        raise ValueError(f"Mật khẩu phải có ít nhất {int(min_length)} ký tự")
    if not any(ch.isupper() for ch in raw):
        raise ValueError("Mật khẩu phải có ít nhất một chữ hoa")
    if not any(ch.islower() for ch in raw):
        raise ValueError("Mật khẩu phải có ít nhất một chữ thường")
    if not any(ch.isdigit() for ch in raw):
        raise ValueError("Mật khẩu phải có ít nhất một chữ số")
    if not any(not ch.isalnum() for ch in raw):
        raise ValueError("Mật khẩu phải có ít nhất một ký tự đặc biệt")


def _new_password(password: str, min_length: int = 8) -> tuple[str, str]:
    raw = str(password or "")
    if len(raw) < int(min_length):
        raise ValueError(f"Mật khẩu phải có ít nhất {int(min_length)} ký tự")
    # V5 uses Argon2id for newly created/changed passwords. Existing PBKDF2
    # hashes remain valid and are transparently upgraded after a successful login.
    if _ARGON2 is not None:
        return "ARGON2ID", _ARGON2.hash(raw)
    salt = secrets.token_bytes(18)
    return base64.b64encode(salt).decode("ascii"), _hash_password(raw, salt)


def _verify_password(password: str, salt_marker: str, stored_hash: str) -> tuple[bool, bool]:
    marker = str(salt_marker or "")
    expected = str(stored_hash or "")
    if marker == "ARGON2ID" and _ARGON2 is not None:
        try:
            ok = bool(_ARGON2.verify(expected, str(password or "")))
            return ok, bool(ok and _ARGON2.check_needs_rehash(expected))
        except (VerifyMismatchError, VerificationError, Exception):
            return False, False
    try:
        salt = base64.b64decode(marker)
    except Exception:
        salt = b""
    digest = _hash_password(str(password or ""), salt) if salt else ""
    ok = bool(digest and hmac.compare_digest(digest, expected))
    # Successful legacy verification should be upgraded to Argon2id.
    return ok, bool(ok and _ARGON2 is not None)


def _setting_get(key: str, default: str = "") -> str:
    row = fetchone("SELECT setting_value FROM runtime_settings WHERE setting_key=?", (str(key),))
    return str((row or {}).get("setting_value") or default)


def _setting_set(key: str, value: str) -> None:
    now = utc_now()
    if fetchone("SELECT setting_key FROM runtime_settings WHERE setting_key=?", (str(key),)):
        execute("UPDATE runtime_settings SET setting_value=?,updated_at=? WHERE setting_key=?", (str(value), now, str(key)))
    else:
        execute("INSERT INTO runtime_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)", (str(key), str(value), now))


def ensure_rbac_schema() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS role_permissions (
        role TEXT NOT NULL,
        permission TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(role, permission)
    );
    CREATE TABLE IF NOT EXISTS account_profiles (
        user_id INTEGER PRIMARY KEY,
        phone TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS account_mfa (
        user_id INTEGER PRIMARY KEY,
        method TEXT NOT NULL DEFAULT 'TOTP',
        secret_enc TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 0,
        last_used_step BIGINT NOT NULL DEFAULT -1,
        enrolled_at TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES system_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS account_mfa_recovery_codes (
        user_id INTEGER NOT NULL,
        code_hash TEXT NOT NULL,
        used_at TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY(user_id, code_hash),
        FOREIGN KEY(user_id) REFERENCES system_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS privileged_security_profiles (
        user_id INTEGER PRIMARY KEY,
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        phone_verified INTEGER NOT NULL DEFAULT 0,
        email_verified INTEGER NOT NULL DEFAULT 0,
        setup_completed INTEGER NOT NULL DEFAULT 0,
        default_method TEXT NOT NULL DEFAULT '',
        completed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES system_users(id) ON DELETE CASCADE
    );
    """
    with connection() as conn:
        conn.executescript(schema)
    # V5 account metadata. Keep upgrades idempotent without intentionally
    # issuing failing ALTER TABLE statements. PostgreSQL logs every failed DDL
    # even when Python catches the exception, which made healthy upgrades look
    # broken ("column ... already exists") in customer logs.
    profile_columns = (
        ("email", "TEXT"),
        ("account_status", "TEXT NOT NULL DEFAULT 'ACTIVE'"),
        ("phone_verified", "INTEGER NOT NULL DEFAULT 0"),
        ("email_verified", "INTEGER NOT NULL DEFAULT 0"),
        ("store_id", "INTEGER"),
    )
    with connection() as conn:
        if conn.mode == "postgres":
            existing_columns = {
                str(row[0] if not isinstance(row, dict) else row.get("column_name") or "").lower()
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=?",
                    ("account_profiles",),
                ).fetchall()
            }
        else:
            existing_columns = {
                str(row[1] if not hasattr(row, "keys") else row["name"]).lower()
                for row in conn.execute("PRAGMA table_info(account_profiles)").fetchall()
            }
        for column_name, column_type in profile_columns:
            if column_name.lower() in existing_columns:
                continue
            conn.execute(f"ALTER TABLE account_profiles ADD COLUMN {column_name} {column_type}")
            existing_columns.add(column_name.lower())
    # Seed only missing defaults. Custom permissions can be added later without
    # being overwritten on restart.
    now = utc_now()
    existing = {(str(r.get("role") or "").upper(), str(r.get("permission") or "")) for r in fetchall("SELECT role,permission FROM role_permissions")}
    for role, permissions in DEFAULT_PERMISSIONS.items():
        for permission in permissions:
            key = (role, permission)
            if key in existing:
                continue
            try:
                with connection() as conn:
                    conn.execute("INSERT INTO role_permissions(role,permission,created_at) VALUES(?,?,?)", (role, permission, now))
            except Exception:
                pass
    from .sms_auth_v542 import ensure_schema
    ensure_schema()


def enforce_admin_only() -> None:
    """Compatibility hook retained for startup.

    V2.4 disabled every non-admin account here. BTMH V3 intentionally does not:
    this hook now upgrades/seeds RBAC without mutating existing user activation.
    """
    ensure_rbac_schema()


def role_catalog() -> list[dict]:
    ensure_rbac_schema()
    out = []
    for role, meta in ROLE_DEFINITIONS.items():
        out.append({"role": role, **meta, "permissions": permissions_for_role(role)})
    return out


def permissions_for_role(role: str) -> list[str]:
    normalized = str(role or "VIEWER").strip().upper()
    try:
        rows = fetchall("SELECT permission FROM role_permissions WHERE UPPER(role)=? ORDER BY permission", (normalized,))
        if rows:
            return [str(r.get("permission") or "") for r in rows if r.get("permission")]
    except Exception:
        pass
    return sorted(DEFAULT_PERMISSIONS.get(normalized, set()))


def _mask_phone(value: str) -> str:
    raw = str(value or "").strip()
    return ("******" + raw[-4:]) if raw else ""


def _mask_email(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw or "@" not in raw:
        return ""
    local, domain = raw.split("@", 1)
    return (local[:1] + "***@" + domain) if local else ("***@" + domain)


def _privileged_security_row(user_id: int) -> dict:
    ensure_rbac_schema()
    return fetchone("SELECT * FROM privileged_security_profiles WHERE user_id=?", (int(user_id),)) or {}


def privileged_security_status(user_id: int, role: str = "") -> dict:
    role_name = str(role or "").strip().upper()
    if not role_name:
        user = fetchone("SELECT role FROM system_users WHERE id=?", (int(user_id),)) or {}
        role_name = str(user.get("role") or "").upper()
    required = role_name in _MFA_REQUIRED_ROLES
    row = _privileged_security_row(int(user_id)) if required else {}
    phone = str(row.get("phone") or "")
    email = str(row.get("email") or "")
    phone_verified = bool(row.get("phone_verified", 0) and phone)
    email_verified = bool(row.get("email_verified", 0) and email)
    completed = bool(row.get("setup_completed", 0) and (phone_verified or email_verified))
    methods = []
    if phone_verified:
        methods.append({"method": "SMS", "label": "Tin nhắn SMS", "hint": _mask_phone(phone)})
    if email_verified:
        methods.append({"method": "EMAIL", "label": "Email", "hint": _mask_email(email)})
    return {
        "required": required,
        "setup_completed": completed,
        "setup_required": bool(required and not completed),
        "phone": phone,
        "email": email,
        "phone_verified": phone_verified,
        "email_verified": email_verified,
        "phone_hint": _mask_phone(phone),
        "email_hint": _mask_email(email),
        "methods": methods,
        "default_method": str(row.get("default_method") or "").upper(),
        "completed_at": row.get("completed_at"),
    }


def verify_privileged_security_contact(user_id: int, *, method: str, destination: str, display_name: str = "") -> dict:
    ensure_rbac_schema()
    user = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),))
    if not user:
        raise ValueError("Không tìm thấy tài khoản")
    role = str(user.get("role") or "").upper()
    if role not in _MFA_REQUIRED_ROLES:
        raise ValueError("Chỉ tài khoản ADMIN/SUPER_ADMIN dùng hồ sơ bảo mật quản trị")
    mode = str(method or "").strip().upper()
    if mode == "SMS":
        normalized = _normalize_phone(destination)
        duplicate = fetchone("SELECT user_id FROM privileged_security_profiles WHERE phone=? AND user_id<>?", (normalized, int(user_id)))
        if duplicate:
            raise ValueError("Số điện thoại đã được dùng cho tài khoản quản trị khác")
    elif mode == "EMAIL":
        normalized = _normalize_email(destination)
        duplicate = fetchone("SELECT user_id FROM privileged_security_profiles WHERE LOWER(email)=? AND user_id<>?", (normalized, int(user_id)))
        if duplicate:
            raise ValueError("Email đã được dùng cho tài khoản quản trị khác")
    else:
        raise ValueError("Phương thức xác thực không hợp lệ")

    now = utc_now()
    current = _privileged_security_row(int(user_id))
    if current:
        if mode == "SMS":
            execute(
                "UPDATE privileged_security_profiles SET phone=?,phone_verified=1,setup_completed=1,default_method=?,completed_at=COALESCE(completed_at,?),updated_at=? WHERE user_id=?",
                (normalized, mode, now, now, int(user_id)),
            )
        else:
            execute(
                "UPDATE privileged_security_profiles SET email=?,email_verified=1,setup_completed=1,default_method=?,completed_at=COALESCE(completed_at,?),updated_at=? WHERE user_id=?",
                (normalized, mode, now, now, int(user_id)),
            )
    else:
        execute(
            """INSERT INTO privileged_security_profiles(user_id,phone,email,phone_verified,email_verified,setup_completed,default_method,completed_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (int(user_id), normalized if mode == "SMS" else "", normalized if mode == "EMAIL" else "", 1 if mode == "SMS" else 0, 1 if mode == "EMAIL" else 0, 1, mode, now, now, now),
        )
    if str(display_name or "").strip():
        execute("UPDATE system_users SET display_name=?,updated_at=? WHERE id=?", (str(display_name).strip(), now, int(user_id)))
    # Refresh any already-issued first-login session so /auth/status immediately
    # reflects that the ADMIN security setup is complete.
    fresh_row = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),)) or user
    fresh_public = _public_user(fresh_row)
    with _lock:
        for token, (expires_at, session_user) in list(_sessions.items()):
            if int(session_user.get("id") or -1) == int(user_id):
                _sessions[token] = (expires_at, fresh_public)
    return privileged_security_status(int(user_id), role)


def privileged_login_otp_destination(challenge_id: str, method: str) -> dict:
    _cleanup_privileged_login_challenges()
    cid = str(challenge_id or "").strip()
    mode = str(method or "").strip().upper()
    with _lock:
        challenge = dict(_privileged_login_challenges.get(cid) or {})
    if not challenge:
        raise ValueError("Phiên đăng nhập đã hết hạn. Hãy nhập lại mật khẩu")
    user_id = int(challenge.get("user_id") or 0)
    user = fetchone("SELECT * FROM system_users WHERE id=?", (user_id,))
    if not user or not bool(user.get("active", 1)):
        raise ValueError("Tài khoản không còn hoạt động")
    security = privileged_security_status(user_id, str(user.get("role") or ""))
    allowed = {str(item.get("method") or "").upper() for item in security.get("methods") or []}
    if mode not in allowed:
        raise ValueError("Phương thức xác thực chưa được tài khoản này xác minh")
    destination = security.get("phone") if mode == "SMS" else security.get("email")
    return {"user_id": user_id, "method": mode, "destination": str(destination or ""), "user": _public_user(user)}


def complete_privileged_login_challenge(challenge_id: str, user_id: int) -> dict:
    _cleanup_privileged_login_challenges()
    cid = str(challenge_id or "").strip()
    with _lock:
        challenge = dict(_privileged_login_challenges.get(cid) or {})
    if not challenge or int(challenge.get("user_id") or 0) != int(user_id):
        raise ValueError("Phiên xác thực đăng nhập không hợp lệ hoặc đã hết hạn")
    row = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),))
    if not row or not bool(row.get("active", 1)):
        raise ValueError("Tài khoản không còn hoạt động")
    with _lock:
        _privileged_login_challenges.pop(cid, None)
    out = _issue_session(row)
    out["second_factor_verified"] = True
    return out


def _cleanup_privileged_login_challenges() -> None:
    now = time.time()
    with _lock:
        for challenge_id, item in list(_privileged_login_challenges.items()):
            if float(item.get("expires_at") or 0) <= now:
                _privileged_login_challenges.pop(challenge_id, None)


def _new_privileged_login_challenge(row: dict) -> dict:
    _cleanup_privileged_login_challenges()
    user_id = int(row.get("id") or 0)
    security = privileged_security_status(user_id, str(row.get("role") or ""))
    if not security.get("setup_completed") or not security.get("methods"):
        out = _issue_session(row)
        out["security_setup_required"] = True
        return out
    challenge_id = secrets.token_urlsafe(28)
    with _lock:
        _privileged_login_challenges[challenge_id] = {
            "user_id": user_id,
            "expires_at": time.time() + _PRIVILEGED_LOGIN_CHALLENGE_TTL,
        }
    return {
        "second_factor_required": True,
        "challenge_id": challenge_id,
        "expires_in": _PRIVILEGED_LOGIN_CHALLENGE_TTL,
        "methods": security.get("methods") or [],
        "default_method": security.get("default_method") or "",
        "user": _public_user(row),
    }


def _public_user(row: dict) -> dict:
    role = str(row.get("role") or "EMPLOYEE").upper()
    profile = {}
    mfa = {}
    try:
        if row.get("id"):
            profile = fetchone(
                "SELECT phone,email,account_status,phone_verified,email_verified,store_id FROM account_profiles WHERE user_id=?",
                (int(row.get("id")),),
            ) or {}
            mfa = fetchone(
                "SELECT enabled,enrolled_at,method FROM account_mfa WHERE user_id=?",
                (int(row.get("id")),),
            ) or {}
    except Exception:
        profile = {}
        mfa = {}
    from .sms_auth_v542 import factor
    sms = factor(int(row.get("id") or 0))
    privileged = role in _MFA_REQUIRED_ROLES
    mfa_enabled = bool(sms or mfa.get("enabled", 0))
    recovery_remaining = 0
    if mfa_enabled and row.get("id"):
        try:
            recovery_remaining = int((fetchone(
                "SELECT COUNT(*) AS n FROM account_mfa_recovery_codes WHERE user_id=? AND used_at IS NULL",
                (int(row.get("id")),),
            ) or {}).get("n") or 0)
        except Exception:
            recovery_remaining = 0
    return {
        "id": int(row.get("id") or 0),
        "username": str(row.get("username") or ""),
        "display_name": str(row.get("display_name") or row.get("username") or ""),
        "role": role,
        "role_label": str(ROLE_DEFINITIONS.get(role, {}).get("label") or role),
        "permissions": permissions_for_role(role),
        "active": bool(row.get("active", 1)),
        "phone": str(profile.get("phone") or ""),
        "email": str(profile.get("email") or ""),
        "account_status": str(profile.get("account_status") or ("ACTIVE" if bool(row.get("active",1)) else "PENDING")),
        "phone_verified": bool(profile.get("phone_verified", 0)),
        "email_verified": bool(profile.get("email_verified", 0)),
        "store_id": profile.get("store_id"),
        "mfa_required": mfa_enabled,
        "mfa_enabled": mfa_enabled,
        "mfa_method": "SMS" if sms else str(mfa.get("method") or ("TOTP" if mfa_enabled else "")),
        "mfa_enrolled_at": mfa.get("enrolled_at"),
        "mfa_recovery_codes_remaining": recovery_remaining,
        "security_setup_required": False,
        "security_2fa_methods": ([{"method": "SMS" if sms else "TOTP", "label": "SMS" if sms else "Authenticator"}] if mfa_enabled else []),
    }


def user_count() -> int:
    # Disabling an administrator is not a factory reset. A configured database
    # must never reopen public bootstrap or the legacy setup-only role grant.
    row = fetchone("SELECT COUNT(*) n FROM system_users WHERE UPPER(role) IN ('ADMIN','SUPER_ADMIN')") or {"n": 0}
    return int(row["n"])


def bootstrap_admin(username: str, display_name: str, password: str, phone: str = "", email: str = "", *, phone_verified: bool = True) -> dict:
    ensure_rbac_schema()
    username = str(username).strip().lower()
    if len(username) < 3:
        raise ValueError("Tên đăng nhập quá ngắn")
    _validate_password_strength(password, 12)
    salt, digest = _new_password(password, 12)
    now = utc_now()
    # Serialize the existence check and insert in the database, including
    # concurrent requests/processes with different usernames. No schema change.
    with connection() as conn:
        if conn.mode == "postgres":
            conn.execute("LOCK TABLE system_users IN SHARE ROW EXCLUSIVE MODE")
        else:
            conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT COUNT(*) n FROM system_users WHERE UPPER(role) IN ('ADMIN','SUPER_ADMIN')").fetchone()
        if int(existing["n"] if hasattr(existing, "keys") else existing[0]) > 0:
            raise ValueError("Hệ thống đã có tài khoản quản trị gốc")
        sql = """INSERT INTO system_users(username,display_name,role,password_salt,password_hash,active,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)"""
        if conn.mode == "postgres":
            sql += " RETURNING id"
        cursor = conn.execute(sql, (username, str(display_name or username).strip(), "SUPER_ADMIN", salt, digest, 1, now, now))
        if conn.mode == "postgres":
            inserted = cursor.fetchone()
            uid = int(inserted["id"] if hasattr(inserted, "keys") else inserted[0])
        else:
            uid = int(cursor.lastrowid)
    if str(phone or "").strip():
        _save_user_profile(int(uid), phone=phone, email=email, status="ACTIVE", phone_verified=phone_verified, email_verified=False)
    return _public_user({"id": uid, "username": username, "display_name": display_name or username, "role": "SUPER_ADMIN", "active": 1})



# One-time owner credential bundled for the customer's Central installation.
# The plaintext password is intentionally NOT stored in source; only this
# Argon2id verifier is packaged. After first successful startup the provision
# marker prevents later restarts from resetting a password the owner changed.
_RELEASE_OWNER_PROVISION_KEY = "release.5.3.1.initial_owner.OWNER_SETUP_REQUIRED"
_RELEASE_OWNER_USERNAME = ""  # supplied only by explicit first-run setup
_RELEASE_OWNER_PASSWORD_HASH = ""  # generated at first run, never committed


def provision_release_owner_account() -> dict:
    """Provision the designated BTMH owner account exactly once per DATA_ROOT.

    This migration is intentionally idempotent. On the first startup of this
    release it creates (or repairs) the named owner as an active SUPER_ADMIN,
    resets any stale MFA enrollment for that one account, and records a runtime
    marker. Future restarts do not touch its role, password or MFA state again.
    """
    # V5.4: never provision an owner automatically or from a packaged secret.
    if os.getenv("BTMH_ALLOW_FIRST_RUN_OWNER", "0") != "1":
        return False
    if not _RELEASE_OWNER_USERNAME or not _RELEASE_OWNER_PASSWORD_HASH:
        return False
    ensure_rbac_schema()
    if _setting_get(_RELEASE_OWNER_PROVISION_KEY, "") == "1":
        row = fetchone("SELECT * FROM system_users WHERE username=?", (_RELEASE_OWNER_USERNAME,))
        return {"provisioned": False, "user": _public_user(row) if row else None}

    now = utc_now()
    row = fetchone("SELECT * FROM system_users WHERE username=?", (_RELEASE_OWNER_USERNAME,))
    if row:
        user_id = int(row.get("id") or 0)
        execute(
            """UPDATE system_users SET role=?,password_salt=?,password_hash=?,active=1,updated_at=? WHERE id=?""",
            ("SUPER_ADMIN", "ARGON2ID", _RELEASE_OWNER_PASSWORD_HASH, now, user_id),
        )
    else:
        user_id = execute(
            """INSERT INTO system_users(username,display_name,role,password_salt,password_hash,active,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (_RELEASE_OWNER_USERNAME, "BTMH Owner Admin", "SUPER_ADMIN", "ARGON2ID", _RELEASE_OWNER_PASSWORD_HASH, 1, now, now),
        )

    # A legacy profile can otherwise block login when its phone was never
    # verified. The designated local owner is considered pre-provisioned.
    profile = fetchone("SELECT user_id FROM account_profiles WHERE user_id=?", (int(user_id),))
    if profile:
        execute(
            "UPDATE account_profiles SET account_status='ACTIVE',updated_at=? WHERE user_id=?",
            (now, int(user_id)),
        )

    # Force a fresh Authenticator enrollment for this newly provisioned release
    # credential. This avoids inheriting an unknown MFA secret from an older DB.
    with connection() as conn:
        conn.execute("DELETE FROM account_mfa_recovery_codes WHERE user_id=?", (int(user_id),))
        conn.execute("DELETE FROM account_mfa WHERE user_id=?", (int(user_id),))
    with _lock:
        for token, (_, user) in list(_sessions.items()):
            if int(user.get("id") or -1) == int(user_id):
                _sessions.pop(token, None)
        for cid, item in list(_mfa_challenges.items()):
            if int(item.get("user_id") or -1) == int(user_id):
                _mfa_challenges.pop(cid, None)

    _setting_set(_RELEASE_OWNER_PROVISION_KEY, "1")
    fresh = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),))
    return {"provisioned": True, "user": _public_user(fresh or {"id": user_id, "username": _RELEASE_OWNER_USERNAME, "role": "SUPER_ADMIN", "active": 1})}

def _validate_role(role: str) -> str:
    normalized = str(role or "VIEWER").strip().upper()
    if normalized not in ROLE_DEFINITIONS:
        raise ValueError("Vai trò không hợp lệ")
    return normalized


def create_user(username: str, display_name: str, role: str, password: str) -> dict:
    ensure_rbac_schema()
    username = str(username or "").strip().lower()
    if len(username) < 3:
        raise ValueError("Tên đăng nhập phải có ít nhất 3 ký tự")
    normalized_role = _validate_role(role)
    if fetchone("SELECT id FROM system_users WHERE username=?", (username,)):
        raise ValueError("Tên đăng nhập đã tồn tại")
    _validate_password_strength(password, 12)
    salt, digest = _new_password(password, 12)
    now = utc_now()
    uid = execute(
        """INSERT INTO system_users(username,display_name,role,password_salt,password_hash,active,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        (username, str(display_name or username).strip(), normalized_role, salt, digest, 1, now, now),
    )
    return _public_user({"id": uid, "username": username, "display_name": display_name or username, "role": normalized_role, "active": 1})



def _normalize_phone(phone: str) -> str:
    raw = str(phone or "").strip().replace(" ", "").replace(".", "").replace("-", "")
    if raw.startswith("+84"):
        raw = "0" + raw[3:]
    if not raw.isdigit() or len(raw) < 9 or len(raw) > 12:
        raise ValueError("Số điện thoại không hợp lệ")
    return raw


def _normalize_email(email: str) -> str:
    raw = str(email or "").strip().lower()
    if not raw or "@" not in raw or raw.startswith("@") or raw.endswith("@") or "." not in raw.split("@",1)[-1]:
        raise ValueError("Email không hợp lệ")
    return raw


def _save_user_profile(user_id: int, *, phone: str, email: str = "", status: str = "ACTIVE", phone_verified: bool = False, email_verified: bool = False, store_id: int | None = None) -> None:
    ensure_rbac_schema()
    normalized_phone = _normalize_phone(phone)
    normalized_email = _normalize_email(email) if str(email or "").strip() else ""
    duplicate = fetchone("SELECT user_id FROM account_profiles WHERE phone=? AND user_id<>?", (normalized_phone, int(user_id)))
    if duplicate:
        raise ValueError("Số điện thoại đã được đăng ký")
    if normalized_email:
        duplicate_email = fetchone("SELECT user_id FROM account_profiles WHERE LOWER(email)=? AND user_id<>?", (normalized_email, int(user_id)))
        if duplicate_email:
            raise ValueError("Email đã được đăng ký")
    now = utc_now()
    current = fetchone("SELECT user_id FROM account_profiles WHERE user_id=?", (int(user_id),))
    with connection() as conn:
        if current:
            conn.execute("""UPDATE account_profiles SET phone=?,email=?,account_status=?,phone_verified=?,email_verified=?,store_id=?,updated_at=? WHERE user_id=?""",
                         (normalized_phone, normalized_email, str(status).upper(), 1 if phone_verified else 0, 1 if email_verified else 0, store_id, now, int(user_id)))
        else:
            conn.execute("""INSERT INTO account_profiles(user_id,phone,email,account_status,phone_verified,email_verified,store_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                         (int(user_id), normalized_phone, normalized_email, str(status).upper(), 1 if phone_verified else 0, 1 if email_verified else 0, store_id, now, now))


def _save_user_phone(user_id: int, phone: str) -> None:
    # Compatibility wrapper used by legacy code.
    profile = fetchone("SELECT email,account_status,phone_verified,email_verified,store_id FROM account_profiles WHERE user_id=?", (int(user_id),)) or {}
    _save_user_profile(user_id, phone=phone, email=str(profile.get("email") or ""), status=str(profile.get("account_status") or "ACTIVE"),
                       phone_verified=bool(profile.get("phone_verified",0)), email_verified=bool(profile.get("email_verified",0)), store_id=profile.get("store_id"))


def register_public_user(username: str, display_name: str, phone: str, password: str, email: str = "") -> dict:
    """Compatibility self-registration. V5 creates a verified-but-pending account.

    The public web UI uses OTP request/verify before calling this function. The
    account stays inactive until an authorised manager/admin approves it.
    """
    ensure_rbac_schema()
    normalized_phone = _normalize_phone(phone)
    normalized_email = _normalize_email(email) if str(email or "").strip() else ""
    if fetchone("SELECT user_id FROM account_profiles WHERE phone=?", (normalized_phone,)):
        raise ValueError("Số điện thoại đã được đăng ký")
    if normalized_email and fetchone("SELECT user_id FROM account_profiles WHERE LOWER(email)=?", (normalized_email,)):
        raise ValueError("Email đã được đăng ký")
    username = str(username or "").strip().lower()
    if len(username) < 3:
        raise ValueError("Tên đăng nhập phải có ít nhất 3 ký tự")
    if fetchone("SELECT id FROM system_users WHERE username=?", (username,)):
        raise ValueError("Tên đăng nhập đã tồn tại")
    _validate_password_strength(password, 12)
    salt, digest = _new_password(password, 12)
    now = utc_now()
    uid = execute(
        """INSERT INTO system_users(username,display_name,role,password_salt,password_hash,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
        (username, str(display_name or username).strip(), "EMPLOYEE", salt, digest, 0, now, now),
    )
    try:
        _save_user_profile(int(uid), phone=normalized_phone, email=normalized_email, status="PENDING", phone_verified=True, email_verified=False)
    except Exception:
        try:
            execute("DELETE FROM system_users WHERE id=?", (int(uid),))
        except Exception:
            pass
        raise
    return _public_user({"id": uid, "username": username, "display_name": display_name or username, "role": "EMPLOYEE", "active": 0})

def approve_user(user_id: int, *, role: str, store_id: int | None = None, actor: str = "") -> dict:
    ensure_rbac_schema()
    row = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),))
    if not row:
        raise ValueError("Không tìm thấy tài khoản")
    normalized_role = _validate_role(role)
    if normalized_role == "SUPER_ADMIN":
        raise ValueError("Không thể cấp SUPER_ADMIN từ luồng duyệt thông thường")
    execute("UPDATE system_users SET role=?,active=1,updated_at=? WHERE id=?", (normalized_role, utc_now(), int(user_id)))
    profile = fetchone("SELECT * FROM account_profiles WHERE user_id=?", (int(user_id),)) or {}
    if profile.get("phone"):
        _save_user_profile(int(user_id), phone=str(profile.get("phone")), email=str(profile.get("email") or ""), status="ACTIVE",
                           phone_verified=bool(profile.get("phone_verified",0)), email_verified=bool(profile.get("email_verified",0)), store_id=store_id)
    fresh = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),)) or row
    return _public_user(fresh)

def change_password_by_verified_phone(username: str, password: str) -> dict:
    _validate_password_strength(password, 12)
    row = fetchone("SELECT * FROM system_users WHERE username=?", (str(username or "").strip().lower(),))
    if not row:
        raise ValueError("Không tìm thấy tài khoản")
    salt, digest = _new_password(password, 12)
    execute("UPDATE system_users SET password_salt=?,password_hash=?,updated_at=? WHERE id=?", (salt, digest, utc_now(), int(row.get("id"))))
    with _lock:
        for token, (_, user) in list(_sessions.items()):
            if int(user.get("id") or -1) == int(row.get("id")):
                _sessions.pop(token, None)
    from .sms_auth_v542 import revoke_user
    revoke_user(int(row.get("id")))
    revoke_user_sessions(int(row.get("id")))
    return _public_user(row)


def list_users() -> list[dict]:
    ensure_rbac_schema()
    rows = fetchall("SELECT id,username,display_name,role,active,created_at,updated_at FROM system_users ORDER BY active DESC,id")
    return [{**_public_user(r), "created_at": r.get("created_at"), "updated_at": r.get("updated_at")} for r in rows]


def update_user(user_id: int, *, role: str | None = None, active: bool | None = None, display_name: str | None = None) -> dict:
    row = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),))
    if not row:
        raise ValueError("Không tìm thấy tài khoản")
    values = {
        "role": _validate_role(role) if role is not None else str(row.get("role") or "VIEWER").upper(),
        "active": 1 if (bool(active) if active is not None else bool(row.get("active", 1))) else 0,
        "display_name": str(display_name).strip() if display_name is not None else str(row.get("display_name") or row.get("username") or ""),
    }
    # Never allow the last active root administrator to be demoted/disabled.
    current_role = str(row.get("role") or "").upper()
    if current_role in {"ADMIN", "SUPER_ADMIN"} and bool(row.get("active", 1)) and (values["role"] not in {"ADMIN", "SUPER_ADMIN"} or not values["active"]):
        admins = int((fetchone("SELECT COUNT(*) n FROM system_users WHERE active=1 AND UPPER(role) IN ('ADMIN','SUPER_ADMIN')") or {}).get("n") or 0)
        if admins <= 1:
            raise ValueError("Phải giữ lại ít nhất một tài khoản quản trị gốc đang hoạt động")
    if current_role != "SUPER_ADMIN" and values["role"] == "SUPER_ADMIN":
        raise ValueError("SUPER_ADMIN chỉ được tạo trong quy trình bảo mật cấp hệ thống")
    execute("UPDATE system_users SET display_name=?,role=?,active=?,updated_at=? WHERE id=?", (values["display_name"], values["role"], values["active"], utc_now(), int(user_id)))
    # Role/activation changes must take effect immediately, not after the old
    # eight-hour session expires. Revoke every in-memory session for this user.
    with _lock:
        for token, (_, session_user) in list(_sessions.items()):
            if int(session_user.get("id") or -1) == int(user_id):
                _sessions.pop(token, None)
    fresh = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),)) or row
    from .sms_auth_v542 import revoke_user
    revoke_user(int(user_id))
    revoke_user_sessions(int(user_id))
    return _public_user(fresh)


def reset_user_password(user_id: int, password: str, *, expected_credentials: tuple[str, str] | None = None) -> dict:
    _validate_password_strength(password, 12)
    row = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),))
    if not row:
        raise ValueError("Không tìm thấy tài khoản")
    salt, digest = _new_password(password, 12)
    with connection() as conn:
        sql = "UPDATE system_users SET password_salt=?,password_hash=?,updated_at=? WHERE id=?"
        params = (salt, digest, utc_now(), int(user_id))
        if expected_credentials is not None:
            # Self-service proves the current password first. A concurrent reset
            # must invalidate that proof rather than let an old password win.
            sql += " AND password_salt=? AND password_hash=? AND active=1"
            params += tuple(expected_credentials)
        if conn.execute(sql, params).rowcount != 1:
            raise ValueError("Thông tin đăng nhập đã thay đổi. Hãy đăng nhập lại.")
    # Revoke all in-memory sessions for this account.
    revoke_user_sessions(int(user_id))
    from .sms_auth_v542 import revoke_user
    revoke_user(int(user_id))
    return _public_user(row)


def _login_key(username: str) -> str:
    return str(username or "").strip().lower()[:120]


def _lock_status(store: dict[str, tuple[int, float]], key: str) -> dict:
    now = time.time()
    with _lock:
        failures, locked_until = store.get(key, (0, 0.0))
        if locked_until and locked_until <= now:
            store.pop(key, None)
            return {"locked": False, "failures": 0, "retry_after": 0}
        return {"locked": bool(locked_until > now), "failures": int(failures), "retry_after": max(0, int(round(locked_until - now)))}


def _failure(store: dict[str, tuple[int, float]], key: str) -> None:
    now = time.time()
    with _lock:
        failures, locked_until = store.get(key, (0, 0.0))
        if locked_until > now:
            return
        failures += 1
        store[key] = (failures, now + _LOGIN_LOCK_SEC if failures >= _LOGIN_MAX_FAILURES else 0.0)


def _success(store: dict[str, tuple[int, float]], key: str) -> None:
    with _lock:
        store.pop(key, None)


def login_lock_status(username: str) -> dict:
    return _lock_status(_failed_logins, _login_key(username))


def _totp_secret() -> str:
    # 160-bit RFC 4226/6238 compatible secret, Base32 without padding.
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_step(at_time: float | None = None) -> int:
    return int((time.time() if at_time is None else float(at_time)) // 30)


def _totp_code(secret: str, *, step: int | None = None) -> str:
    raw = str(secret or "").strip().upper().replace(" ", "")
    padded = raw + ("=" * ((8 - len(raw) % 8) % 8))
    key = base64.b32decode(padded, casefold=True)
    counter = int(_totp_step() if step is None else step).to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def _verify_totp(secret: str, code: str, *, last_used_step: int = -1, at_time: float | None = None) -> int | None:
    candidate = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(candidate) != 6:
        return None
    current = _totp_step(at_time)
    # A ±30 second window tolerates small clock drift. last_used_step prevents
    # replaying a code already accepted for this account.
    for step in (current - 1, current, current + 1):
        if step <= int(last_used_step):
            continue
        if hmac.compare_digest(_totp_code(secret, step=step), candidate):
            return step
    return None


def _encrypt_totp_secret(secret: str) -> str:
    return base64.urlsafe_b64encode(encrypt_bytes(str(secret).encode("utf-8"))).decode("ascii")


def _decrypt_totp_secret(secret_enc: str) -> str:
    if not secret_enc:
        return ""
    return decrypt_bytes(base64.urlsafe_b64decode(str(secret_enc).encode("ascii"))).decode("utf-8")


def _mfa_record(user_id: int) -> dict:
    ensure_rbac_schema()
    return fetchone("SELECT * FROM account_mfa WHERE user_id=?", (int(user_id),)) or {}


def mfa_status(user_id: int, role: str = "") -> dict:
    normalized_role = str(role or "").upper()
    record = _mfa_record(int(user_id))
    enabled = bool(record.get("enabled", 0) and record.get("secret_enc"))
    return {
        "required": normalized_role in _MFA_REQUIRED_ROLES,
        "enabled": enabled,
        "method": "TOTP" if enabled else "",
        "enrolled_at": record.get("enrolled_at"),
        "recovery_codes_remaining": int((fetchone(
            "SELECT COUNT(*) AS n FROM account_mfa_recovery_codes WHERE user_id=? AND used_at IS NULL",
            (int(user_id),),
        ) or {}).get("n") or 0),
    }


def _cleanup_mfa_challenges() -> None:
    now = time.time()
    with _lock:
        for challenge_id, item in list(_mfa_challenges.items()):
            if float(item.get("expires_at") or 0) <= now:
                _mfa_challenges.pop(challenge_id, None)


def _new_mfa_challenge(row: dict, *, setup: bool) -> dict:
    _cleanup_mfa_challenges()
    challenge_id = secrets.token_urlsafe(28)
    secret = _totp_secret() if setup else ""
    username = str(row.get("username") or "")
    with _lock:
        _mfa_challenges[challenge_id] = {
            "user_id": int(row.get("id") or 0),
            "mode": "SETUP" if setup else "VERIFY",
            "secret": secret,
            "attempts": 0,
            "expires_at": time.time() + _MFA_CHALLENGE_TTL,
        }
    out = {
        "mfa_required": True,
        "mfa_setup_required": bool(setup),
        "challenge_id": challenge_id,
        "expires_in": _MFA_CHALLENGE_TTL,
        "user": _public_user(row),
    }
    if setup:
        label = quote(f"{_MFA_ISSUER}:{username}")
        issuer = quote(_MFA_ISSUER)
        out["mfa_setup"] = {
            "method": "TOTP",
            "issuer": _MFA_ISSUER,
            "account": username,
            "secret": secret,
            "otpauth_uri": f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&digits=6&period=30",
        }
    return out


def _mfa_failed_attempt(challenge_id: str) -> bool:
    """Return True when the challenge is exhausted and has been revoked."""
    with _lock:
        item = _mfa_challenges.get(str(challenge_id or ""))
        if not item:
            return True
        item["attempts"] = int(item.get("attempts") or 0) + 1
        if int(item["attempts"]) >= 5:
            _mfa_challenges.pop(str(challenge_id or ""), None)
            return True
        return False


def _new_recovery_codes(count: int = 8) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes: list[str] = []
    for _ in range(max(1, int(count))):
        raw = "".join(secrets.choice(alphabet) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def _recovery_hash(code: str) -> str:
    normalized = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _persist_mfa_setup(user_id: int, secret: str, used_step: int) -> list[str]:
    now = utc_now()
    enc = _encrypt_totp_secret(secret)
    codes = _new_recovery_codes(8)
    with connection() as conn:
        current = conn.execute("SELECT user_id FROM account_mfa WHERE user_id=?", (int(user_id),)).fetchone()
        if current:
            conn.execute(
                "UPDATE account_mfa SET method='TOTP',secret_enc=?,enabled=1,last_used_step=?,enrolled_at=?,updated_at=? WHERE user_id=?",
                (enc, int(used_step), now, now, int(user_id)),
            )
        else:
            conn.execute(
                "INSERT INTO account_mfa(user_id,method,secret_enc,enabled,last_used_step,enrolled_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (int(user_id), "TOTP", enc, 1, int(used_step), now, now),
            )
        conn.execute("DELETE FROM account_mfa_recovery_codes WHERE user_id=?", (int(user_id),))
        for code in codes:
            conn.execute(
                "INSERT INTO account_mfa_recovery_codes(user_id,code_hash,used_at,created_at) VALUES(?,?,NULL,?)",
                (int(user_id), _recovery_hash(code), now),
            )
    return codes


def _consume_recovery_code(user_id: int, code: str) -> bool:
    digest = _recovery_hash(code)
    if len("".join(ch for ch in str(code or "") if ch.isalnum())) < 8:
        return False
    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT code_hash,used_at FROM account_mfa_recovery_codes WHERE user_id=? AND code_hash=?",
            (int(user_id), digest),
        ).fetchone()
        if not row:
            return False
        used_at = row["used_at"] if hasattr(row, "keys") else row[1]
        if used_at:
            return False
        cur = conn.execute(
            "UPDATE account_mfa_recovery_codes SET used_at=? WHERE user_id=? AND code_hash=? AND used_at IS NULL",
            (now, int(user_id), digest),
        )
        return bool(getattr(cur, "rowcount", 0))


def _issue_session(row: dict) -> dict:
    token = secrets.token_urlsafe(32)
    user = _public_user(row)
    from .sms_auth_v542 import credential_tag
    tag = credential_tag(row)
    with _lock:
        _sessions[token] = (time.time() + _SESSION_TTL, user)
        _session_credential_tags[token] = tag
    return {"token": token, "expires_in": _SESSION_TTL, "user": user}


def _authenticate_password(username: str, password: str) -> dict:
    ensure_rbac_schema()
    key = _login_key(username)
    lock = login_lock_status(key)
    if lock["locked"]:
        raise ValueError(f"Đăng nhập tạm khóa. Thử lại sau {lock['retry_after']} giây")
    row = fetchone("SELECT * FROM system_users WHERE username=?", (key,))
    if not row:
        _failure(_failed_logins, key)
        raise ValueError("Sai tên đăng nhập hoặc mật khẩu")
    password_ok, needs_upgrade = _verify_password(password, str(row.get("password_salt") or ""), str(row.get("password_hash") or ""))
    if not password_ok:
        _failure(_failed_logins, key)
        raise ValueError("Sai tên đăng nhập hoặc mật khẩu")
    if needs_upgrade:
        try:
            new_salt, new_digest = _new_password(password, 1)
            execute("UPDATE system_users SET password_salt=?,password_hash=?,updated_at=? WHERE id=?", (new_salt, new_digest, utc_now(), int(row.get("id"))))
            row["password_salt"], row["password_hash"] = new_salt, new_digest
        except Exception:
            pass
    role = str(row.get("role") or "EMPLOYEE").upper()
    profile = fetchone("SELECT account_status,phone_verified FROM account_profiles WHERE user_id=?", (int(row.get("id") or 0),)) or {}
    status = str(profile.get("account_status") or ("ACTIVE" if bool(row.get("active",1)) else "DISABLED")).upper()
    if status == "PENDING":
        _success(_failed_logins, key)
        raise ValueError("Tài khoản đã xác minh số điện thoại và đang chờ quản trị viên phê duyệt")
    if not bool(row.get("active", 1)) or status in {"DISABLED", "LOCKED", "REJECTED"}:
        _success(_failed_logins, key)
        raise ValueError("Tài khoản hiện chưa được phép truy cập hệ thống")
    _success(_failed_logins, key)
    return row


def login(username: str, password: str, *, trusted_cookie: str = "", binding: str = "", allow_trust: bool = False) -> dict:
    """Password first. SMS after enrollment; preserve existing enabled TOTP.

    A trusted browser skips only the second factor, never the password. An
    unconfigured provider does NOT downgrade an enrolled account to password-only.
    """
    from . import sms_auth_v542 as sms
    row = _authenticate_password(username, password)
    uid = int(row["id"])
    sms_record = sms.factor(uid)
    record = _mfa_record(uid)
    totp_enabled = bool(record.get("enabled") and record.get("secret_enc"))
    if sms_record or totp_enabled:
        if sms.trust(row, trusted_cookie, allowed=allow_trust):
            out = _issue_session(row)
            out["trusted_browser"] = True
            return out
        if sms_record:
            return sms.begin_login(row, binding)
        out = _new_mfa_challenge(row, setup=False)
        with _lock:
            _mfa_challenges[out["challenge_id"]]["credential_tag"] = sms.credential_tag(row)
            _mfa_challenges[out["challenge_id"]]["binding_hash"] = sms.digest(binding) if binding else ""
        out["mfa_method"] = "TOTP"
        return out
    return _issue_session(row)


def complete_mfa_challenge(challenge_id: str, code: str, *, binding: str = "") -> dict:
    with _lock:
        return _complete_mfa_challenge_locked(challenge_id, code, binding=binding)


def _complete_mfa_challenge_locked(challenge_id: str, code: str, *, binding: str = "") -> dict:
    _cleanup_mfa_challenges()
    cid = str(challenge_id or "").strip()
    with _lock:
        challenge = dict(_mfa_challenges.get(cid) or {})
    if not challenge:
        raise ValueError("Phiên xác thực 2 lớp đã hết hạn. Hãy đăng nhập lại")
    user_id = int(challenge.get("user_id") or 0)
    row = fetchone("SELECT * FROM system_users WHERE id=?", (user_id,))
    if not row or not bool(row.get("active", 1)):
        with _lock:
            _mfa_challenges.pop(cid, None)
        raise ValueError("Tài khoản không còn hoạt động")
    from . import sms_auth_v542 as sms
    if (challenge.get("credential_tag") != sms.credential_tag(row)
        or (challenge.get("binding_hash") and challenge["binding_hash"] != sms.digest(binding))):
        raise ValueError("Phien xac minh khong hop le. Hay dang nhap lai")
    # Persistent factor budget prevents restarting challenges to reset attempts.
    with connection() as conn:
        sms._take_budget(conn, "verify:"+str(user_id), 900, 10)

    recovery_codes: list[str] = []
    mode = str(challenge.get("mode") or "VERIFY").upper()
    if mode == "SETUP":
        secret = str(challenge.get("secret") or "")
        step = _verify_totp(secret, code, last_used_step=-1)
        if step is None:
            exhausted = _mfa_failed_attempt(cid)
            raise ValueError("Quá nhiều lần MFA sai. Hãy đăng nhập lại" if exhausted else "Mã Authenticator không hợp lệ")
        recovery_codes = _persist_mfa_setup(user_id, secret, step)
    else:
        record = _mfa_record(user_id)
        if not bool(record.get("enabled", 0)) or not record.get("secret_enc"):
            raise ValueError("MFA của tài khoản chưa được cấu hình")
        raw_code = str(code or "").strip()
        digits = "".join(ch for ch in raw_code if ch.isdigit())
        if len(digits) == 6 and all(ch.isdigit() or ch.isspace() for ch in raw_code):
            secret = _decrypt_totp_secret(str(record.get("secret_enc") or ""))
            step = _verify_totp(secret, digits, last_used_step=int(record.get("last_used_step") or -1))
            if step is None:
                exhausted = _mfa_failed_attempt(cid)
                raise ValueError("Quá nhiều lần MFA sai. Hãy đăng nhập lại" if exhausted else "Mã Authenticator không hợp lệ hoặc đã được sử dụng")
            execute("UPDATE account_mfa SET last_used_step=?,updated_at=? WHERE user_id=?", (int(step), utc_now(), user_id))
        elif not _consume_recovery_code(user_id, raw_code):
            exhausted = _mfa_failed_attempt(cid)
            raise ValueError("Quá nhiều lần MFA sai. Hãy đăng nhập lại" if exhausted else "Mã xác thực hoặc mã khôi phục không hợp lệ")

    with _lock:
        _mfa_challenges.pop(cid, None)
    out = _issue_session(row)
    out["mfa_verified"] = True
    mark_factor_verified(out["token"])
    if recovery_codes:
        out["recovery_codes"] = recovery_codes
        out["message"] = "MFA đã được kích hoạt. Hãy lưu các mã khôi phục ở nơi an toàn; chúng chỉ hiển thị lần này."
    return out


def reset_user_mfa(user_id: int) -> dict:
    row = fetchone("SELECT * FROM system_users WHERE id=?", (int(user_id),))
    if not row:
        raise ValueError("Không tìm thấy tài khoản")
    with connection() as conn:
        conn.execute("DELETE FROM account_mfa_recovery_codes WHERE user_id=?", (int(user_id),))
        conn.execute("DELETE FROM account_mfa WHERE user_id=?", (int(user_id),))
        conn.execute("DELETE FROM privileged_security_profiles WHERE user_id=?", (int(user_id),))
    with _lock:
        for token, (_, user) in list(_sessions.items()):
            if int(user.get("id") or -1) == int(user_id):
                _sessions.pop(token, None)
        for cid, item in list(_mfa_challenges.items()):
            if int(item.get("user_id") or -1) == int(user_id):
                _mfa_challenges.pop(cid, None)
        for cid, item in list(_privileged_login_challenges.items()):
            if int(item.get("user_id") or -1) == int(user_id):
                _privileged_login_challenges.pop(cid, None)
    from .sms_auth_v542 import revoke_user
    revoke_user(int(user_id))
    revoke_user_sessions(int(user_id))
    with connection() as conn:
        conn.execute("DELETE FROM sms_factors_v542 WHERE user_id=?", (int(user_id),))
    return _public_user(row)


def logout(token: str) -> None:
    with _lock:
        _sessions.pop(token, None)
        _session_factor_times.pop(token, None)
        _session_credential_tags.pop(token, None)


def mark_factor_verified(token: str) -> None:
    with _lock:
        if token in _sessions:
            _session_factor_times[token] = time.time()


def factor_is_fresh(token: str) -> bool:
    with _lock:
        return token in _sessions and time.time() - _session_factor_times.get(token, 0) < 300


def revoke_user_sessions(user_id: int) -> None:
    with _lock:
        for token, (_, user) in list(_sessions.items()):
            if int(user.get("id") or -1) == int(user_id):
                _sessions.pop(token, None)
                _session_factor_times.pop(token, None)
                _session_credential_tags.pop(token, None)


def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    now = time.time()
    with _lock:
        for key, (expiry, _) in list(_sessions.items()):
            if expiry <= now:
                _sessions.pop(key, None)
                _session_factor_times.pop(key, None)
                _session_credential_tags.pop(key, None)
        item = _sessions.get(token)
        tag = _session_credential_tags.get(token, "")
    if not item:
        return None
    from .sms_auth_v542 import credential_tag
    row = fetchone("SELECT * FROM system_users WHERE id=?", (int(item[1]["id"]),))
    profile = fetchone("SELECT account_status FROM account_profiles WHERE user_id=?", (int(item[1]["id"]),)) or {}
    if (not row or not row.get("active") or profile.get("account_status", "ACTIVE") != "ACTIVE"
        or not hmac.compare_digest(tag, credential_tag(row))):
        logout(token)
        return None
    return dict(item[1])


def token_from_authorization(value: str) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


def _route_role_allowed(user_role: str, requested: set[str]) -> bool:
    if not requested:
        return True
    role = str(user_role or "VIEWER").upper()
    effective = ROLE_ROUTE_GRANTS.get(role, {role})
    return bool(effective.intersection({str(x).upper() for x in requested}))


def require_role(authorization: str, roles: set[str] | None = None) -> dict:
    if user_count() == 0:
        return {"id": 0, "username": "bootstrap", "display_name": "Thiết lập ban đầu", "role": "ADMIN", "permissions": ["*"]}
    user = user_for_token(token_from_authorization(authorization))
    if not user:
        raise PermissionError("Cần đăng nhập để thực hiện thao tác này")
    if roles and not _route_role_allowed(str(user.get("role") or ""), roles):
        raise PermissionError("Tài khoản không có quyền thực hiện thao tác này")
    return user


def has_permission(user: dict | None, permission: str) -> bool:
    if not user:
        return False
    permissions = set(user.get("permissions") or permissions_for_role(str(user.get("role") or "VIEWER")))
    return "*" in permissions or str(permission) in permissions


def require_permission(authorization: str, permission: str) -> dict:
    user = require_role(authorization, None)
    if not has_permission(user, permission):
        raise PermissionError(f"Thiếu quyền: {permission}")
    return user

# --------------------------- Mobile Viewer (read-only) ---------------------------

def mobile_viewer_status() -> dict:
    enabled = _setting_get("mobile_viewer_enabled", "0") == "1"
    salt = _setting_get("mobile_viewer_salt", "")
    digest = _setting_get("mobile_viewer_hash", "")
    configured = bool(salt and digest)
    return {"enabled": bool(enabled and configured), "configured": configured, "mode": "READ_ONLY"}


def configure_mobile_viewer(*, enabled: bool, password: str = "") -> dict:
    current = mobile_viewer_status()
    if password:
        salt, digest = _new_password(password, 6)
        _setting_set("mobile_viewer_salt", salt)
        _setting_set("mobile_viewer_hash", digest)
        current["configured"] = True
    if enabled and not (current.get("configured") or mobile_viewer_status().get("configured")):
        raise ValueError("Hãy đặt mật khẩu Mobile Viewer trước khi bật")
    _setting_set("mobile_viewer_enabled", "1" if enabled else "0")
    if not enabled:
        with _lock:
            _mobile_sessions.clear()
    return mobile_viewer_status()


def mobile_login_lock_status() -> dict:
    return _lock_status(_mobile_failed, "mobile")


def mobile_login(password: str) -> dict:
    status = mobile_viewer_status()
    if not status.get("enabled"):
        raise ValueError("Mobile Viewer chưa được Admin bật")
    lock = mobile_login_lock_status()
    if lock["locked"]:
        raise ValueError(f"Mobile Viewer tạm khóa. Thử lại sau {lock['retry_after']} giây")
    salt_marker = _setting_get("mobile_viewer_salt", "")
    expected = _setting_get("mobile_viewer_hash", "")
    password_ok, needs_upgrade = _verify_password(str(password or ""), salt_marker, expected)
    if not password_ok:
        _failure(_mobile_failed, "mobile")
        raise ValueError("Sai mật khẩu Mobile Viewer")
    if needs_upgrade:
        try:
            new_salt, new_hash = _new_password(str(password or ""), 1)
            _setting_set("mobile_viewer_salt", new_salt)
            _setting_set("mobile_viewer_hash", new_hash)
        except Exception:
            pass
    _success(_mobile_failed, "mobile")
    token = secrets.token_urlsafe(32)
    viewer = {"kind": "MOBILE_VIEWER", "mode": "READ_ONLY", "display_name": "Mobile Viewer"}
    with _lock:
        _mobile_sessions[token] = (time.time() + _MOBILE_SESSION_TTL, viewer)
    return {"token": token, "expires_in": _MOBILE_SESSION_TTL, "viewer": viewer}


def mobile_logout(token: str) -> None:
    with _lock:
        _mobile_sessions.pop(token, None)


def mobile_user_for_token(token: str) -> dict | None:
    if not token:
        return None
    now = time.time()
    with _lock:
        expired = [k for k, (exp, _) in _mobile_sessions.items() if exp <= now]
        for k in expired:
            _mobile_sessions.pop(k, None)
        item = _mobile_sessions.get(token)
        return dict(item[1]) if item else None


# V5.4 Customer Release: semantic read permissions used by protected API routes.
# This compatibility installer extends any role-permission mapping already defined
# by the legacy application; it does not replace the original RBAC model.
V54_PERMISSION_ALIASES_INSTALLED = True
_V54_ROLE_PERMISSION_ADDITIONS = {
    "SUPER_ADMIN": {"camera.view", "employee.view", "history.view", "evidence.view", "operations.view", "system.diagnostics", "report.view"},
    "ADMIN": {"camera.view", "employee.view", "history.view", "evidence.view", "operations.view", "system.diagnostics", "report.view"},
    "MANAGER": {"camera.view", "employee.view", "history.view", "evidence.view", "operations.view", "report.view"},
    "HR": {"employee.view", "history.view", "report.view"},
    "SECURITY": {"camera.view", "history.view", "evidence.view", "operations.view"},
    "OPERATOR": {"camera.view", "history.view", "evidence.view", "operations.view"},
    "TECHNICIAN": {"camera.view", "operations.view", "system.diagnostics"},
}

def _v54_extend_role_permissions() -> None:
    for _mapping in list(globals().values()):
        if not isinstance(_mapping, dict) or not _mapping:
            continue
        normalized = {}
        for _key in list(_mapping.keys()):
            _name = str(getattr(_key, "value", _key)).upper()
            normalized[_name] = _key
        if "SUPER_ADMIN" not in normalized and "ADMIN" not in normalized:
            continue
        for _role_name, _additions in _V54_ROLE_PERMISSION_ADDITIONS.items():
            _real_key = normalized.get(_role_name)
            if _real_key is None:
                continue
            _current = _mapping.get(_real_key)
            if isinstance(_current, set):
                _current.update(_additions)
            elif isinstance(_current, list):
                for _permission in sorted(_additions):
                    if _permission not in _current:
                        _current.append(_permission)
            elif isinstance(_current, tuple):
                _mapping[_real_key] = tuple(dict.fromkeys([*_current, *sorted(_additions)]))

_v54_extend_role_permissions()
