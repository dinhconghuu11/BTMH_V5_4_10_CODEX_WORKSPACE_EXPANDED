from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import ssl
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from .config import CONFIG_DIR
from .db import connection, execute, fetchall, fetchone, utc_now
from .secret_store import SecretStoreError, load_secret, save_secret

OTP_TTL_SECONDS = 300
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 5
OTP_MAX_PER_HOUR = 6
OTP_DELIVERY_CONFIG_KEY = "otp_delivery_config_v2"
SMS_SECRET_PATH = CONFIG_DIR / "otp_sms_provider_secret.dpapi"
SMTP_SECRET_PATH = CONFIG_DIR / "otp_smtp_password.dpapi"


def _bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _legacy_env_config() -> dict:
    sms_provider = str(os.getenv("BTMH_SMS_PROVIDER", "DEMO") or "DEMO").strip().upper()
    email_provider = str(os.getenv("BTMH_EMAIL_PROVIDER", "DEMO") or "DEMO").strip().upper()
    return {
        "sms": {
            "enabled": sms_provider != "OFF",
            "provider": sms_provider if sms_provider in {"DEMO", "WEBHOOK", "TWILIO"} else "DEMO",
            "webhook_url": str(os.getenv("BTMH_SMS_WEBHOOK_URL", "") or "").strip(),
            "account_sid": str(os.getenv("BTMH_TWILIO_ACCOUNT_SID", "") or "").strip(),
            "sender": str(os.getenv("BTMH_SMS_SENDER", os.getenv("BTMH_TWILIO_FROM", "")) or "").strip(),
        },
        "email": {
            "enabled": email_provider != "OFF",
            "provider": email_provider if email_provider in {"DEMO", "SMTP"} else "DEMO",
            "host": str(os.getenv("BTMH_SMTP_HOST", "") or "").strip(),
            "port": int(str(os.getenv("BTMH_SMTP_PORT", "587") or "587")),
            "username": str(os.getenv("BTMH_SMTP_USERNAME", "") or "").strip(),
            "from_email": str(os.getenv("BTMH_SMTP_FROM", os.getenv("BTMH_SMTP_USERNAME", "")) or "").strip(),
            "ssl": _bool(os.getenv("BTMH_SMTP_SSL", "0")),
            "starttls": _bool(os.getenv("BTMH_SMTP_STARTTLS", "1"), True),
        },
    }


def _runtime_config() -> dict:
    base = _legacy_env_config()
    try:
        row = fetchone("SELECT setting_value FROM runtime_settings WHERE setting_key=?", (OTP_DELIVERY_CONFIG_KEY,))
        if not row:
            return base
        raw = json.loads(str(row.get("setting_value") or "{}"))
        if isinstance(raw.get("sms"), dict):
            base["sms"].update(raw["sms"])
        if isinstance(raw.get("email"), dict):
            base["email"].update(raw["email"])
    except Exception:
        pass
    return base


def _secret(path, env_name: str = "") -> str:
    env_value = str(os.getenv(env_name, "") or "") if env_name else ""
    try:
        return load_secret(path, env_value)
    except (SecretStoreError, OSError, ValueError):
        return env_value


def _sms_secret(provider: str = "") -> str:
    # WEBHOOK bearer token and Twilio Auth Token intentionally share one DPAPI slot;
    # switching provider replaces only this secret, never exposes it to the browser.
    stored = _secret(SMS_SECRET_PATH)
    if stored:
        return stored
    mode = str(provider or "").upper()
    if mode == "TWILIO":
        return str(os.getenv("BTMH_TWILIO_AUTH_TOKEN", "") or "")
    return str(os.getenv("BTMH_SMS_WEBHOOK_TOKEN", "") or "")


def _smtp_password() -> str:
    return _secret(SMTP_SECRET_PATH, "BTMH_SMTP_PASSWORD")


def delivery_config_public() -> dict:
    cfg = _runtime_config()
    sms = cfg.get("sms") or {}
    email = cfg.get("email") or {}
    return {
        "sms": {
            "enabled": _bool(sms.get("enabled"), True),
            "provider": str(sms.get("provider") or "DEMO").upper(),
            "webhook_url": str(sms.get("webhook_url") or ""),
            "account_sid": str(sms.get("account_sid") or ""),
            "sender": str(sms.get("sender") or ""),
            "secret_configured": bool(_sms_secret(str(sms.get("provider") or ""))),
        },
        "email": {
            "enabled": _bool(email.get("enabled"), True),
            "provider": str(email.get("provider") or "DEMO").upper(),
            "host": str(email.get("host") or ""),
            "port": int(email.get("port") or 587),
            "username": str(email.get("username") or ""),
            "from_email": str(email.get("from_email") or ""),
            "ssl": _bool(email.get("ssl")),
            "starttls": _bool(email.get("starttls"), True),
            "password_configured": bool(_smtp_password()),
        },
    }


