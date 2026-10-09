"""Offline supported-runtime discovery shared by launchers and the gateway.

No candidate is executed to discover its version. Its bytes must match the
executable in the pinned upstream ZIP; VERSION.txt is only an extra check.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

VERSION = "1.21.1"
ARCHIVE_NAME = f"mediamtx_v{VERSION}_windows_amd64.zip"
ARCHIVE_SHA256 = "faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MediaMTXRuntime:
    binary: Path | None
    reason: str


def is_development() -> bool:
    # A missing/typo environment must retain the production requirement.
    return os.getenv("BTMH_ENV", "production").strip().lower() == "development"


def _signature(path: Path) -> tuple[str, int, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=32)
def _archive_executable_hash(signature: tuple[str, int, int, int]) -> str:
    try:
        with open(signature[0], "rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != ARCHIVE_SHA256:
                return ""
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                executables = [entry for entry in archive.infolist()
                               if not entry.is_dir() and
                               entry.filename.replace("\\", "/").split("/")[-1].lower() == "mediamtx.exe"]
                if len(executables) != 1:
                    return ""
                with archive.open(executables[0]) as executable:
                    return hashlib.file_digest(executable, "sha256").hexdigest()
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        return ""


@lru_cache(maxsize=32)
def _executable_hash(signature: tuple[str, int, int, int]) -> str:
    try:
        with open(signature[0], "rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return ""


def invalidate_verification_cache() -> None:
    # Windows ctime is creation time. An equal-size edit with restored mtime
    # must never reuse a cached digest at the boundary that executes code.
    _archive_executable_hash.cache_clear()
    _executable_hash.cache_clear()


def _supported(binary: Path, data_root: Path) -> bool:
    try:
        if not binary.is_file():
            return False
        marker = binary.parent / "VERSION.txt"
        if marker.exists() and marker.read_text(encoding="utf-8-sig").strip() != VERSION:
            return False
        actual = _executable_hash(_signature(binary))
        # Offline installs retain the verified ZIP alongside the binary. Older
        # online installs retain it in downloads; no Internet access is needed.
        archives = (binary.parent / ARCHIVE_NAME, data_root / "downloads" / ARCHIVE_NAME,
                    data_root / "runtime" / "mediamtx" / ARCHIVE_NAME)
        for archive in archives:
            if archive.is_file():
                expected = _archive_executable_hash(_signature(archive))
                if expected and actual == expected:
                    return True
    except (OSError, ValueError, UnicodeError):
        pass
    return False


def resolve_mediamtx(data_root: Path, project_root: Path | None = None) -> MediaMTXRuntime:
    data_root = Path(data_root)
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    candidates = [data_root / "runtime" / "mediamtx" / "mediamtx.exe"]
    for name in ("BTMH_MEDIAMTX_BIN", "BTMH_MEDIAMTX_BINARY"):
        configured = os.getenv(name, "").strip()
        if configured:
            candidates.append(Path(os.path.expandvars(os.path.expanduser(configured))))
    if is_development():
        candidates.extend(root / relative for relative in (
            "tools/mediamtx/mediamtx.exe", "tools/mediamtx.exe",
            "vendor/mediamtx/mediamtx.exe", "vendor/mediamtx.exe"))
    found = shutil.which("mediamtx.exe") or shutil.which("mediamtx")
    if found:
        candidates.append(Path(found))
    rejected = False
    seen: set[str] = set()
    for candidate in candidates:
        identity = str(candidate.absolute()).lower()
        if identity in seen:
            continue
        seen.add(identity)
        if _supported(candidate, data_root):
            return MediaMTXRuntime(candidate, "")
        if candidate.exists():
            rejected = True
    return MediaMTXRuntime(None, "MEDIAMTX_UNSUPPORTED_BINARY" if rejected else "MEDIAMTX_NOT_INSTALLED")


def require_mediamtx(data_root: Path) -> MediaMTXRuntime:
    invalidate_verification_cache()
    result = resolve_mediamtx(data_root)
    if result.binary is None and not is_development():
        raise RuntimeError(result.reason)
    return result
