from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .secret_store import load_secret, SecretStoreError


@dataclass(frozen=True)
class CameraProfile:
    name: str
    source_type: str
    url: str
    location: str = ""
    model: str = ""


def _encode_userinfo(value: str) -> str:
    return quote(unquote(str(value or "")), safe="")


def build_rtsp_url(ip: str, user: str, password: str, *, port: int = 554, channel: int | str = 101, stream: str | None = None) -> str:
    host = str(ip or "").strip()
    if not host:
        raise ValueError("Thiếu IP camera RTSP")
    username = quote(str(user or ""), safe="")
    secret = quote(str(password or ""), safe="")
    auth = f"{username}:{secret}@" if username or secret else ""
    path = str(stream or f"/Streaming/Channels/{channel}").strip()
    if not path.startswith("/"):
        path = "/" + path
    return f"rtsp://{auth}{host}:{int(port or 554)}{path}"


def normalize_camera_source(source: str) -> str:
    """Normalize RTSP credentials without changing USB indexes.

    User/password components are percent-encoded so passwords containing '@',
    ':', '#', '%' or spaces are parsed correctly by OpenCV/FFmpeg.
    """
    value = str(source or "").strip()
    if not value.lower().startswith("rtsp://"):
        return value
    prefix = value[:7]
    rest = value[7:]
    authority, separator, path = rest.partition("/")
    if "@" not in authority:
        return value
    userinfo, host = authority.rsplit("@", 1)
    host_and_path = host + separator + path
    if ":" in userinfo:
        username, password = userinfo.split(":", 1)
        userinfo = f"{_encode_userinfo(username)}:{_encode_userinfo(password)}"
    else:
        userinfo = _encode_userinfo(userinfo)
    return prefix + userinfo + "@" + host_and_path


def redact_camera_source(source: str) -> str:
    value = str(source or "").strip()
    if not value.lower().startswith("rtsp://"):
        return value
    authority, separator, path = value[7:].partition("/")
    if "@" not in authority:
        return value
    _, host = authority.rsplit("@", 1)
    return "rtsp://***:***@" + host + separator + path


def hikvision_ai_substream(source: str) -> str | None:
    """Derive a substream only from a recognized Hikvision channel path.

    The registry source stays unchanged. Encoded credentials, the operator's
    port, query arguments and channel number are preserved server-side.
    """
    value = normalize_camera_source(str(source or ""))
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "rtsp" or not parsed.hostname or parsed.fragment:
            return None
        match = re.fullmatch(r"(/Streaming/Channels/)([1-9][0-9]*)01(/?)", parsed.path, re.IGNORECASE)
        if not match:
            return None
        path = f"{match.group(1)}{match.group(2)}02{match.group(3)}"
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))
    except ValueError:
        return None


def hikvision(ip: str, user: str, password: str, channel: int = 101, name: str = "Hikvision IP Camera", *, port: int = 554, stream: str | None = None, model: str = "") -> CameraProfile:
    return CameraProfile(
        name=name,
        source_type="RTSP",
        url=build_rtsp_url(ip, user, password, port=port, channel=channel, stream=stream),
        location="IP Camera",
        model=model,
    )


def _data_root() -> Path:
    configured = os.getenv("CAMPUSFACE_DATA_ROOT", "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    if os.name == "nt":
        local = os.getenv("LOCALAPPDATA", "").strip()
        if local:
            return Path(local) / "CampusFace"
    return Path(__file__).resolve().parents[1] / ".campusface-data"


def hikvision_secret_path() -> Path:
    configured = os.getenv("CAMPUSFACE_HIKVISION_SECRET_FILE", "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    return _data_root() / "data" / "hikvision_cam01_password.dpapi"


def _local_profile_path() -> Path:
    configured = os.getenv("CAMPUSFACE_HIKVISION_PROFILE", "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    return _data_root() / "config" / "hikvision_camera.json"


def _profile_candidates() -> list[Path]:
    core_root = Path(__file__).resolve().parents[1]
    package_root = Path(__file__).resolve().parents[3]
    candidates: list[Path] = [_local_profile_path()]
    candidates.extend([
        core_root / "config" / "hikvision_test_camera.json",
        package_root / "config" / "hikvision_test_camera.json",
    ])
    # Keep order stable and avoid duplicates when CAMPUSFACE_HIKVISION_PROFILE
    # points into the packaged tree.
    seen: set[str] = set()
    out: list[Path] = []
    for item in candidates:
        key = str(item.resolve()) if item.exists() else str(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _stored_camera_password() -> str:
    try:
        return load_secret(hikvision_secret_path(), os.getenv("CAMPUSFACE_HIKVISION_PASSWORD", ""))
    except (SecretStoreError, OSError, ValueError):
        return os.getenv("CAMPUSFACE_HIKVISION_PASSWORD", "")


def load_hikvision_profile() -> CameraProfile | None:
    """Load a local Hikvision profile without bundling camera secrets.

    Non-secret defaults (model/IP/port/path/user) may ship with the project.
    The password is read from Windows DPAPI at runtime. This keeps the camera
    password out of source ZIPs, HTML, JavaScript and browser APIs.
    """
    ip = os.getenv("CAMPUSFACE_HIKVISION_IP", "").strip()
    user = os.getenv("CAMPUSFACE_HIKVISION_USERNAME", "").strip()
    password = _stored_camera_password()
    port = int(os.getenv("CAMPUSFACE_HIKVISION_RTSP_PORT", "554") or 554)
    stream = os.getenv("CAMPUSFACE_HIKVISION_STREAM", "/Streaming/Channels/101").strip()
    name = os.getenv("CAMPUSFACE_HIKVISION_NAME", "Hikvision Camera").strip() or "Hikvision Camera"
    model = os.getenv("CAMPUSFACE_HIKVISION_MODEL", "").strip()
    if ip and user and password:
        return hikvision(ip, user, password, name=name, port=port, stream=stream, model=model)

    for path in _profile_candidates():
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("example_only"):
                continue  # A shipped sample must not become a live camera profile.
            ip = str(raw.get("ip") or "").strip()
            user = str(raw.get("username") or raw.get("user") or "").strip()
            # Backward compatibility: an old local-only profile may still contain
            # a password, but release packages no longer do.
            password = str(raw.get("password") or "") or _stored_camera_password()
            if not ip or not user or not password:
                continue
            port = int(raw.get("rtsp_port") or 554)
            stream = str(raw.get("stream") or "/Streaming/Channels/101").strip()
            model = str(raw.get("model") or "").strip()
            configured_name = str(raw.get("name") or "").strip()
            if model and (not configured_name or "test camera" in configured_name.lower()):
                name = f"Hikvision {model}"
            else:
                name = configured_name or (f"Hikvision {model}" if model else "Hikvision Camera")
            return hikvision(ip, user, password, name=name, port=port, stream=stream, model=model)
        except Exception:
            continue
    return None