def save_delivery_config(payload: dict) -> dict:
    current = _runtime_config()
    incoming = payload or {}
    sms_in = incoming.get("sms") if isinstance(incoming.get("sms"), dict) else {}
    email_in = incoming.get("email") if isinstance(incoming.get("email"), dict) else {}

    sms_provider = str(sms_in.get("provider", current.get("sms", {}).get("provider", "DEMO")) or "DEMO").strip().upper()
    email_provider = str(email_in.get("provider", current.get("email", {}).get("provider", "DEMO")) or "DEMO").strip().upper()
    if sms_provider not in {"DEMO", "WEBHOOK", "TWILIO"}:
        raise ValueError("SMS provider chỉ hỗ trợ DEMO, WEBHOOK hoặc TWILIO")
    if email_provider not in {"DEMO", "SMTP"}:
        raise ValueError("Email provider chỉ hỗ trợ DEMO hoặc SMTP")

    sms = {
        "enabled": _bool(sms_in.get("enabled", current.get("sms", {}).get("enabled", True)), True),
        "provider": sms_provider,
        "webhook_url": str(sms_in.get("webhook_url", current.get("sms", {}).get("webhook_url", "")) or "").strip(),
        "account_sid": str(sms_in.get("account_sid", current.get("sms", {}).get("account_sid", "")) or "").strip(),
        "sender": str(sms_in.get("sender", current.get("sms", {}).get("sender", "")) or "").strip(),
    }
    email = {
        "enabled": _bool(email_in.get("enabled", current.get("email", {}).get("enabled", True)), True),
        "provider": email_provider,
        "host": str(email_in.get("host", current.get("email", {}).get("host", "")) or "").strip(),
        "port": max(1, min(65535, int(email_in.get("port", current.get("email", {}).get("port", 587)) or 587))),
        "username": str(email_in.get("username", current.get("email", {}).get("username", "")) or "").strip(),
        "from_email": str(email_in.get("from_email", current.get("email", {}).get("from_email", "")) or "").strip(),
        "ssl": _bool(email_in.get("ssl", current.get("email", {}).get("ssl", False))),
        "starttls": _bool(email_in.get("starttls", current.get("email", {}).get("starttls", True)), True),
    }
    if email["ssl"]:
        email["starttls"] = False
    if sms["enabled"] and sms_provider == "WEBHOOK" and not sms["webhook_url"]:
        raise ValueError("WEBHOOK SMS cần URL gateway")
    if sms["enabled"] and sms_provider == "TWILIO" and (not sms["account_sid"] or not sms["sender"]):
        raise ValueError("Twilio cần Account SID và Sender/From")
    if email["enabled"] and email_provider == "SMTP" and (not email["host"] or not email["from_email"]):
        raise ValueError("SMTP cần Host và địa chỉ From")

    sms_secret = str(sms_in.get("secret") or "")
    smtp_password = str(email_in.get("password") or "")
    if sms_secret:
        save_secret(SMS_SECRET_PATH, sms_secret, machine_scope=True)
    if smtp_password:
        save_secret(SMTP_SECRET_PATH, smtp_password, machine_scope=True)
    if _bool(sms_in.get("clear_secret")) and SMS_SECRET_PATH.exists():
        SMS_SECRET_PATH.unlink()
    if _bool(email_in.get("clear_password")) and SMTP_SECRET_PATH.exists():
        SMTP_SECRET_PATH.unlink()

    now = utc_now()
    serialized = json.dumps({"sms": sms, "email": email}, ensure_ascii=False, separators=(",", ":"))
    if fetchone("SELECT setting_key FROM runtime_settings WHERE setting_key=?", (OTP_DELIVERY_CONFIG_KEY,)):
        execute("UPDATE runtime_settings SET setting_value=?,updated_at=? WHERE setting_key=?", (serialized, now, OTP_DELIVERY_CONFIG_KEY))
    else:
        execute("INSERT INTO runtime_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)", (OTP_DELIVERY_CONFIG_KEY, serialized, now))
    return delivery_config_public()


