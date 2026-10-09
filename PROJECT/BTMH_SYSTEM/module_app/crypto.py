from __future__ import annotations

import os
from cryptography.fernet import Fernet
from .config import KEY_PATH


def _load_key() -> bytes:
    env_key = os.getenv("FACE_DEMO_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8")
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes().strip()
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return key


FERNET = Fernet(_load_key())


def encrypt_bytes(data: bytes) -> bytes:
    return FERNET.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return FERNET.decrypt(data)
