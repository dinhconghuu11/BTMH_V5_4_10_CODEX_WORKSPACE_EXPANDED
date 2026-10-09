from __future__ import annotations

import base64
import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import EVENT_SNAPSHOTS_DIR, STUDENT_PHOTOS_DIR, STORE_SNAPSHOTS
from .db import execute, fetchall, fetchone, utc_now


def _student_dir(student_id: int) -> Path:
    path = STUDENT_PHOTOS_DIR / str(int(student_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _relative(path: Path) -> str:
    try:
        return path.relative_to(STUDENT_PHOTOS_DIR.parent.parent).as_posix()
    except Exception:
        return path.as_posix()


def _upsert_photo(student_id: int, photo_type: str, path: Path, data: bytes, *, conn=None) -> dict[str, Any]:
    now = utc_now()
    digest = hashlib.sha256(data).hexdigest()
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    select_sql = "SELECT id FROM student_photos WHERE student_id=? AND photo_type=?"
    params = (int(student_id), str(photo_type))
    existing = conn.execute(select_sql, params).fetchone() if conn is not None else fetchone(select_sql, params)
    if existing:
        (conn.execute if conn is not None else execute)(
            "UPDATE student_photos SET relative_path=?,mime_type=?,sha256=?,updated_at=? WHERE id=?",
            (_relative(path), mime, digest, now, int(existing["id"])),
        )
        row_id = int(existing["id"])
    else:
        insert_sql = "INSERT INTO student_photos(student_id,photo_type,relative_path,mime_type,sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?)"
        values = (int(student_id), str(photo_type), _relative(path), mime, digest, now, now)
        row_id = int(conn.execute(insert_sql + " RETURNING id", values).fetchone()["id"]) if conn is not None else execute(insert_sql, values)
    return {
        "id": row_id,
        "student_id": int(student_id),
        "photo_type": str(photo_type),
        "relative_path": _relative(path),
        "sha256": digest,
        "updated_at": now,
    }


def save_enrollment_photo(student_id: int, image: np.ndarray, *, conn=None) -> dict[str, Any] | None:
    """Persist one quality-selected portrait after FaceID enrollment.

    Raw scan frames remain transient. Only the best enrollment crop is stored for
    the human-readable student profile; biometric matching still uses SFace vectors.
    """
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        return None
    target_dir = _student_dir(student_id)
    path = target_dir / "enrollment_best.jpg"
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        return None
    data = buf.tobytes()
    path.write_bytes(data)
    # profile.jpg mirrors the selected enrollment portrait so UI code has a stable
    # filename. It can later be replaced by an explicitly uploaded portrait.
    profile = target_dir / "profile.jpg"
    profile.write_bytes(data)
    _upsert_photo(student_id, "ENROLLMENT_BEST", path, data, conn=conn)
    return _upsert_photo(student_id, "PROFILE", profile, data, conn=conn)


def student_photos(student_id: int) -> list[dict[str, Any]]:
    return fetchall(
        "SELECT id,student_id,photo_type,relative_path,mime_type,sha256,created_at,updated_at FROM student_photos WHERE student_id=? ORDER BY id",
        (int(student_id),),
    )


def photo_record(student_id: int, photo_type: str = "PROFILE") -> dict[str, Any] | None:
    return fetchone(
        "SELECT id,student_id,photo_type,relative_path,mime_type,sha256,created_at,updated_at FROM student_photos WHERE student_id=? AND photo_type=?",
        (int(student_id), str(photo_type).upper()),
    )


def photo_path(student_id: int, photo_type: str = "PROFILE") -> Path | None:
    rec = photo_record(student_id, photo_type)
    if not rec:
        return None
    rel = Path(str(rec.get("relative_path") or ""))
    # Current storage root layout is <DATA_ROOT>/Photos/Students/<id>/... . The DB
    # stores a path relative to DATA_ROOT, so derive the root from Students' parent.
    data_root = STUDENT_PHOTOS_DIR.parent.parent
    path = (data_root / rel).resolve()
    try:
        path.relative_to(data_root.resolve())
    except Exception:
        return None
    return path if path.exists() else None


def delete_student_media(student_id: int) -> None:
    sid = int(student_id)
    try:
        execute("DELETE FROM student_photos WHERE student_id=?", (sid,))
    except Exception:
        pass
    folder = STUDENT_PHOTOS_DIR / str(sid)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


def save_event_snapshot_data_url(event_id: int, data_url: str, status: str) -> str | None:
    """Optionally persist a recognition snapshot outside PostgreSQL.

    Snapshot storage is disabled by default. When enabled, PostgreSQL keeps event
    metadata while JPEG files live in the dedicated Snapshots tree.
    """
    if not STORE_SNAPSHOTS or not data_url or "," not in data_url:
        return None
    try:
        _header, payload = data_url.split(",", 1)
        data = base64.b64decode(payload, validate=False)
    except Exception:
        return None
    if not data:
        return None
    now = utc_now()
    day = now[:10]
    folder = EVENT_SNAPSHOTS_DIR / day
    folder.mkdir(parents=True, exist_ok=True)
    safe_status = "".join(c for c in str(status).upper() if c.isalnum() or c in "-_")[:32] or "EVENT"
    path = folder / f"{int(event_id)}_{safe_status}.jpg"
    path.write_bytes(data)
    return path.as_posix()