def delivery_status() -> dict:
    """Return non-secret delivery readiness so the UI never confuses DEMO with real delivery."""
    cfg = delivery_config_public()
    sms = cfg["sms"]
    email = cfg["email"]
    sms_provider = str(sms.get("provider") or "DEMO").upper()
    email_provider = str(email.get("provider") or "DEMO").upper()
    sms_configured = bool(sms.get("enabled")) and (
        (sms_provider == "WEBHOOK" and bool(sms.get("webhook_url")))
        or (sms_provider == "TWILIO" and bool(sms.get("account_sid") and sms.get("sender") and sms.get("secret_configured")))
    )
    # Bearer token is optional for a generic webhook because some on-prem gateways
    # authenticate by network/IP, while Twilio always needs its Auth Token.
    email_configured = bool(email.get("enabled")) and email_provider == "SMTP" and bool(email.get("host") and email.get("from_email") and (not email.get("username") or email.get("password_configured")))
    sms_real = bool(sms_configured and sms_provider != "DEMO")
    email_real = bool(email_configured and email_provider != "DEMO")
    return {
        "sms": {"provider": sms_provider, "configured": bool(sms_configured), "real_delivery": sms_real, "enabled": bool(sms.get("enabled"))},
        "email": {"provider": email_provider, "configured": bool(email_configured), "real_delivery": email_real, "enabled": bool(email.get("enabled"))},
        "demo": not sms_real and not email_real,
    }


