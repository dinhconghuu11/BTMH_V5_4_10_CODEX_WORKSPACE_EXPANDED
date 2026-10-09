from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from pathlib import Path


class SecretStoreError(RuntimeError):
    pass


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(data: bytes):
    buf = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    return blob, buf


def _blob_to_bytes(blob: DATA_BLOB) -> bytes:
    if not blob.pbData or not blob.cbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi_protect(data: bytes, *, machine_scope: bool = True) -> bytes:
    if os.name != "nt":
        raise SecretStoreError("Windows DPAPI is only available on Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    in_blob, _buf = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    flags = 0x01 | (0x04 if machine_scope else 0x00)  # UI_FORBIDDEN | LOCAL_MACHINE
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), "CampusFace PostgreSQL credential", None, None, None,
        flags, ctypes.byref(out_blob),
    )
    if not ok:
        raise SecretStoreError(f"CryptProtectData failed with WinError {ctypes.GetLastError()}")
    try:
        return _blob_to_bytes(out_blob)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretStoreError("Windows DPAPI is only available on Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    in_blob, _buf = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    description = wintypes.LPWSTR()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), ctypes.byref(description), None, None, None, 0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise SecretStoreError(f"CryptUnprotectData failed with WinError {ctypes.GetLastError()}")
    try:
        return _blob_to_bytes(out_blob)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))
        if description:
            kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))


def save_secret(path: Path, value: str, *, machine_scope: bool = False) -> None:
    if not value:
        raise SecretStoreError("Cannot store an empty secret")
    protected = _dpapi_protect(value.encode("utf-8"), machine_scope=machine_scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"DPAPI1:" + base64.b64encode(protected))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_secret(path: Path, env_value: str = "") -> str:
    if env_value:
        return env_value
    if not path.exists():
        return ""
    payload = path.read_bytes()
    if payload.startswith(b"DPAPI1:"):
        protected = base64.b64decode(payload.split(b":", 1)[1])
        return _dpapi_unprotect(protected).decode("utf-8")
    raise SecretStoreError("Unsupported PostgreSQL secret file format")
