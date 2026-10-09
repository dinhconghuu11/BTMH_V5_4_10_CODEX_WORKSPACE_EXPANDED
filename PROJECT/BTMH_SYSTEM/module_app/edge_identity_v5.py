from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from .config import CONFIG_DIR
from .secret_store import SecretStoreError, load_secret, save_secret

EDGE_PRIVATE_KEY_PATH = CONFIG_DIR / "edge_sync_private_key.dpapi"
EDGE_SIGNATURE_VERSION = "BTMH-EDGE-V1"
EDGE_CLOCK_SKEW_SECONDS = 300


class EdgeIdentityError(RuntimeError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        return b""
    raw += "=" * ((4 - len(raw) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(raw.encode("ascii"))
    except Exception as exc:
        raise EdgeIdentityError("Khóa thiết bị không hợp lệ") from exc


def generate_device_keypair() -> dict[str, str]:
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "private_key_b64": _b64(private_raw),
        "public_key_b64": _b64(public_raw),
        "fingerprint": hashlib.sha256(public_raw).hexdigest(),
    }




def public_from_private(private_key_b64: str) -> dict[str, str]:
    raw = _unb64(private_key_b64)
    if len(raw) != 32:
        raise EdgeIdentityError("Private key Edge không hợp lệ")
    public_raw = Ed25519PrivateKey.from_private_bytes(raw).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {"public_key_b64": _b64(public_raw), "fingerprint": hashlib.sha256(public_raw).hexdigest()}

def validate_public_key(public_key_b64: str) -> dict[str, str]:
    raw = _unb64(public_key_b64)
    if len(raw) != 32:
        raise EdgeIdentityError("Public key Edge phải là Ed25519 32-byte")
    try:
        Ed25519PublicKey.from_public_bytes(raw)
    except Exception as exc:
        raise EdgeIdentityError("Public key Edge không hợp lệ") from exc
    return {"public_key_b64": _b64(raw), "fingerprint": hashlib.sha256(raw).hexdigest()}


def save_edge_private_key(private_key_b64: str, path: Path = EDGE_PRIVATE_KEY_PATH) -> None:
    raw = _unb64(private_key_b64)
    if len(raw) != 32:
        raise EdgeIdentityError("Private key Edge phải là Ed25519 32-byte")
    if os.name != "nt":
        raise EdgeIdentityError("Private key production chỉ được lưu bằng Windows DPAPI; dùng BTMH_EDGE_PRIVATE_KEY_B64 cho test/dev")
    try:
        save_secret(path, _b64(raw), machine_scope=True)
    except SecretStoreError as exc:
        raise EdgeIdentityError(str(exc)) from exc


def load_edge_private_key(path: Path = EDGE_PRIVATE_KEY_PATH) -> str:
    env_value = str(os.getenv("BTMH_EDGE_PRIVATE_KEY_B64", "") or "").strip()
    try:
        value = load_secret(path, env_value)
    except SecretStoreError as exc:
        raise EdgeIdentityError(str(exc)) from exc
    raw = _unb64(value)
    if len(raw) != 32:
        raise EdgeIdentityError("Chưa cấu hình private key cho Edge node")
    return _b64(raw)


def canonical_request(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    body_hash = hashlib.sha256(body or b"").hexdigest()
    text = "\n".join(
        (
            EDGE_SIGNATURE_VERSION,
            str(method or "POST").upper(),
            str(path or "/"),
            str(timestamp or ""),
            str(nonce or ""),
            body_hash,
        )
    )
    return text.encode("utf-8")


def sign_request(private_key_b64: str, *, method: str, path: str, body: bytes, timestamp: int | None = None, nonce: str = "") -> dict[str, str]:
    raw = _unb64(private_key_b64)
    if len(raw) != 32:
        raise EdgeIdentityError("Private key Edge không hợp lệ")
    ts = str(int(timestamp if timestamp is not None else time.time()))
    nonce_value = str(nonce or secrets.token_urlsafe(18))
    message = canonical_request(method, path, ts, nonce_value, body)
    signature = Ed25519PrivateKey.from_private_bytes(raw).sign(message)
    return {
        "timestamp": ts,
        "nonce": nonce_value,
        "signature": _b64(signature),
    }


def verify_request_signature(public_key_b64: str, *, method: str, path: str, body: bytes, timestamp: str, nonce: str, signature: str) -> None:
    public_raw = _unb64(public_key_b64)
    signature_raw = _unb64(signature)
    if len(public_raw) != 32 or len(signature_raw) != 64:
        raise EdgeIdentityError("Chữ ký Edge không hợp lệ")
    message = canonical_request(method, path, str(timestamp), str(nonce), body)
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature_raw, message)
    except InvalidSignature as exc:
        raise EdgeIdentityError("Chữ ký Edge không hợp lệ") from exc


def validate_central_url(url: str, *, allow_http_dev: bool = False) -> str:
    value = str(url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise EdgeIdentityError("BTMH_CENTRAL_URL không hợp lệ")
    hostname = (parsed.hostname or "").lower()
    local = hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (local or allow_http_dev):
        raise EdgeIdentityError("Central Server production bắt buộc HTTPS")
    return value