def ensure_otp_schema() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS auth_otp_challenges (
        challenge_id TEXT PRIMARY KEY,
        purpose TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT 'SMS',
        destination_hash TEXT NOT NULL,
        destination_hint TEXT NOT NULL DEFAULT '',
        otp_salt TEXT NOT NULL,
        otp_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        consumed INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_auth_otp_destination ON auth_otp_challenges(destination_hash,created_at DESC);
    """
    with connection() as conn:
        conn.executescript(schema)
    # Upgrade V5.2 databases that created the OTP table before channels existed.
    try:
        with connection() as conn:
            conn.execute("ALTER TABLE auth_otp_challenges ADD COLUMN channel TEXT NOT NULL DEFAULT 'SMS'")
    except Exception:
        pass


def _normalize_phone(phone: str) -> str:
    raw = str(phone or "").strip().replace(" ", "").replace(".", "").replace("-", "")
    if raw.startswith("+84"):
        raw = "0" + raw[3:]
    if not raw.isdigit() or len(raw) < 9 or len(raw) > 12:
        raise ValueError("Số điện thoại không hợp lệ")
    return raw


def _normalize_email(email: str) -> str:
    raw = str(email or "").strip().lower()
    if not raw or "@" not in raw or raw.startswith("@") or raw.endswith("@"):
        raise ValueError("Email không hợp lệ")
    local, domain = raw.rsplit("@", 1)
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Email không hợp lệ")
    return raw


def _normalize_destination(channel: str, destination: str) -> tuple[str, str]:
    method = str(channel or "SMS").strip().upper()
    if method == "SMS":
        return method, _normalize_phone(destination)
    if method == "EMAIL":
        return method, _normalize_email(destination)
    raise ValueError("Phương thức OTP không hợp lệ")


def _destination_hint(channel: str, destination: str) -> str:
    method = str(channel or "SMS").upper()
    value = str(destination or "")
    if method == "SMS":
        return "******" + value[-4:]
    local, _, domain = value.partition("@")
    if not local:
        return "***"
    shown = local[:1] + "***" if len(local) > 1 else "***"
    return shown + ("@" + domain if domain else "")


def _dest_hash(purpose: str, channel: str, destination: str) -> str:
    method, normalized = _normalize_destination(channel, destination)
    # Resend throttling is purpose-scoped so completing first-time contact
    # verification does not block the first real login OTP for 60 seconds.
    return hashlib.sha256(f"{str(purpose).upper()}:{method}:{normalized}".encode("utf-8")).hexdigest()


def _hash_code(code: str, salt: bytes) -> str:
    raw = hashlib.pbkdf2_hmac("sha256", str(code).encode("ascii"), salt, 120_000)
    return base64.b64encode(raw).decode("ascii")


def _parse(value: str) -> datetime:
    raw = str(value or "").replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _send_sms(phone: str, code: str, purpose: str) -> dict:
    cfg = _runtime_config().get("sms") or {}
    provider = str(cfg.get("provider") or "DEMO").strip().upper()
    enabled = _bool(cfg.get("enabled"), True)
    message = f"BTMH Security: Ma OTP cua ban la {code}. Ma co hieu luc 5 phut. Khong chia se ma nay."
    if not enabled:
        raise RuntimeError("Kênh SMS OTP đang tắt trong Quản trị & bảo mật")
    if provider == "DEMO":
        return {"provider": "DEMO", "delivered": True, "demo_otp": code}
    if provider == "WEBHOOK":
        url = str(cfg.get("webhook_url") or "").strip()
        if not url:
            raise RuntimeError("Chưa cấu hình URL SMS Gateway")
        body = json.dumps({
            "to": _normalize_phone(phone),
            "message": message,
            "purpose": purpose,
            "sender": str(cfg.get("sender") or ""),
        }, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        token = _sms_secret(provider)
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if int(resp.status) >= 300:
                raise RuntimeError(f"SMS gateway trả về HTTP {resp.status}")
        return {"provider": "WEBHOOK", "delivered": True}
    if provider == "TWILIO":
        account_sid = str(cfg.get("account_sid") or "").strip()
        sender = str(cfg.get("sender") or "").strip()
        auth_token = _sms_secret(provider)
        if not account_sid or not sender or not auth_token:
            raise RuntimeError("Twilio chưa đủ Account SID, Auth Token và Sender")
        target = _normalize_phone(phone)
        # BTMH normalizes Vietnamese +84 to 0 for account identity; Twilio requires E.164.
        if target.startswith("0"):
            target = "+84" + target[1:]
        elif not target.startswith("+"):
            target = "+" + target
        url = f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(account_sid, safe='')}/Messages.json"
        form = urllib.parse.urlencode({"To": target, "From": sender, "Body": message}).encode("utf-8")
        basic = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
        req = urllib.request.Request(url, data=form, headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            if int(resp.status) >= 300:
                raise RuntimeError(f"Twilio trả về HTTP {resp.status}")
        return {"provider": "TWILIO", "delivered": True}
    raise RuntimeError("Nhà cung cấp SMS chưa được cấu hình")


def _send_email(email: str, code: str, purpose: str) -> dict:
    cfg = _runtime_config().get("email") or {}
    provider = str(cfg.get("provider") or "DEMO").strip().upper()
    enabled = _bool(cfg.get("enabled"), True)
    if not enabled:
        raise RuntimeError("Kênh Email OTP đang tắt trong Quản trị & bảo mật")
    if provider == "DEMO":
        return {"provider": "DEMO", "delivered": True, "demo_otp": code}
    if provider != "SMTP":
        raise RuntimeError("Nhà cung cấp Email chưa được cấu hình")

    host = str(cfg.get("host") or "").strip()
    port = int(cfg.get("port") or 587)
    username = str(cfg.get("username") or "").strip()
    password = _smtp_password()
    sender = str(cfg.get("from_email") or username).strip()
    use_ssl = _bool(cfg.get("ssl"))
    use_starttls = _bool(cfg.get("starttls"), True)
    if not host or not sender:
        raise RuntimeError("Chưa cấu hình SMTP Host / From")

    msg = EmailMessage()
    msg["Subject"] = "Mã xác thực BTMH Security"
    msg["From"] = sender
    msg["To"] = _normalize_email(email)
    msg.set_content(
        "Mã xác thực đăng nhập BTMH Security của bạn là:\n\n"
        f"{code}\n\n"
        "Mã có hiệu lực trong 5 phút và chỉ dùng được một lần. "
        "Nếu bạn không thực hiện yêu cầu này, hãy bỏ qua email."
    )
    context = ssl.create_default_context()
    if use_ssl:
        client = smtplib.SMTP_SSL(host, port, timeout=12, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=12)
    try:
        client.ehlo()
        if not use_ssl and use_starttls:
            client.starttls(context=context)
            client.ehlo()
        if username:
            if not password:
                raise RuntimeError("SMTP có username nhưng chưa lưu mật khẩu")
            client.login(username, password)
        client.send_message(msg)
    finally:
        try:
            client.quit()
        except Exception:
            pass
    return {"provider": "SMTP", "delivered": True}

def request_otp_delivery(*, purpose: str, channel: str, destination: str, payload: dict | None = None) -> dict:
    ensure_otp_schema()
    method, normalized = _normalize_destination(channel, destination)
    digest = _dest_hash(purpose, method, normalized)
    now = datetime.now(timezone.utc)
    latest = fetchone("SELECT created_at FROM auth_otp_challenges WHERE destination_hash=? ORDER BY created_at DESC LIMIT 1", (digest,))
    if latest:
        elapsed = (now - _parse(latest.get("created_at") or utc_now())).total_seconds()
        if elapsed < OTP_RESEND_SECONDS:
            raise ValueError(f"Vui lòng chờ {max(1, int(OTP_RESEND_SECONDS-elapsed))} giây trước khi gửi lại OTP")
    hour_cutoff = (now - timedelta(hours=1)).isoformat()
    recent = fetchall("SELECT challenge_id FROM auth_otp_challenges WHERE destination_hash=? AND created_at>=?", (digest, hour_cutoff))
    if len(recent) >= OTP_MAX_PER_HOUR:
        raise ValueError("Đã gửi quá nhiều OTP. Vui lòng thử lại sau")

    challenge_id = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_bytes(16)
    now_iso = now.isoformat()
    expires = (now + timedelta(seconds=OTP_TTL_SECONDS)).isoformat()
    hint = _destination_hint(method, normalized)
    with connection() as conn:
        conn.execute(
            """INSERT INTO auth_otp_challenges(challenge_id,purpose,channel,destination_hash,destination_hint,otp_salt,otp_hash,expires_at,attempts,consumed,payload_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (challenge_id, str(purpose).upper(), method, digest, hint, base64.b64encode(salt).decode("ascii"), _hash_code(code, salt), expires, 0, 0, json.dumps(payload or {}, ensure_ascii=False), now_iso, now_iso),
        )
    try:
        delivery = _send_sms(normalized, code, str(purpose).upper()) if method == "SMS" else _send_email(normalized, code, str(purpose).upper())
    except Exception:
        with connection() as conn:
            conn.execute("UPDATE auth_otp_challenges SET consumed=1,updated_at=? WHERE challenge_id=?", (utc_now(), challenge_id))
        raise
    return {
        "challenge_id": challenge_id,
        "expires_in": OTP_TTL_SECONDS,
        "resend_after": OTP_RESEND_SECONDS,
        "channel": method,
        "destination_hint": hint,
        **delivery,
    }


def request_otp(*, purpose: str, phone: str, payload: dict | None = None) -> dict:
    """Backward-compatible SMS wrapper used by existing registration/reset flows."""
    out = request_otp_delivery(purpose=purpose, channel="SMS", destination=phone, payload=payload)
    out["phone_hint"] = out.get("destination_hint")
    return out


def verify_otp(*, challenge_id: str, otp: str, purpose: str) -> dict:
    ensure_otp_schema()
    row = fetchone("SELECT * FROM auth_otp_challenges WHERE challenge_id=?", (str(challenge_id),))
    if not row or int(row.get("consumed") or 0):
        raise ValueError("OTP không tồn tại hoặc đã được sử dụng")
    if str(row.get("purpose") or "").upper() != str(purpose).upper():
        raise ValueError("OTP không đúng mục đích xác minh")
    if _parse(row.get("expires_at") or utc_now()) <= datetime.now(timezone.utc):
        with connection() as conn:
            conn.execute("UPDATE auth_otp_challenges SET consumed=1,updated_at=? WHERE challenge_id=?", (utc_now(), str(challenge_id)))
        raise ValueError("OTP đã hết hạn")
    attempts = int(row.get("attempts") or 0) + 1
    with connection() as conn:
        conn.execute("UPDATE auth_otp_challenges SET attempts=?,updated_at=? WHERE challenge_id=?", (attempts, utc_now(), str(challenge_id)))
    if attempts > OTP_MAX_ATTEMPTS:
        with connection() as conn:
            conn.execute("UPDATE auth_otp_challenges SET consumed=1,updated_at=? WHERE challenge_id=?", (utc_now(), str(challenge_id)))
        raise ValueError("OTP đã bị khóa do nhập sai quá nhiều lần")
    try:
        salt = base64.b64decode(row.get("otp_salt") or "")
    except Exception:
        salt = b""
    expected = str(row.get("otp_hash") or "")
    actual = _hash_code(str(otp or "").strip(), salt) if salt else ""
    if not actual or not hmac.compare_digest(expected, actual):
        raise ValueError("Mã OTP không đúng")
    with connection() as conn:
        conn.execute("UPDATE auth_otp_challenges SET consumed=1,updated_at=? WHERE challenge_id=?", (utc_now(), str(challenge_id)))
    try:
        payload = json.loads(row.get("payload_json") or "{}")
    except Exception:
        payload = {}
    return {
        "ok": True,
        "payload": payload,
        "channel": str(row.get("channel") or "SMS").upper(),
        "destination_hint": str(row.get("destination_hint") or ""),
        "phone_hint": str(row.get("destination_hint") or ""),
    }
