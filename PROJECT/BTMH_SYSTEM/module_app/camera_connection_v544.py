"""Safe, structured editing of an existing RTSP camera connection."""
from __future__ import annotations
from urllib.parse import urlsplit, unquote, quote
from .capture_session_v544 import valid_source, display_source


def connection_view(row: dict) -> dict:
    source=str(row.get("source") or "")
    p=urlsplit(source)
    host=p.hostname or ""
    legacy_hint = (
        "Địa chỉ này là cấu hình mẫu cũ. Hãy nhập IP thực tế của camera trong mạng hiện tại."
        if host == "192.168.1.200" and "hikvision" in str(row.get("name") or "").lower()
        else ""
    )
    return {"id":row["id"],"name":row.get("name", "Camera"),"editable":p.scheme.lower()=="rtsp",
            "host":host, "port":p.port or 554,"path":(p.path or "/")+("?"+p.query if p.query else ""),
            "username":unquote(p.username or ""),"credential_saved":bool(p.password),
            "source_display":display_source(source),"updated_at":row.get("updated_at") or "",
            "legacy_host_warning":legacy_hint}


def update_connection_source(previous: str, host: str, port: int, path: str,
                             username: str | None = None, password: str | None = None) -> str:
    p=urlsplit(previous)
    if p.scheme.lower()!="rtsp":raise ValueError("Only RTSP cameras support this connection editor")
    host=str(host).strip().strip("[]")
    if not host or len(host)>253 or any(c in host for c in "/@?#\\ \t\r\n"):
        raise ValueError("Invalid host")
    if not 1<=int(port)<=65535:raise ValueError("Invalid port")
    path=str(path).strip()
    if not path.startswith("/") or "#" in path or any(ord(c)<32 or c==" " for c in path):
        raise ValueError("Invalid path")
    # None/blank means KEEP an already saved credential, never write *** back.
    user=unquote(p.username or "") if username in {None,""} else username
    secret=unquote(p.password or "") if password in {None,""} else password
    if len(user)>256 or len(secret)>1024:raise ValueError("Credential too long")
    auth=(quote(user,safe="")+":"+quote(secret,safe="")+"@") if user or secret else ""
    authority=f"[{host}]" if ":" in host else host
    return valid_source(f"rtsp://{auth}{authority}:{int(port)}{path}")
