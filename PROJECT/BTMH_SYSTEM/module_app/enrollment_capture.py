"""Bounded shared capture for reviewed desktop and QR FaceID enrollment.

Only the existing registry and multi-frame PAD engine decide sample validity.
Request authorization, consent scope and durable lifecycle belong to qr_enrollment.
This module never writes active templates or holds a store camera.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import struct
import threading
import time
import uuid

import cv2
import numpy as np

from .anti_spoof import ANTI_SPOOF
from .crypto import decrypt_bytes
from .registry import ENROLLMENT, INDEX
from .student_media import save_enrollment_photo

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 1920 * 1080
MAX_IMAGE_DIMENSION = 1920
MAX_ACTIVE_CAPTURES = 32
CAPTURE_TTL_SECONDS = 30 * 60
PAD_FRESH_SECONDS = 5.0
GUIDANCE_PHASES = ("CENTER", "LEFT", "RIGHT", "CENTER", "LIVENESS")
PAD_MESSAGES = {
    "PASS": "Đã xác minh người thật",
    "CHECKING": "Đang xác minh người thật",
    "BLOCKED": "Không thể xác minh người thật; bỏ ảnh, màn hình hoặc vật che khỏi camera",
    "MODEL_UNAVAILABLE": "Chưa thể xác minh người thật. Vui lòng liên hệ quản trị viên",
}


def _jpeg_dimensions(raw: bytes) -> tuple[int, int]:
    """Inspect SOF before decompression, rejecting oversized encoded uploads."""
    if len(raw) < 4 or raw[:2] != b"\xff\xd8":
        raise ValueError("Chỉ nhận ảnh JPEG camera")
    i = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    dimensions = None
    while i < len(raw):
        if raw[i] != 0xFF:
            raise ValueError("Ảnh JPEG không hợp lệ")
        while i < len(raw) and raw[i] == 0xFF:
            i += 1
        if i >= len(raw):
            break
        marker = raw[i]
        i += 1
        if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if marker in {0xD9, 0xDA}:
            break
        if i + 2 > len(raw):
            break
        size = struct.unpack_from(">H", raw, i)[0]
        if size < 2 or i + size > len(raw):
            raise ValueError("Ảnh JPEG không hợp lệ")
        if marker in sof:
            if dimensions is not None or size < 8:
                raise ValueError("Ảnh JPEG không hợp lệ")
            height, width = struct.unpack_from(">HH", raw, i + 3)
            _validate_dimensions(width, height)
            dimensions = (width, height)
        i += size
    if dimensions is None:
        raise ValueError("Ảnh JPEG không hợp lệ")
    return dimensions


def _validate_dimensions(width: int, height: int) -> None:
    # Portrait 1080x1920 is equivalent to landscape 1920x1080.
    if min(width, height) <= 0 or max(width, height) > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
        raise ValueError("Ảnh camera vượt giới hạn 1920×1080 pixel")


def decode_uploaded_frame(data_url: str):
    if not isinstance(data_url, str):
        raise ValueError("Ảnh camera không hợp lệ")
    prefix = "data:image/jpeg;base64,"
    if not data_url.startswith(prefix):
        raise ValueError("Chỉ nhận ảnh JPEG camera")
    encoded = data_url[len(prefix):]
    if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError("Ảnh camera vượt giới hạn 2 MiB")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Ảnh camera không hợp lệ") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Ảnh camera vượt giới hạn 2 MiB")
    expected = _jpeg_dimensions(raw)
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    _validate_image(image)
    if (image.shape[1], image.shape[0]) != expected:
        raise ValueError("Kích thước ảnh camera không hợp lệ")
    return image


def _validate_image(image) -> None:
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("Ảnh camera không hợp lệ")
    _validate_dimensions(image.shape[1], image.shape[0])


@dataclass
class _Capture:
    student_id: int
    created_at: float
    key: str
    lock: threading.Lock = field(default_factory=threading.Lock)
    active: bool = True
    phase: int = 0
    scan_pass: int = 1
    decision: dict = field(default_factory=dict)
    decision_at: float = 0.0
    verified_at: str | None = None
    ready: bool = False


class EnrollmentCapture:
    def __init__(self, *, enrollment=ENROLLMENT, pad=ANTI_SPOOF, clock=time.monotonic, utc_clock=None):
        self.enrollment = enrollment
        self.pad = pad
        self.clock = clock
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._captures: dict[str, _Capture] = {}
        self._retired: dict[str, float] = {}

    def _state(self, request_id: str, student_id: int) -> _Capture:
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("Phiên đăng ký không hợp lệ")
        now = self.clock()
        with self._lock:
            for key, state in list(self._captures.items()):
                if now - state.created_at >= CAPTURE_TTL_SECONDS:
                    self.retire_capture(key)
            self._retired = {key: stamp for key, stamp in self._retired.items() if now - stamp < CAPTURE_TTL_SECONDS}
            if request_id in self._retired:
                raise PermissionError("Phiên đăng ký đã kết thúc")
            state = self._captures.get(request_id)
            if state is None:
                if len(self._captures) >= MAX_ACTIVE_CAPTURES:
                    raise ValueError("Đang có quá nhiều phiên đăng ký; vui lòng thử lại")
                state = _Capture(int(student_id), now, "enrollment:" + uuid.uuid4().hex)
                self._captures[request_id] = state
            if state.student_id != int(student_id):
                raise PermissionError("Phiên đăng ký thuộc nhân viên khác")
            return state

    def _run_frame(self, request_id: str, student_id: int, image_factory) -> dict:
        state = self._state(request_id, student_id)
        if not state.lock.acquire(blocking=False):
            return {"ok": False, "accepted": False, "busy": True, "ready_to_finalize": False,
                    "message": "Đang xử lý ảnh trước"}
        try:
            if not state.active:
                raise PermissionError("Phiên đăng ký đã kết thúc")
            # Each attempt invalidates the prior PASS before decode/detect. A
            # missing face, invalid upload or failed model call cannot reuse it.
            state.decision = {}
            state.decision_at = 0.0
            state.verified_at = None
            state.ready = False
            image = image_factory()
            _validate_image(image)

            def gate(current_image, observation):
                decision = self.pad.update(state.key, current_image, observation)
                public = decision.public()
                status = str(decision.status)
                state.decision = {key: public[key] for key in ("score", "observations") if key in public}
                state.decision.update({"status": status if status in PAD_MESSAGES else "CHECKING",
                                       "reason": PAD_MESSAGES.get(status, PAD_MESSAGES["CHECKING"]),
                                       "source": "existing_passive_pad"})
                state.decision_at = self.clock()
                if decision.status == "PASS":
                    state.verified_at = self.utc_clock().astimezone(timezone.utc).isoformat()
                    return True
                return False

            response = self.enrollment.frame(state.key, student_id, image, sample_gate=gate)
            if not state.decision:
                # Zero/multiple faces interrupt this capture's temporal PAD
                # evidence. A later face must earn a new multi-frame PASS.
                self.pad.purge_prefix(state.key)
            # Detection failures contain a legacy display-only scan_pass=1;
            # they must not roll back a completed server scan/guidance sequence.
            pass_no = int(response.get("scan_pass") or state.scan_pass) if "captured" in response else state.scan_pass
            if pass_no != state.scan_pass:
                state.scan_pass = pass_no
                state.phase = 0
            pose = str(response.get("pose") or "").upper()
            registry_ready = bool(response.get("ready_to_finalize"))
            if (response.get("accepted") or registry_ready) and state.phase < 4 and pose == GUIDANCE_PHASES[state.phase]:
                state.phase += 1
            # Keep real two-pass coverage authoritative. The guidance sequence
            # never fabricates samples or omits the existing vertical coverage.
            state.ready = registry_ready and state.phase >= 4 and pose == "CENTER" and state.decision.get("status") == "PASS"
            if registry_ready and not state.ready:
                response["message"] = "Trở về chính diện để hoàn tất xác minh người thật"
            response.update({"capture_phase": "LIVENESS" if state.ready else GUIDANCE_PHASES[state.phase],
                             "capture_phase_index": state.phase, "guidance_phases": list(GUIDANCE_PHASES),
                             "pad": dict(state.decision), "ready_to_finalize": state.ready,
                             "capture_ready": state.ready})
            return response
        except Exception:
            state.decision = {}
            state.decision_at = 0.0
            state.verified_at = None
            state.ready = False
            self.pad.purge_prefix(state.key)
            raise
        finally:
            state.lock.release()

    def frame(self, request_id: str, student_id: int, image) -> dict:
        return self._run_frame(request_id, student_id, lambda: image)

    def frame_upload(self, request_id: str, student_id: int, data_url: str) -> dict:
        return self._run_frame(request_id, student_id, lambda: decode_uploaded_frame(data_url))

    def prepare(self, request_id: str, student_id: int):
        from .qr_enrollment import PreparedDraft
        with self._lock:
            state = self._captures.get(request_id)
        if state is None or state.student_id != int(student_id):
            raise ValueError("Chưa có phiên đăng ký FaceID")
        if not state.lock.acquire(blocking=False):
            raise ValueError("Đang xử lý ảnh trước")
        try:
            if not state.active or self.clock() - state.created_at >= CAPTURE_TTL_SECONDS:
                raise PermissionError("Phiên đăng ký đã kết thúc")
            if not state.ready or state.decision.get("status") != "PASS" or self.clock() - state.decision_at > PAD_FRESH_SECONDS:
                raise ValueError("Cần hoàn tất hai vòng quét và xác minh người thật hiện tại")
            material = self.enrollment.prepare_draft(state.key, student_id)
            return PreparedDraft(**material, pad={**state.decision, "verified_at": state.verified_at})
        finally:
            state.lock.release()

    def retire_capture(self, request_id: str) -> None:
        with self._lock:
            state = self._captures.pop(request_id, None)
            self._retired[request_id] = self.clock()
            if state is not None:
                state.active = False
        if state is not None:
            with state.lock:
                self.enrollment.reset(state.key)
                self.pad.purge_prefix(state.key)

    def reset_capture(self, request_id: str) -> None:
        # Reset transient evidence; the durable request expiry is never extended.
        with self._lock:
            old = self._captures.get(request_id)
            created_at = old.created_at if old is not None else None
            student_id = old.student_id if old is not None else None
        self.retire_capture(request_id)
        with self._lock:
            self._retired.pop(request_id, None)
            if created_at is not None:
                self._captures[request_id] = _Capture(student_id, created_at, "enrollment:" + uuid.uuid4().hex)


CAPTURE = EnrollmentCapture()


def refresh_active_index() -> None:
    INDEX.invalidate()
    INDEX.load(force=True)


def save_approved_preview(student_id: int, encrypted_blob: bytes | None, *, conn=None) -> bool:
    if not encrypted_blob:
        return False
    raw = decrypt_bytes(encrypted_blob)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Ảnh xem trước vượt giới hạn 2 MiB")
    _jpeg_dimensions(raw)
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    _validate_image(image)
    return bool(save_enrollment_photo(student_id, image, conn=conn))
