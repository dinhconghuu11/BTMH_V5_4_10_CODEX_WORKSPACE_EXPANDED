from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from contextlib import nullcontext
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from .config import (
    AI_TARGET_FPS,
    AI_WIDTH,
    AI_NATIVE_FRAME,
    AI_NATIVE_MAX_WIDTH,
    PERFORMANCE_GUARD_ENABLED,
    PERFORMANCE_GUARD_MIN_FPS,
    PERFORMANCE_GUARD_ADJUST_SEC,
    PERFORMANCE_GUARD_RECOVER_SEC,
    PERFORMANCE_GUARD_PTZ_HOLD_SEC,
    CAMERA_BACKEND,
    CAMERA_FAIL_LIMIT,
    CAMERA_FOURCC,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_MODE,
    CAMERA_PREVIEW_FPS,
    CAMERA_RECONNECT,
    CAMERA_SOURCE,
    CAMERA_WARMUP_FRAMES,
    CAMERA_WIDTH,
    CAMERA_AUTOFOCUS,
    CAMERA_AUTO_EXPOSURE,
    CAMERA_QUALITY_INTERVAL_SEC,
    CAMERA_SHARPNESS_WARN,
    CAMERA_SHARPNESS_GOOD,
    CAMERA_BRIGHTNESS_LOW,
    CAMERA_BRIGHTNESS_HIGH,
    CAMERA_CONTRAST_WARN,
    CAMERA_MODE_ACCEPT_RATIO,
    JPEG_QUALITY,
    OBSERVATION_FACE_AI_FPS,
    OBSERVATION_FACE_AI_WIDTH,
    OBSERVATION_PREVIEW_FPS,
    OBSERVATION_PREVIEW_WIDTH,
    OBSERVATION_JPEG_QUALITY,
    OBSERVATION_PREVIEW_ENHANCE,
    OBSERVATION_PREVIEW_SHARPEN,
    OBSERVATION_PREVIEW_CONTRAST,
    OBSERVATION_PREVIEW_BRIGHTNESS_TARGET,
    OBSERVATION_MAX_FACES,
    OBSERVATION_IDENTITY_BUDGET,
    RTSP_REALTIME_PROFILE,
    RTSP_CAPTURE_FPS,
    RTSP_CAPTURE_MAX_WIDTH,
    RTSP_AI_TARGET_FPS,
    RTSP_AI_WIDTH,
    RTSP_PREVIEW_FPS,
    RTSP_PREVIEW_WIDTH,
    RTSP_JPEG_QUALITY,
)
from .walkby import WALKBY
from .camera_profiles import normalize_camera_source
from .camera_handover_v544 import CameraHandoverV544Mixin
from .ai_capture_v550 import AICaptureLane
from . import config as cfg


def _set_current_thread_priority(*, above_normal: bool = False) -> bool:
    """Best-effort Windows scheduling hint for capture/preview threads.

    AI work can briefly saturate CPU cores. Giving camera I/O and browser-preview
    workers a small priority advantage keeps frames arriving/displaying smoothly
    without lowering camera FPS or changing FaceID thresholds.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentThread()
        # Win32 THREAD_PRIORITY_ABOVE_NORMAL = +1, NORMAL = 0.
        return bool(kernel32.SetThreadPriority(handle, 1 if above_normal else 0))
    except Exception:
        return False


@dataclass(frozen=True)
class CapturePlan:
    backend_name: str
    backend_code: int | None
    width: int
    height: int
    fps: int
    fourcc: str | None


class StaticCameraService(CameraHandoverV544Mixin):
    """Fault-tolerant local camera service.

    The camera, AI and preview each have a separate worker. The capture worker
    validates real frames before declaring the camera ONLINE, negotiates a safe
    Windows mode (preferred backend + MJPG + resolution fallback), and reconnects
    automatically after consecutive grab failures. The AI worker always consumes
    the newest frame so stale frames never build up in a queue.
    """

    def __init__(self, *, engine=None, session_id="service-camera") -> None:
        self._walkby = engine or WALKBY
        self._ai_session_id = str(session_id)
        self._pipeline_enabled = True
        self._event_context = {}
        self._appearance_owner = uuid.uuid4().hex
        self._business_consumer = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        # Every camera start receives a unique generation. This prevents a slow
        # RTSP/FFmpeg worker from a previous source from waking up after a handover
        # and publishing stale state/frames into the newly selected USB camera.
        self._run_generation = 0
        self._lock = threading.RLock()
        self._cap_lock = threading.RLock()
        self._cap = None
        # Remember the last capture mode that really worked for each physical
        # source. Integrated Windows webcams often advertise 1920x1080 but only
        # deliver stable frames at 1280x720. Reusing the proven mode makes a
        # Hikvision -> Laptop handover fast enough to avoid a false rollback.
        self._capture_plan_cache: dict[str, CapturePlan] = {}
        self._source_override: str | None = None
        self._source_label_override: str | None = None
        self._handover_lock = threading.Lock()
        self._ai_work_lock = threading.RLock()
        self._active_session = None
        self._pending_session = None
        self._source_epoch = 0
        self._ai_capture = AICaptureLane()
        self._ai_registered_source = ""
        self._retry_blocked_source = ""
        self._recognition_paused = False
        self._handover = {
            "active": False,
            "state": "IDLE",
            "from_source": "",
            "to_source": "",
            "from_label": "",
            "to_label": "",
            "message": "Sẵn sàng",
            "stable_frames": 0,
            "required_frames": 0,
            "rolled_back": False,
            "started_at": "",
            "finished_at": "",
        }
        self._frame: np.ndarray | None = None
        self._frame_seq = 0
        self._frame_at = 0.0
        self._jpeg = b""
        self._jpeg_seq = self._raw_jpeg_seq = 0
        self._jpeg_at = self._raw_jpeg_at = 0.0
        self._preview_requested_at = 0.0
        self._raw_jpeg = b""
        self._raw_requested_at = 0.0
        self._observation_jpeg = b""
        self._observation_jpeg_seq = 0
        self._observation_jpeg_at = 0.0
        self._observation_requested_at = 0.0
        self._observation_last_encoded_at = 0.0
        self._observation_mode = False
        self._enrollment_hold_until = 0.0
        self._result: dict = {"tracks": [], "events": [], "frame_width": 0, "frame_height": 0}
        self._last_event: dict | None = None
        self._recent_events = deque(maxlen=24)
        self._latencies = deque(maxlen=60)
        self._ai_result_at = 0.0
        self._ai_result_source_epoch = -1
        self._ai_error_source_epoch = -1
        # V13 realtime performance guard. The capture worker always publishes the
        # newest frame; AI is deliberately allowed to skip stale frames instead of
        # building a latency queue. The guard adjusts only inference cadence, never
        # the operator preview FPS.
        self._performance_last_adjust = 0.0
        self._performance_last_recover = 0.0
        self._performance_effective_fps = float(max(PERFORMANCE_GUARD_MIN_FPS, AI_TARGET_FPS))
        self._performance_reason = "Khởi tạo scheduler"
        self._performance_load_state = "NORMAL"
        self._capture_total = 0
        self._ai_total = 0
        self._ptz_guard_until = 0.0
        self._last_quality_at = 0.0
        # PTZ control state. USB PTZ devices are controlled through UVC/OpenCV
        # CAP_PROP_PAN/TILT/ZOOM when the Windows driver exposes them. If not,
        # CampusFace falls back to a digital crop so operators still have a
        # predictable local control surface without extra vendor software.
        self._ptz_state = {
            "mode": "digital",
            "pan": 0.0,
            "tilt": 0.0,
            "zoom": 1.0,
            "speed": 0.5,
            "hardware_supported": False,
            "last_action": "HOME",
            "message": "Digital PTZ sẵn sàng",
        }
        self._status = {
            "running": False,
            "opened": False,
            "state": "stopped",
            "error": "",
            "capture_fps": 0.0,
            "preview_fps": 0.0,
            "observation_preview_fps": 0.0,
            "observation_encode_ms": 0.0,
            "observation_jpeg_quality": int(OBSERVATION_JPEG_QUALITY),
            "preview_transport": "WEBSOCKET_ACK_BITMAP",
            "capture_priority_boosted": False,
            "preview_priority_boosted": False,
            "rtsp_hwaccel_requested": False,
            "observation_mode": False,
            "ai_fps": 0.0,
            "ai_error_code": "",
            "ai_successful_results_current_source": 0,
            "last_ai_ms": 0.0,
            "avg_ai_ms": 0.0,
            "p95_ai_ms": 0.0,
            "latest_seq": 0,
            "ai_seq": 0,
            "dropped_for_ai": 0,
            "performance_guard_enabled": bool(PERFORMANCE_GUARD_ENABLED),
            "ai_scheduler_mode": "ADAPTIVE_LATEST_FRAME" if PERFORMANCE_GUARD_ENABLED else "FIXED_LATEST_FRAME",
            "ai_target_fps_base": float(AI_TARGET_FPS),
            "ai_target_fps_effective": float(AI_TARGET_FPS),
            "ai_min_fps": int(PERFORMANCE_GUARD_MIN_FPS),
            "ai_load_state": "NORMAL",
            "ai_lane": "FACEID_NATIVE",
            "ai_drop_ratio": 0.0,
            "frame_policy": "LATEST_FRAME_DROP_STALE",
            "ptz_guard_active": False,
            "ptz_guard_remaining_ms": 0,
            "visible_tracks": 0,
            "visible_faces": 0,
            "source": str(CAMERA_SOURCE),
            "source_label": "Camera laptop" if str(CAMERA_SOURCE) == "0" else ("Camera PTZ" if str(CAMERA_SOURCE) == "1" else str(CAMERA_SOURCE)),
            "recognition_paused": False,
            "handover_active": False,
            "handover_state": "IDLE",
            "backend": "",
            "fourcc": "",
            "actual_width": 0,
            "actual_height": 0,
            "requested_width": int(CAMERA_WIDTH),
            "requested_height": int(CAMERA_HEIGHT),
            "requested_fps": int(CAMERA_FPS),
            "native_ai_enabled": bool(AI_NATIVE_FRAME),
            "ai_input_width": 0,
            "ai_input_height": 0,
            "autofocus_requested": bool(CAMERA_AUTOFOCUS),
            "auto_exposure_requested": bool(CAMERA_AUTO_EXPOSURE),
            "autofocus_active": None,
            "auto_exposure_value": None,
            "resolution_fallback": False,
            "camera_quality": "UNKNOWN",
            "quality_warning": "",
            "sharpness_score": 0.0,
            "brightness": 0.0,
            "contrast": 0.0,
            "reconnect_count": 0,
            "last_frame_age_ms": None,
            "capture_owner": "CAPTURE_THREAD_ONLY",
            "safe_decoder_shutdown": True,
            "realtime_profile": "usb",
            "decoder_output_fps": 0.0,
            "decoder_max_width": 0,
            "preview_target_fps": int(CAMERA_PREVIEW_FPS),
            "preview_target_width": int(CAMERA_WIDTH),
            "preview_jpeg_quality_effective": int(JPEG_QUALITY),
            "ai_target_width_effective": int(AI_WIDTH),
            "pipeline_backlog": 0,
        }
        self._set_placeholder("CAMERA READY")

    def _run_is_active(self, generation: int | None) -> bool:
        if generation is None:
            return not self._stop.is_set()
        with self._lock:
            current = int(self._run_generation)
        return generation == current and not self._stop.is_set()

    @staticmethod
    def _default_source_label(source: str) -> str:
        value = str(source or "0").strip()
        if value == "0":
            return "Camera laptop"
        if value == "1":
            return "Camera PTZ"
        if value.lower().startswith("rtsp://"):
            return "Camera RTSP"
        return value or "Camera"

    def event_camera_source(self) -> str:
        with self._lock:
            source = str(self._status.get("source") or self._source_override or CAMERA_SOURCE)
            label = str(self._source_label_override or self._status.get("source_label") or "").strip()
        return label or self._default_source_label(source)

    def set_source_label(self, label: str | None) -> None:
        with self._lock:
            source = str(self._status.get("source") or self._source_override or CAMERA_SOURCE)
            clean = str(label or "").strip()
            self._source_label_override = clean or None
            self._status["source_label"] = clean or self._default_source_label(source)

    def configure_source(self, source: str, source_label: str | None = None) -> None:
        """Configure the source used by the next capture start.

        This is used during application startup and migrations before worker
        threads are running. Runtime switching continues to use safe_select_source.
        """
        value = normalize_camera_source(str(source or "0").strip() or "0")
        label = str(source_label or "").strip() or self._default_source_label(value)
        with self._lock:
            self._source_override = value
            self._source_label_override = label
            self._status["source"] = value
            self._status["source_label"] = label

    def configure_ai_source(self, registry_source: str | None) -> None:
        """Bind the AI lane to the active, enabled DB camera only.

        Call after source resolution/commit. Never persist the derived /102 URL
        or expose it through status, and never switch the main camera here.
        """
        with self._lock:
            current = normalize_camera_source(self.current_source_identity())
            registered = normalize_camera_source(str(registry_source or ""))
            self._ai_registered_source = registered if registered == current else ""
            epoch = self._source_epoch
        self._ai_capture.configure(current, epoch, registered=bool(self._ai_registered_source))

    def configure_ai_pipeline(self, context, *, enabled, consumer=None):
        """Supervisor-owned state; stopping a browser preview never calls this."""
        values = dict(context or {})
        session_id = f"camera-{int(values['camera_id'])}" if values.get("camera_id") else self._ai_session_id
        with self._ai_work_lock:
            changed = (values != self._event_context or bool(enabled) != self._pipeline_enabled
                       or session_id != self._ai_session_id)
            if changed:
                self._walkby.reset(self._ai_session_id)
                self._appearance_owner = uuid.uuid4().hex
                with self._lock:
                    self._result = {"tracks": [], "events": [], "face_count": 0, "updated_at": time.time()}
                    self._ai_result_at = 0.0
                    self._ai_result_source_epoch = self._ai_error_source_epoch = -1
                    self._status["ai_error_code"] = ""
                    self._status["ai_successful_results_current_source"] = 0
            self._ai_session_id = session_id
            self._event_context = values
            self._pipeline_enabled = bool(enabled)
            self._business_consumer = consumer if enabled else None
            if enabled:
                from .ai_camera_runtime import MAX_ACTIVE_TRACKS, budgeted_inference
                self._walkby.configure_resource_limits(MAX_ACTIVE_TRACKS, budgeted_inference)

    def refresh_ai_metadata(self, context):
        """Publish names between frames without resetting engine/session/appearance."""
        from .ai_camera_runtime import processing_context
        values = dict(context or {})
        with self._ai_work_lock:
            if processing_context(values) != processing_context(self._event_context):
                raise ValueError("AI_METADATA_BEHAVIOR_CHANGED")
            self._event_context = values
            self.set_source_label(values.get("camera_name"))

    def _sync_ai_capture_epoch(self) -> None:
        with self._lock:
            current = normalize_camera_source(self.current_source_identity())
            registered = bool(current and current == self._ai_registered_source)
            epoch = self._source_epoch
        self._ai_capture.configure(current, epoch, registered=registered)

    def media_source_context(self) -> tuple[str, int]:
        with self._lock:
            return normalize_camera_source(self.current_source_identity()), self._source_epoch

    def validated_ai_substream_source(self) -> str:
        """Internal only: a current decoded /102 proof, never a browser payload."""
        from .camera_profiles import hikvision_ai_substream
        with self._lock:
            current, epoch = self.media_source_context()
            if not current or current != self._ai_registered_source:
                return ""
            if self._ai_capture.snapshot(epoch) is None:
                return ""
            return hikvision_ai_substream(current) or ""

    def _ai_input_packet(self):
        """Choose a proven fresh substream packet, otherwise current main frame."""
        with self._lock:
            epoch = self._source_epoch
            packet = self._ai_capture.snapshot(epoch)
            if packet is not None:
                return self._apply_digital_ptz(packet.frame.copy()), packet.seq, packet.at, epoch, "HIKVISION_SUBSTREAM"
            seq, captured_at = self._frame_seq, self._frame_at
            online = self._status.get("state") == "online"
            fresh = bool(online and captured_at and 0.0 <= time.perf_counter() - captured_at <= 1.3)
            main = self._frame.copy() if fresh and self._frame is not None else None
        return main, seq, captured_at, epoch, "MAIN_FALLBACK"

    def _ai_evidence_provider(self, *, source_epoch, capture_at, image, observation, **_):
        """Confirm a fresh main-frame face before producing a sharper evidence crop.

        A substream bbox is only an ROI proposal. A main-frame detector must
        confirm one unambiguous spatial match; stale, mismatched geometry or
        handover frames are rejected rather than blindly scaling the crop.
        """
        from .face_core import CORE
        with self._lock:
            if int(source_epoch) != self._source_epoch or self._frame is None:
                return None
            main = self._frame.copy()
            main_at = float(self._frame_at)
        now = time.perf_counter()
        if (not capture_at or abs(main_at - float(capture_at)) > cfg.AI_EVIDENCE_SYNC_SEC
                or not 0.0 <= now - main_at <= 0.5):
            return None
        ih, iw = image.shape[:2]
        mh, mw = main.shape[:2]
        if mw <= iw or abs((mw / mh) / (iw / ih) - 1.0) > 0.025:
            return None
        x, y, w, h = observation.bbox
        sx, sy = mw / float(iw), mh / float(ih)
        proposed = (int(x * sx), int(y * sy), int(w * sx), int(h * sy))
        px, py, pw, ph = proposed
        margin = int(max(pw, ph) * 0.45)
        x1, y1 = max(0, px - margin), max(0, py - margin)
        x2, y2 = min(mw, px + pw + margin), min(mh, py + ph + margin)
        roi = main[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        try:
            faces = CORE.detect(roi, long_range=False, use_custom=False)
            confirmed = []
            for face in faces:
                translated = CORE._translate_face(face, x1, y1)
                candidate = CORE.observe(main, translated, with_embedding=False)
                if CORE.iou(candidate.bbox, proposed) >= 0.60:
                    confirmed.append(candidate)
            if len(confirmed) != 1:
                return None
            with self._lock:
                if int(source_epoch) != self._source_epoch:
                    return None
            return {"image": main, "observation": confirmed[0]}
        except Exception:
            return None

    def _source_value(self):
        value = str(self._source_override if self._source_override is not None else CAMERA_SOURCE).strip()
        value = normalize_camera_source(value)
        return int(value) if value.isdigit() else value

    @staticmethod
    def _is_network_source(source) -> bool:
        return isinstance(source, str) and source.lower().startswith(("rtsp://", "http://", "https://"))

    @classmethod
    def _backend_options(cls, source) -> list[tuple[str, int | None]]:
        if cls._is_network_source(source):
            options: list[tuple[str, int | None]] = []
            if hasattr(cv2, "CAP_FFMPEG"):
                options.append(("ffmpeg", cv2.CAP_FFMPEG))
            options.append(("auto", None))
            return options
        if not (isinstance(source, int) and os.name == "nt"):
            return [("auto", None)]
        preferred = str(CAMERA_BACKEND or "auto").strip().lower()
        raw: list[tuple[str, int | None]] = []
        if preferred in {"auto", "dshow"} and hasattr(cv2, "CAP_DSHOW"):
            raw.append(("dshow", cv2.CAP_DSHOW))
        if preferred in {"auto", "msmf"} and hasattr(cv2, "CAP_MSMF"):
            raw.append(("msmf", cv2.CAP_MSMF))
        # If a forced backend fails, try the other Windows backend before giving up.
        if preferred == "dshow" and hasattr(cv2, "CAP_MSMF"):
            raw.append(("msmf", cv2.CAP_MSMF))
        if preferred == "msmf" and hasattr(cv2, "CAP_DSHOW"):
            raw.append(("dshow", cv2.CAP_DSHOW))
        raw.append(("auto", None))
        out: list[tuple[str, int | None]] = []
        seen: set[str] = set()
        for item in raw:
            if item[0] not in seen:
                out.append(item)
                seen.add(item[0])
        return out

    @staticmethod
    def _resolution_options() -> list[tuple[int, int]]:
        requested = (max(160, int(CAMERA_WIDTH)), max(120, int(CAMERA_HEIGHT)))
        candidates = [requested]
        # 1280x720 and 640x480 are the two safest USB webcam fallbacks on Windows.
        if requested[0] > 1280 or requested[1] > 720:
            candidates.append((1280, 720))
        if requested[0] > 640 or requested[1] > 480:
            candidates.append((640, 480))
        out: list[tuple[int, int]] = []
        seen = set()
        for mode in candidates:
            if mode not in seen:
                out.append(mode)
                seen.add(mode)
        return out

    @classmethod
    def capture_plans(cls, source) -> list[CapturePlan]:
        plans: list[CapturePlan] = []
        resolutions = [(max(160, int(CAMERA_WIDTH)), max(120, int(CAMERA_HEIGHT)))] if cls._is_network_source(source) else cls._resolution_options()
        for backend_name, backend_code in cls._backend_options(source):
            for width, height in resolutions:
                # DirectShow + MJPG is usually the most stable 720p/30 mode.
                # MSMF/AUTO are tested with their native pixel format first because
                # some Windows drivers reject an explicit MJPG request under MSMF.
                if isinstance(source, int) and os.name == "nt" and backend_name == "dshow":
                    fourccs = ["MJPG", None]
                elif isinstance(source, int) and os.name == "nt":
                    fourccs = [None]
                else:
                    fourccs = [None]
                preferred = str(CAMERA_FOURCC or "auto").strip().upper()
                if preferred and preferred != "AUTO":
                    fourccs = [preferred, None] if preferred not in {None, ""} else [None]
                for fourcc in fourccs:
                    plans.append(
                        CapturePlan(
                            backend_name=backend_name,
                            backend_code=backend_code,
                            width=width,
                            height=height,
                            fps=max(1, int(CAMERA_FPS)),
                            fourcc=fourcc,
                        )
                    )
        return plans


    @classmethod
    def _configure_capture(cls, cap, plan: CapturePlan, source=None) -> None:
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if cls._is_network_source(source):
            # RTSP stream geometry/FPS is controlled by the camera encoder. Do not
            # apply UVC-only exposure/autofocus or force USB capture modes.
            return
        if plan.fourcc:
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*plan.fourcc[:4]))
            except Exception:
                pass
        try:
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 1)
        except Exception:
            pass
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, plan.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, plan.height)
        cap.set(cv2.CAP_PROP_FPS, plan.fps)
        # Best-effort camera quality controls. Drivers that do not expose these
        # properties simply ignore them. DirectShow typically accepts 0.75 for
        # automatic exposure; autofocus is usually a boolean 0/1 property.
        if CAMERA_AUTOFOCUS and hasattr(cv2, "CAP_PROP_AUTOFOCUS"):
            try:
                cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            except Exception:
                pass
        if CAMERA_AUTO_EXPOSURE and hasattr(cv2, "CAP_PROP_AUTO_EXPOSURE"):
            try:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            except Exception:
                pass

    @staticmethod
    def _valid_frame(frame: np.ndarray | None) -> bool:
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim < 2:
            return False
        h, w = frame.shape[:2]
        if h < 64 or w < 64 or frame.size == 0:
            return False
        # Reject obvious corrupt/empty frames, while still allowing very dark rooms.
        sample = frame[:: max(1, h // 90), :: max(1, w // 120)]
        mean = float(np.mean(sample))
        std = float(np.std(sample))
        if std < 0.25 and (mean < 1.0 or mean > 254.0):
            return False
        return True

    @staticmethod
    def _fourcc_text(value: float | int) -> str:
        try:
            code = int(value)
            text = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
            text = "".join(c for c in text if 32 <= ord(c) <= 126).strip()
            return text or "default"
        except Exception:
            return "default"

    @staticmethod
    def _mode_matches_plan(actual_w: int, actual_h: int, plan: CapturePlan) -> bool:
        # Windows drivers sometimes report OPEN while silently ignoring a requested
        # resolution. Reject that pseudo-success so the next explicit fallback plan
        # is tried and status reflects the mode that is really in use.
        wr = float(actual_w) / max(1.0, float(plan.width))
        hr = float(actual_h) / max(1.0, float(plan.height))
        return min(wr, hr) >= float(CAMERA_MODE_ACCEPT_RATIO)

    @staticmethod
    def _quality_metrics(frame: np.ndarray) -> dict:
        if frame is None or frame.size == 0:
            return {"camera_quality": "UNKNOWN", "quality_warning": "Chưa có frame", "sharpness_score": 0.0, "brightness": 0.0, "contrast": 0.0}
        h, w = frame.shape[:2]
        if w > 640:
            scale = 640.0 / float(w)
            work = cv2.resize(frame, (640, max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA)
        else:
            work = frame
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY) if work.ndim == 3 else work
        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        warnings: list[str] = []
        if brightness < CAMERA_BRIGHTNESS_LOW:
            warnings.append("Thiếu sáng")
        elif brightness > CAMERA_BRIGHTNESS_HIGH:
            warnings.append("Quá sáng")
        if contrast < CAMERA_CONTRAST_WARN:
            warnings.append("Tương phản thấp")
        if sharpness < CAMERA_SHARPNESS_WARN:
            warnings.append("Hình mờ")
        if warnings:
            state = "POOR"
        elif sharpness < CAMERA_SHARPNESS_GOOD:
            state = "FAIR"
        else:
            state = "GOOD"
        return {
            "camera_quality": state,
            "quality_warning": " · ".join(warnings),
            "sharpness_score": round(sharpness, 1),
            "brightness": round(brightness, 1),
            "contrast": round(contrast, 1),
        }

    def _update_quality(self, frame: np.ndarray, now: float) -> None:
        if now - self._last_quality_at < CAMERA_QUALITY_INTERVAL_SEC:
            return
        self._last_quality_at = now
        metrics = self._quality_metrics(frame)
        with self._lock:
            self._status.update(metrics)

    def _warmup(self, cap, *, timeout_sec: float = 0.9) -> np.ndarray | None:
        required_good = 2
        good = 0
        last = None
        # Do not cap webcam warm-up to only a handful of read() calls. After an
        # RTSP/FFmpeg source is retired, Windows UVC/DirectShow can need 1-2s
        # before the integrated camera starts returning real frames.
        deadline = time.perf_counter() + max(0.9, float(timeout_sec))
        attempts = max(18, int(CAMERA_WARMUP_FRAMES) * 4)
        for _ in range(attempts):
            if self._stop.is_set() or time.perf_counter() > deadline:
                break
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None
            if ok and self._valid_frame(frame):
                last = frame
                good += 1
                if good >= required_good:
                    return last
            else:
                good = 0
            time.sleep(0.02)
        return None

    def _set_state(self, state: str, *, opened: bool | None = None, error: str | None = None) -> None:
        with self._lock:
            self._status["state"] = state
            if opened is not None:
                self._status["opened"] = bool(opened)
            if error is not None:
                self._status["error"] = error

    def _set_placeholder(self, text: str) -> None:
        canvas = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(canvas, text, (36, 174), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (205, 220, 230), 2, cv2.LINE_AA)
        cv2.putText(canvas, "BAO TIN MANH HAI", (36, 214), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (120, 150, 170), 1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
        if ok:
            data = buf.tobytes()
            with self._lock:
                self._jpeg = data
                self._raw_jpeg = data

    def _release_capture(self) -> None:
        with self._cap_lock:
            cap = self._cap
            self._cap = None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def _release_owned_capture(self, cap) -> None:
        # A retired handover worker must never release the VideoCapture owned by
        # the new generation. Only clear self._cap when it is the exact object.
        if cap is None:
            return
        with self._cap_lock:
            if self._cap is cap:
                self._cap = None
        try:
            cap.release()
        except Exception:
            pass




    @staticmethod
    def _enhance_observation_preview(frame: np.ndarray) -> np.ndarray:
        """Crisp browser-only observation preview; AI still receives the raw frame.

        The V5 path keeps native camera pixels whenever possible, then applies a
        conservative luminance/contrast correction and unsharp mask only to the
        JPEG shown in the browser. This avoids biometric drift and keeps FaceID,
        PAD and FaceID geometry untouched.
        """
        if frame is None or frame.size == 0 or not OBSERVATION_PREVIEW_ENHANCE:
            return frame
        work = frame
        # Estimate brightness on a sparse sample to keep 1080p preview processing cheap.
        sample = work[::6, ::6]
        try:
            gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY) if sample.ndim == 3 else sample
            mean = float(np.mean(gray))
        except Exception:
            mean = OBSERVATION_PREVIEW_BRIGHTNESS_TARGET
        beta = float(np.clip((OBSERVATION_PREVIEW_BRIGHTNESS_TARGET - mean) * 0.14, -7.0, 10.0))
        if abs(OBSERVATION_PREVIEW_CONTRAST - 1.0) > 0.001 or abs(beta) > 0.1:
            work = cv2.convertScaleAbs(work, alpha=OBSERVATION_PREVIEW_CONTRAST, beta=beta)
        amount = float(OBSERVATION_PREVIEW_SHARPEN)
        if amount > 0.001:
            # V2.7 replaces a full-frame Gaussian blur + blend with one small 3x3
            # convolution. At 1080p/25 FPS this saves substantial CPU while keeping
            # the same mild edge crispness for the browser preview.
            a = max(0.01, min(0.14, amount * 0.38))
            kernel = np.asarray([[0.0, -a, 0.0], [-a, 1.0 + 4.0 * a, -a], [0.0, -a, 0.0]], dtype=np.float32)
            work = cv2.filter2D(work, -1, kernel)
        return work

    @staticmethod
    def _enhance_enrollment_preview(frame: np.ndarray) -> np.ndarray:
        """Improve the FaceID enrollment preview without altering AI input frames.

        The camera/recognition pipeline keeps the untouched capture frame for
        embeddings and PAD. Only the enrollment JPEG shown in the browser receives
        a conservative local-contrast + unsharp-mask pass. This makes laptop/USB
        webcam previews look crisper while avoiding biometric drift.
        """
        if frame is None or frame.size == 0:
            return frame
        # Mild luminance-only CLAHE keeps skin colour stable under indoor lighting.
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=1.35, tileGridSize=(8, 8))
        l_chan = clahe.apply(l_chan)
        enhanced = cv2.cvtColor(cv2.merge((l_chan, a_chan, b_chan)), cv2.COLOR_LAB2BGR)
        blur = cv2.GaussianBlur(enhanced, (0, 0), 0.9)
        return cv2.addWeighted(enhanced, 1.16, blur, -0.16, 0)

    def _publish_frame(self, frame: np.ndarray, now: float) -> None:
        frame = self._apply_digital_ptz(frame)
        with self._lock:
            self._capture_total += 1
            self._frame = frame
            self._frame_seq += 1
            self._frame_at = now
            self._status["latest_seq"] = self._frame_seq
            self._status["opened"] = True
            self._status["state"] = "online"
            self._status["error"] = ""
            self._status["actual_width"] = int(frame.shape[1])
            self._status["actual_height"] = int(frame.shape[0])
            self._status["last_frame_age_ms"] = 0.0



    @staticmethod
    def _resize_for_ai(frame: np.ndarray, target_width: int | None = None) -> np.ndarray:
        h, w = frame.shape[:2]
        width = int(target_width or AI_WIDTH)
        if w <= width:
            return frame.copy()
        scale = width / float(w)
        return cv2.resize(frame, (width, max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA)

    def _performance_target_fps(self, base_target: int, now: float) -> float:
        """Adapt AI cadence to measured latency without slowing the live preview."""
        base = float(max(PERFORMANCE_GUARD_MIN_FPS, int(base_target)))
        if not PERFORMANCE_GUARD_ENABLED:
            self._performance_effective_fps = base
            self._performance_load_state = "FIXED"
            self._performance_reason = "Performance Guard tắt"
            return base
        current = float(min(base, max(PERFORMANCE_GUARD_MIN_FPS, self._performance_effective_fps)))
        with self._lock:
            arr = np.asarray(self._latencies, dtype=np.float32) if self._latencies else None
            latest_seq = max(1, int(self._frame_seq))
            dropped = max(0, int(self._status.get("dropped_for_ai") or 0))
        avg_ms = float(arr.mean()) if arr is not None and arr.size else 0.0
        p95_ms = float(np.percentile(arr, 95)) if arr is not None and arr.size else 0.0
        budget_ms = 1000.0 / max(1.0, current)
        drop_ratio = min(1.0, dropped / float(latest_seq))
        overloaded = (p95_ms > budget_ms * 1.30) or (avg_ms > budget_ms * 1.08)
        severe = (p95_ms > budget_ms * 1.85) or (avg_ms > budget_ms * 1.55)
        can_adjust = (now - self._performance_last_adjust) >= PERFORMANCE_GUARD_ADJUST_SEC
        if can_adjust and overloaded and current > PERFORMANCE_GUARD_MIN_FPS:
            step = 2.0 if severe else 1.0
            current = max(float(PERFORMANCE_GUARD_MIN_FPS), current - step)
            self._performance_last_adjust = now
            self._performance_last_recover = now
            self._performance_load_state = "HIGH" if severe else "BUSY"
            self._performance_reason = f"Giảm AI FPS để giữ realtime · p95 {p95_ms:.0f} ms"
        elif current < base and not overloaded and (now - self._performance_last_recover) >= PERFORMANCE_GUARD_RECOVER_SEC:
            current = min(base, current + 1.0)
            self._performance_last_adjust = now
            self._performance_last_recover = now
            self._performance_load_state = "RECOVERING" if current < base else "NORMAL"
            self._performance_reason = "Tăng dần AI FPS sau khi tải ổn định"
        elif not overloaded and current >= base:
            self._performance_load_state = "NORMAL"
            self._performance_reason = "Realtime ổn định"
        self._performance_effective_fps = current
        with self._lock:
            self._status["ai_target_fps_base"] = round(base, 1)
            self._status["ai_target_fps_effective"] = round(current, 1)
            self._status["ai_load_state"] = self._performance_load_state
            self._status["ai_drop_ratio"] = round(drop_ratio, 4)
        return current

    def performance_status(self) -> dict:
        with self._lock:
            latest_seq = max(1, int(self._frame_seq))
            dropped = max(0, int(self._status.get("dropped_for_ai") or 0))
            tracks = len((self._result or {}).get("tracks") or [])
            faces = int((self._result or {}).get("face_count") or tracks)
            now = time.perf_counter()
            ptz_remaining = max(0.0, self._ptz_guard_until - now)
            preview_at = float(self._observation_jpeg_at or self._frame_at or 0.0)
            ai_at = float(self._ai_result_at or 0.0) if self._ai_result_source_epoch == self._source_epoch else 0.0
            preview_age_ms = max(0.0, (now - preview_at) * 1000.0) if preview_at > 0 else None
            tracking_age_ms = max(0.0, (now - ai_at) * 1000.0) if ai_at > 0 else None
            return {
                "enabled": bool(PERFORMANCE_GUARD_ENABLED),
                "scheduler": str(self._status.get("ai_scheduler_mode") or "ADAPTIVE_LATEST_FRAME"),
                "frame_policy": "LATEST_FRAME_DROP_STALE",
                "base_target_fps": round(float(self._status.get("ai_target_fps_base") or AI_TARGET_FPS), 1),
                "effective_target_fps": round(float(self._performance_effective_fps), 1),
                "actual_ai_fps": round(float(self._status.get("ai_fps") or 0.0), 1),
                "capture_fps": round(float(self._status.get("capture_fps") or 0.0), 1),
                "last_ai_ms": round(float(self._status.get("last_ai_ms") or 0.0), 1),
                "avg_ai_ms": round(float(self._status.get("avg_ai_ms") or 0.0), 1),
                "p95_ai_ms": round(float(self._status.get("p95_ai_ms") or 0.0), 1),
                "dropped_frames": dropped,
                "drop_ratio": round(min(1.0, dropped / float(latest_seq)), 4),
                "load_state": self._performance_load_state,
                "reason": self._performance_reason,
                "visible_tracks": tracks,
                "visible_faces": faces,
                "capture_total": int(self._capture_total),
                "ai_total": int(self._ai_total),
                "ptz_guard_active": ptz_remaining > 0.0,
                "ptz_guard_remaining_ms": int(round(ptz_remaining * 1000.0)),
                "preview_isolated": True,
                "event_driven_faceid": True,
                "pipeline_mode": "DECOUPLED_PREVIEW_IDENTITY",
                "ai_lane": str(self._status.get("ai_lane") or "FACEID_NATIVE"),
                "observation_ai_width": int(OBSERVATION_FACE_AI_WIDTH),
                "observation_face_target_fps": int(OBSERVATION_FACE_AI_FPS),
                "realtime_profile": str(self._status.get("realtime_profile") or "usb"),
                "decoder_output_fps": round(float(self._status.get("decoder_output_fps") or 0.0), 1),
                "decoder_max_width": int(self._status.get("decoder_max_width") or 0),
                "preview_target_fps": int(self._status.get("preview_target_fps") or CAMERA_PREVIEW_FPS),
                "preview_target_width": int(self._status.get("preview_target_width") or CAMERA_WIDTH),
                "preview_jpeg_quality": int(self._status.get("preview_jpeg_quality_effective") or JPEG_QUALITY),
                "ai_target_width": int(self._status.get("ai_target_width_effective") or AI_WIDTH),
                "queue_depth": 0,
                "preview_server_age_ms": None if preview_age_ms is None else round(preview_age_ms, 1),
                "tracking_result_age_ms": None if tracking_age_ms is None else round(tracking_age_ms, 1),
                "ai_capture": self._ai_capture.status(),
                "ai_metrics": dict(self._status.get("ai_metrics") or {}),
            }

    def _ai_loop(self, generation: int | None = None) -> None:
        last_seq = 0
        last_lane = None
        processed = 0
        t0 = time.perf_counter()
        while self._run_is_active(generation):
            cycle = time.perf_counter()
            with self._lock:
                hold_until = self._enrollment_hold_until
                observation_mode = bool(self._observation_mode)
                ptz_guard_active = cycle < float(self._ptz_guard_until or 0.0)
                recognition_paused = bool(self._recognition_paused or ptz_guard_active or not self._pipeline_enabled)
            with self._lock:
                active_source = str(self._status.get("source") or self._source_value())
            network_realtime = self._is_network_source(active_source)
            if network_realtime:
                base_target_fps = min(RTSP_AI_TARGET_FPS, OBSERVATION_FACE_AI_FPS if observation_mode else AI_TARGET_FPS)
            else:
                base_target_fps = OBSERVATION_FACE_AI_FPS if observation_mode else AI_TARGET_FPS
            target_fps = self._performance_target_fps(base_target_fps, cycle)
            with self._lock:
                self._status["ptz_guard_active"] = bool(ptz_guard_active)
                self._status["ptz_guard_remaining_ms"] = max(0, int(round((self._ptz_guard_until - cycle) * 1000.0))) if ptz_guard_active else 0
            if recognition_paused:
                time.sleep(min(0.05, 1.0 / max(1.0, target_fps)))
                continue
            period = 1.0 / max(1.0, target_fps)
            if cycle < hold_until:
                time.sleep(min(period, max(0.01, hold_until - cycle)))
                continue
            work_lock_started = time.perf_counter()
            if not self._ai_work_lock.acquire(timeout=.05):
                continue
            work_lock_wait_ms = (time.perf_counter() - work_lock_started) * 1000.
            try:
                # Handover/configuration may have changed these guards while this
                # loop waited for the work lock. Never read a new source or enter
                # inference until its backend camera context has been readmitted.
                with self._lock:
                    guarded_at = time.perf_counter()
                    guarded = (not self._run_is_active(generation) or not self._pipeline_enabled
                               or self._recognition_paused or guarded_at < self._enrollment_hold_until
                               or guarded_at < float(self._ptz_guard_until or 0.0))
                if guarded:
                    continue
                acquisition_started = time.perf_counter()
                frame, seq, capture_at, source_epoch, input_mode = self._ai_input_packet()
                acquisition_ms = (time.perf_counter() - acquisition_started) * 1000.
                lane_key = (source_epoch, input_mode)
                if lane_key != last_lane:
                    if last_lane is not None:
                        self._walkby.reset(self._ai_session_id)
                    last_seq = 0
                    last_lane = lane_key
                if frame is None or seq == last_seq:
                    time.sleep(0.004)
                    continue
                if seq > last_seq + 1:
                    with self._lock:
                        self._status["dropped_for_ai"] += int(seq - last_seq - 1)
                last_seq = seq
                # V2.6 runs two quality/performance lanes without touching the camera stream.
                # The browser keeps the native 1080p frame, while the personnel-tracking
                # page uses a bounded 1280px AI lane. This materially reduces latency and
                # CPU/GPU pressure without lowering the image quality operators see.
                # Normal FaceID/enrollment can still use the native MAX profile for small
                # or oblique faces. Identity extraction inside WalkBy remains event-driven.
                preprocessing_started = time.perf_counter()
                if network_realtime:
                    target_width = min(RTSP_AI_WIDTH, OBSERVATION_FACE_AI_WIDTH if observation_mode else max(RTSP_AI_WIDTH, AI_WIDTH if AI_WIDTH < 1280 else RTSP_AI_WIDTH))
                    work = self._resize_for_ai(frame, target_width)
                    native_ai = bool(work.shape[:2] == frame.shape[:2])
                    ai_lane = "RTSP_REALTIME_LATEST"
                elif observation_mode:
                    work = self._resize_for_ai(frame, OBSERVATION_FACE_AI_WIDTH)
                    native_ai = bool(work.shape[:2] == frame.shape[:2])
                    ai_lane = "PERSONNEL_TRACKING"
                elif AI_NATIVE_FRAME and frame.shape[1] <= AI_NATIVE_MAX_WIDTH:
                    work = frame.copy()
                    native_ai = True
                    ai_lane = "FACEID_NATIVE"
                else:
                    work = self._resize_for_ai(frame, AI_WIDTH)
                    native_ai = bool(work.shape[:2] == frame.shape[:2])
                    ai_lane = "FACEID_BALANCED"
                preprocessing_ms = (time.perf_counter() - preprocessing_started) * 1000.
                with self._lock:
                    self._status["native_ai_active"] = native_ai
                    self._status["ai_input_width"] = int(work.shape[1])
                    self._status["ai_input_height"] = int(work.shape[0])
                    self._status["ai_lane"] = ai_lane
                    self._status["ai_target_width_effective"] = int(work.shape[1])
                    self._status["pipeline_backlog"] = 0
                    self._status["ai_input_mode"] = input_mode
                    self._status["ai_capture_at"] = float(capture_at)
                started = time.perf_counter()
                try:
                    context = dict(self._event_context)
                    if context:
                        from .demo_context import camera_event_context
                        from .camera_appearances import APPEARANCES
                        event_scope = camera_event_context(context)
                        appearance_scope = APPEARANCES.frame(context, f"{self._appearance_owner}:{source_epoch}", datetime.now(timezone.utc))
                    else:
                        event_scope = nullcontext()
                        appearance_scope = nullcontext(None)
                    with event_scope, appearance_scope as appearance_frame:
                        result = self._walkby.process(
                            self._ai_session_id, work,
                            max_faces=OBSERVATION_MAX_FACES if observation_mode else None,
                            identity_budget=OBSERVATION_IDENTITY_BUDGET if observation_mode else None,
                            camera_source=self.event_camera_source(), async_mode=cfg.AI_ASYNC_ENABLED,
                            source_epoch=source_epoch, frame_seq=seq, capture_at=capture_at,
                            evidence_provider=self._ai_evidence_provider,
                            appearance_observer=appearance_frame.prepare if appearance_frame is not None else None,
                        )
                        if appearance_frame is not None:
                            appearance_frame.annotate(result)
                    result["updated_at"] = time.time()
                    result["source_epoch"] = source_epoch
                    result["camera_id"] = context.get("camera_id")
                    latency = (time.perf_counter() - started) * 1000.0
                    with self._lock:
                        if not self._run_is_active(generation):
                            continue
                        self._result = result
                        if result.get("events"):
                            for event in result["events"]:
                                item = dict(event)
                                self._recent_events.appendleft(item)
                            self._last_event = dict(result["events"][-1])
                        self._latencies.append(latency)
                        arr = np.asarray(self._latencies, dtype=np.float32)
                        self._status["last_ai_ms"] = round(latency, 1)
                        self._status["avg_ai_ms"] = round(float(arr.mean()), 1)
                        self._status["p95_ai_ms"] = round(float(np.percentile(arr, 95)), 1)
                        self._status["ai_seq"] = seq
                        self._status["visible_tracks"] = int(result.get("track_count") or len(result.get("tracks") or []))
                        self._status["visible_faces"] = int(result.get("face_count") or len(result.get("tracks") or []))
                        self._status["ai_metrics"] = dict(result.get("ai_metrics") or {})
                        self._status["ai_stage_times"] = {**dict(result.get("stage_times") or {}),
                            "work_lock_wait_ms": round(work_lock_wait_ms, 3),
                            "acquisition_ms": round(acquisition_ms, 3),
                            "preprocessing_ms": round(preprocessing_ms, 3),
                            "capture_to_result_ms": round(max(0., time.perf_counter() - capture_at) * 1000., 3)}
                        if not result.get("discarded_generation"):
                            if self._ai_result_source_epoch != source_epoch:
                                self._status["ai_successful_results_current_source"] = 0
                            self._status["ai_successful_results_current_source"] += 1
                            self._ai_result_source_epoch = source_epoch
                            self._ai_result_at = time.perf_counter()
                            self._ai_error_source_epoch = -1
                            self._status["ai_error_code"] = ""
                            self._ai_total += 1
                            processed += 1
                    if self._business_consumer is not None and context and not result.get("discarded_generation"):
                        try:
                            self._business_consumer(context, result, datetime.now(timezone.utc))
                        except Exception:
                            with self._lock:
                                self._status["business_error"] = "BUSINESS_RESULT_PENDING"
                except Exception:
                    with self._lock:
                        self._status["ai_error_code"] = "AI_PROCESS_FAILED"
                        self._ai_error_source_epoch = source_epoch
            finally:
                self._ai_work_lock.release()
            now = time.perf_counter()
            if now - t0 >= 1.0:
                with self._lock:
                    self._status["ai_fps"] = round(processed / max(1e-6, now - t0), 1)
                processed = 0
                t0 = now
            elapsed = time.perf_counter() - cycle
            if elapsed < period:
                time.sleep(period - elapsed)

    @staticmethod
    def _draw_overlay(frame: np.ndarray, result: dict) -> np.ndarray:
        tracks = result.get("tracks") or []
        fw = int(result.get("frame_width") or 0)
        fh = int(result.get("frame_height") or 0)
        if not tracks or fw <= 0 or fh <= 0:
            return frame
        out = frame.copy()
        ih, iw = out.shape[:2]
        sx = iw / float(fw)
        sy = ih / float(fh)
        for tr in tracks:
            b = tr.get("bbox") or [0, 0, 0, 0]
            x, y, w, h = [int(round(v)) for v in b]
            x1, y1 = int(x * sx), int(y * sy)
            x2, y2 = int((x + w) * sx), int((y + h) * sy)
            recognized = bool(tr.get("recognized"))
            status = str(tr.get("status") or "").upper()
            unregistered = bool(tr.get("unknown")) or status == "UNREGISTERED"
            blocked = bool(tr.get("spoof_blocked")) or status == "SPOOF_BLOCKED"
            verifying = status in {"VERIFYING_PASSIVE", "VERIFYING_LIVENESS", "LIVENESS_CHALLENGE"}
            if blocked:
                color = (65, 65, 235)
            elif recognized:
                color = (60, 220, 140)
            elif unregistered:
                color = (45, 175, 255)
            elif verifying:
                color = (255, 200, 55)
            else:
                color = (255, 185, 45)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            live_info = tr.get('liveness') or {}
            risk_pct = int(round(float(live_info.get('risk_score') or 0.0) * 100))
            context_pct = int(round(float(live_info.get('context_score') or 0.0) * 100))
            if blocked:
                method = str(live_info.get('spoof_method') or 'PHONE/PHOTO')
                label = f"ID {tr.get('track_id')}  SPOOF BLOCKED  {method}"
            elif recognized:
                pad_info = ((live_info.get('signals') or {}).get('pad') or {})
                pad_live = int(round(float(pad_info.get('live_score') or live_info.get('score') or 0.0) * 100))
                if pad_info.get('ready') is False:
                    label = f"ID {tr.get('track_id')}  FACEID {int(round(float(tr.get('confidence') or 0.0) * 100))}%  ANTI-SPOOF CONTEXT"
                else:
                    label = f"ID {tr.get('track_id')}  FACEID {int(round(float(tr.get('confidence') or 0.0) * 100))}%  PAD LIVE {pad_live}%"
            elif unregistered:
                label = f"ID {tr.get('track_id')}  UNREGISTERED"
            elif verifying:
                pad_info = ((live_info.get('signals') or {}).get('pad') or {})
                if pad_info.get('ready') is False:
                    label = f"ID {tr.get('track_id')}  ANTI-SPOOF CONTEXT CHECK"
                else:
                    pad_live = int(round(float(pad_info.get('live_score') or 0.0) * 100))
                    pad_spoof = int(round(float(pad_info.get('spoof_score') or 0.0) * 100))
                    label = f"ID {tr.get('track_id')}  PAD CHECK  LIVE {pad_live}% SPOOF {pad_spoof}%"
            else:
                label = f"ID {tr.get('track_id')}  ANALYZING"
            cv2.putText(out, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
        return out

    def _preview_loop(self, generation: int | None = None) -> None:
        priority_ok = _set_current_thread_priority(above_normal=True)
        with self._lock:
            self._status["preview_priority_boosted"] = bool(priority_ok)
        frames = 0
        observation_frames = 0
        observation_encode_samples = deque(maxlen=45)
        t0 = time.perf_counter()
        last_seq = -1
        while self._run_is_active(generation):
            started = time.perf_counter()
            now_perf = started
            with self._lock:
                active_source = str(self._status.get("source") or self._source_value())
            network_realtime = self._is_network_source(active_source)
            preview_target_fps = RTSP_PREVIEW_FPS if network_realtime else CAMERA_PREVIEW_FPS
            preview_target_width = RTSP_PREVIEW_WIDTH if network_realtime else CAMERA_WIDTH
            preview_quality = RTSP_JPEG_QUALITY if network_realtime else JPEG_QUALITY
            period = 1.0 / max(1, preview_target_fps)
            with self._lock:
                self._status["preview_target_fps"] = int(preview_target_fps)
                self._status["preview_target_width"] = int(preview_target_width)
                self._status["preview_jpeg_quality_effective"] = int(preview_quality)
            # Check whether any browser view actually needs a JPEG before copying
            # the full camera frame. On Classroom-only use this cuts unnecessary
            # 25-FPS memory copies and leaves more CPU for FaceID/Pose.
            with self._lock:
                preview_needed = (now_perf - self._preview_requested_at) < 0.55
                raw_needed = (now_perf - self._raw_requested_at) < 0.55
                observation_needed = (now_perf - self._observation_requested_at) < 0.55
                observation_due = (now_perf - self._observation_last_encoded_at) >= (1.0 / max(1, OBSERVATION_PREVIEW_FPS))
                source_epoch = self._source_epoch
                any_due = preview_needed or raw_needed or (observation_needed and observation_due)
                if any_due:
                    frame = None if self._frame is None else self._frame.copy()
                    result = dict(self._result)
                    seq = self._frame_seq
                    online = self._status.get("state") == "online"
                else:
                    frame = None
                    result = {}
                    seq = self._frame_seq
                    online = self._status.get("state") == "online"
            if online and frame is not None and seq != last_seq:
                raw_buf = None
                observation_buf = None
                buf = None
                ok = False
                if preview_needed:
                    ph, pw = frame.shape[:2]
                    if pw > preview_target_width:
                        scale = preview_target_width / float(pw)
                        preview_frame = cv2.resize(frame, (preview_target_width, max(1, int(round(ph * scale)))), interpolation=cv2.INTER_AREA)
                    else:
                        preview_frame = frame
                    preview = self._draw_overlay(preview_frame, result)
                    ok, buf = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), preview_quality])
                if raw_needed:
                    # Enrollment uses the raw stream. Enhance only this browser JPEG;
                    # self._frame stays untouched for FaceID/PAD processing.
                    enroll_preview = self._enhance_enrollment_preview(frame)
                    enroll_quality = max(90, int(JPEG_QUALITY))
                    raw_ok, raw_buf = cv2.imencode(".jpg", enroll_preview, [int(cv2.IMWRITE_JPEG_QUALITY), enroll_quality])
                    if not raw_ok:
                        raw_buf = None
                if observation_needed and observation_due:
                    ph, pw = frame.shape[:2]
                    observation_width = min(OBSERVATION_PREVIEW_WIDTH, RTSP_PREVIEW_WIDTH) if network_realtime else OBSERVATION_PREVIEW_WIDTH
                    if pw > observation_width:
                        scale = observation_width / float(pw)
                        observation_frame = cv2.resize(frame, (observation_width, max(1, int(round(ph * scale)))), interpolation=cv2.INTER_AREA)
                    else:
                        # Never upscale a low-resolution webcam frame: interpolation cannot
                        # create real detail. V5 preserves native pixels and improves only
                        # display contrast/sharpness.
                        observation_frame = frame
                    observation_frame = self._enhance_observation_preview(observation_frame)
                    observation_quality = min(OBSERVATION_JPEG_QUALITY, RTSP_JPEG_QUALITY) if network_realtime else OBSERVATION_JPEG_QUALITY
                    encode_args = [int(cv2.IMWRITE_JPEG_QUALITY), observation_quality]
                    if hasattr(cv2, "IMWRITE_JPEG_LUMA_QUALITY"):
                        encode_args += [int(cv2.IMWRITE_JPEG_LUMA_QUALITY), OBSERVATION_JPEG_QUALITY]
                    encode_started = time.perf_counter()
                    c_ok, observation_buf = cv2.imencode(".jpg", observation_frame, encode_args)
                    observation_encode_samples.append((time.perf_counter() - encode_started) * 1000.0)
                    if not c_ok:
                        observation_buf = None
                if ok or raw_buf is not None or observation_buf is not None:
                    with self._lock:
                        if source_epoch != self._source_epoch or not self._run_is_active(generation):
                            continue
                        if ok and buf is not None:
                            self._jpeg = buf.tobytes()
                            self._jpeg_seq, self._jpeg_at = seq, time.perf_counter()
                        if raw_buf is not None:
                            self._raw_jpeg = raw_buf.tobytes()
                            self._raw_jpeg_seq, self._raw_jpeg_at = seq, time.perf_counter()
                        if observation_buf is not None:
                            self._observation_jpeg = observation_buf.tobytes()
                            self._observation_jpeg_seq = int(seq)
                            self._observation_jpeg_at = time.perf_counter()
                            self._observation_last_encoded_at = now_perf
                            observation_frames += 1
                last_seq = seq
                frames += 1
            now = time.perf_counter()
            if now - t0 >= 1.0:
                with self._lock:
                    self._status["preview_fps"] = round(frames / max(1e-6, now - t0), 1)
                    self._status["observation_preview_fps"] = round(observation_frames / max(1e-6, now - t0), 1)
                    if observation_encode_samples:
                        self._status["observation_encode_ms"] = round(float(np.mean(observation_encode_samples)), 1)
                    self._status["observation_jpeg_quality"] = int(OBSERVATION_JPEG_QUALITY)
                frames = 0
                observation_frames = 0
                t0 = now
            elapsed = time.perf_counter() - started
            if elapsed < period:
                time.sleep(period - elapsed)

    def current_source_identity(self) -> str:
        """Internal comparison only: never serialize this into a public response."""
        with self._lock:
            return str(self._status.get("source") or self._source_override or CAMERA_SOURCE)

    def preview_packet(self, raw: bool = False) -> tuple[bytes, int, float | None]:
        """Finite JPEG response with actual encoded-frame age, independent of AI."""
        now = time.perf_counter()
        with self._lock:
            if raw:
                self._raw_requested_at = now
                data, seq, at = self._raw_jpeg, self._raw_jpeg_seq, self._raw_jpeg_at
            else:
                self._preview_requested_at = now
                data, seq, at = self._jpeg, self._jpeg_seq, self._jpeg_at
        return bytes(data), int(seq), round(max(0.0, now - at) * 1000.0, 1) if at else None

    def scoped_preview_packet(self, source: str, epoch: int) -> tuple[bytes, int, float | None]:
        """Return only fresh raw JPEG bytes from the requested physical source."""
        with self._lock:
            if self.media_source_context() != (normalize_camera_source(source), int(epoch)):
                return b"", 0, None
            now = time.perf_counter()
            self._raw_requested_at = now
            age = now - self._raw_jpeg_at if self._raw_jpeg_at else None
            if age is None or not 0 <= age < 4.0:
                return b"", 0, None
            return bytes(self._raw_jpeg), int(self._raw_jpeg_seq), round(age * 1000.0, 1)

    def latest_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def latest_media_packet(self) -> tuple[np.ndarray | None, int, float]:
        """Return the newest native camera frame for zero-backlog media transport.

        Unlike the JPEG preview accessors this does *not* mark the JPEG encoder as
        requested. WebRTC can therefore read the native 1080p frame directly while
        the legacy JPEG worker naturally goes idle after its fallback client leaves.
        """
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
            return frame, int(self._frame_seq), float(self._frame_at)

    def latest_jpeg(self) -> bytes:
        with self._lock:
            self._preview_requested_at = time.perf_counter()
            return bytes(self._jpeg)

    def latest_raw_jpeg(self) -> bytes:
        with self._lock:
            self._raw_requested_at = time.perf_counter()
            return bytes(self._raw_jpeg)

    def latest_observation_jpeg(self) -> bytes:
        """Newest enhanced operator preview for identity-only observation."""
        with self._lock:
            self._observation_requested_at = time.perf_counter()
            return bytes(self._observation_jpeg or self._raw_jpeg or self._jpeg)

    def latest_observation_packet(self) -> tuple[bytes, int, float]:
        """Newest identity-observation JPEG with zero-backlog sequence metadata."""
        with self._lock:
            self._observation_requested_at = time.perf_counter()
            jpeg = bytes(self._observation_jpeg or self._raw_jpeg or self._jpeg)
            seq = int(self._observation_jpeg_seq or self._frame_seq)
            encoded_at = float(self._observation_jpeg_at or self._frame_at)
            return jpeg, seq, encoded_at

    def set_observation_mode(self, enabled: bool) -> None:
        """Enable the identity-optimized observation lane without behaviour analysis."""
        with self._lock:
            self._observation_mode = bool(enabled)
            self._status["observation_mode"] = bool(enabled)
            if not enabled:
                self._observation_requested_at = 0.0

    def hold_enrollment_mode(self, seconds: float = 0.75) -> None:
        with self._lock:
            self._enrollment_hold_until = max(
                self._enrollment_hold_until,
                time.perf_counter() + max(0.1, seconds),
            )

    def latest_event(self):
        with self._lock:
            return dict(self._last_event) if self._last_event else None

    def recent_events(self, limit: int = 12) -> list[dict]:
        limit = max(1, min(24, int(limit)))
        with self._lock:
            return [dict(x) for x in list(self._recent_events)[:limit]]

    def latest_result(self) -> dict:
        with self._lock:
            out = dict(self._result)
            out["recognition_paused"] = bool(self._recognition_paused)
            out["handover"] = dict(self._handover)
            out["camera_source"] = str(self._status.get("source_label") or self._status.get("source") or CAMERA_SOURCE)
            return out

    def purge_student(self, student_id: int) -> None:
        sid = int(student_id)
        with self._lock:
            if self._last_event:
                st = self._last_event.get("student") or {}
                if int(st.get("id") or -1) == sid or int(self._last_event.get("student_id") or -1) == sid:
                    self._last_event = None
            kept = []
            for ev in self._recent_events:
                st = ev.get("student") or {}
                if int(st.get("id") or -1) == sid or int(ev.get("student_id") or -1) == sid:
                    continue
                kept.append(ev)
            self._recent_events.clear()
            self._recent_events.extend(kept)
            tracks = []
            for tr in self._result.get("tracks", []):
                row = dict(tr)
                if int(row.get("student_id") or -1) == sid:
                    row.update({"recognized": False, "student_id": None, "confidence": 0.0, "unknown": True, "status": "UNREGISTERED", "display_name": "Chưa đăng ký"})
                tracks.append(row)
            self._result = {**self._result, "tracks": tracks}

    def _apply_digital_ptz(self, frame: np.ndarray) -> np.ndarray:
        """Apply loss-bounded digital pan/tilt/zoom and resize back to source size.

        This is the fallback for laptop cameras or PTZ drivers that do not expose
        UVC pan/tilt/zoom properties. Because the crop is resized to the original
        dimensions, recognition, overlays and browser previews keep one coordinate
        system and do not need special handling.
        """
        with self._lock:
            state = dict(self._ptz_state)
        if str(state.get("mode") or "digital") != "digital":
            return frame
        zoom = max(1.0, min(4.0, float(state.get("zoom") or 1.0)))
        pan = max(-1.0, min(1.0, float(state.get("pan") or 0.0)))
        tilt = max(-1.0, min(1.0, float(state.get("tilt") or 0.0)))
        if zoom <= 1.001 and abs(pan) < 0.001 and abs(tilt) < 0.001:
            return frame
        h, w = frame.shape[:2]
        crop_w = max(160, min(w, int(round(w / zoom))))
        crop_h = max(120, min(h, int(round(h / zoom))))
        room_x = max(0, w - crop_w)
        room_y = max(0, h - crop_h)
        cx = (w / 2.0) + pan * (room_x / 2.0)
        cy = (h / 2.0) + tilt * (room_y / 2.0)
        x1 = max(0, min(w - crop_w, int(round(cx - crop_w / 2.0))))
        y1 = max(0, min(h - crop_h, int(round(cy - crop_h / 2.0))))
        crop = frame[y1:y1 + crop_h, x1:x1 + crop_w]
        if crop.size == 0:
            return frame
        return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)

    @staticmethod
    def _ptz_prop(name: str):
        return getattr(cv2, name, None)

    def _try_hardware_ptz(self, action: str, speed: float) -> tuple[bool, str]:
        """Best-effort UVC PTZ through the active OpenCV capture object."""
        source = str(self._status.get("source") or CAMERA_SOURCE).strip().lower()
        # Index 0 is treated as the laptop camera. External/secondary cameras are
        # allowed to try the driver's UVC PTZ controls first.
        if source in {"0", "laptop", "camera laptop"}:
            return False, "Camera laptop dùng Digital PTZ"
        with self._cap_lock:
            cap = self._cap
            if cap is None:
                return False, "Camera chưa sẵn sàng"
            try:
                if action in {"left", "right"}:
                    prop = self._ptz_prop("CAP_PROP_PAN")
                    if prop is None: return False, "Driver không có PAN"
                    current = float(cap.get(prop) or 0.0)
                    step = 2.0 + 13.0 * speed
                    target = max(-180.0, min(180.0, current + (-step if action == "left" else step)))
                    ok = bool(cap.set(prop, target))
                elif action in {"up", "down"}:
                    prop = self._ptz_prop("CAP_PROP_TILT")
                    if prop is None: return False, "Driver không có TILT"
                    current = float(cap.get(prop) or 0.0)
                    step = 2.0 + 13.0 * speed
                    target = max(-180.0, min(180.0, current + (-step if action == "up" else step)))
                    ok = bool(cap.set(prop, target))
                elif action in {"zoom_in", "zoom_out"}:
                    prop = self._ptz_prop("CAP_PROP_ZOOM")
                    if prop is None: return False, "Driver không có ZOOM"
                    current = float(cap.get(prop) or 0.0)
                    step = 5.0 + 35.0 * speed
                    target = max(0.0, min(1000.0, current + (step if action == "zoom_in" else -step)))
                    ok = bool(cap.set(prop, target))
                elif action == "home":
                    ok = False
                    for pname in ("CAP_PROP_PAN", "CAP_PROP_TILT"):
                        prop = self._ptz_prop(pname)
                        if prop is not None:
                            ok = bool(cap.set(prop, 0.0)) or ok
                elif action in {"focus_near", "focus_far"}:
                    prop = self._ptz_prop("CAP_PROP_FOCUS")
                    if prop is None: return False, "Driver không có FOCUS"
                    current = float(cap.get(prop) or 0.0)
                    step = 2.0 + 12.0 * speed
                    target = max(0.0, min(255.0, current + (-step if action == "focus_near" else step)))
                    if hasattr(cv2, "CAP_PROP_AUTOFOCUS"):
                        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                    ok = bool(cap.set(prop, target))
                elif action in {"autofocus_on", "autofocus_off"}:
                    prop = self._ptz_prop("CAP_PROP_AUTOFOCUS")
                    if prop is None: return False, "Driver không có AUTOFOCUS"
                    ok = bool(cap.set(prop, 1 if action == "autofocus_on" else 0))
                else:
                    return False, "Lệnh PTZ không hợp lệ"
            except Exception as exc:
                return False, f"Driver PTZ lỗi: {exc}"
        return (ok, "Đã gửi lệnh PTZ phần cứng" if ok else "Driver không nhận lệnh PTZ")

    def control_ptz(self, action: str, speed: float = 0.5) -> dict:
        action = str(action or "").strip().lower()
        allowed = {"left", "right", "up", "down", "zoom_in", "zoom_out", "home", "focus_near", "focus_far", "autofocus_on", "autofocus_off"}
        if action not in allowed:
            raise ValueError("Lệnh điều khiển camera không hợp lệ")
        speed = max(0.1, min(1.0, float(speed or 0.5)))
        # Keep preview live but suspend biometric inference during PTZ motion/focus.
        hold = PERFORMANCE_GUARD_PTZ_HOLD_SEC
        if action == "home":
            hold = max(hold, 0.85)
        elif action in {"zoom_in", "zoom_out"}:
            hold = max(hold, 0.65)
        with self._lock:
            self._ptz_guard_until = max(self._ptz_guard_until, time.perf_counter() + hold)
        hardware_ok, message = self._try_hardware_ptz(action, speed)
        with self._lock:
            self._ptz_state["speed"] = speed
            self._ptz_state["last_action"] = action.upper()
            self._ptz_state["hardware_supported"] = bool(hardware_ok or self._ptz_state.get("hardware_supported"))
            if hardware_ok:
                self._ptz_state["mode"] = "hardware"
                self._ptz_state["message"] = message
            else:
                # Focus is a true optical control; do not fake it digitally.
                if action in {"focus_near", "focus_far", "autofocus_on", "autofocus_off"}:
                    self._ptz_state["message"] = message
                else:
                    self._ptz_state["mode"] = "digital"
                    step = 0.08 + 0.22 * speed
                    if action in {"left", "right", "up", "down"} and float(self._ptz_state.get("zoom") or 1.0) < 1.18:
                        self._ptz_state["zoom"] = 1.35
                    if action == "left": self._ptz_state["pan"] = max(-1.0, float(self._ptz_state.get("pan") or 0.0) - step)
                    elif action == "right": self._ptz_state["pan"] = min(1.0, float(self._ptz_state.get("pan") or 0.0) + step)
                    elif action == "up": self._ptz_state["tilt"] = max(-1.0, float(self._ptz_state.get("tilt") or 0.0) - step)
                    elif action == "down": self._ptz_state["tilt"] = min(1.0, float(self._ptz_state.get("tilt") or 0.0) + step)
                    elif action == "zoom_in": self._ptz_state["zoom"] = min(4.0, float(self._ptz_state.get("zoom") or 1.0) + 0.18 + 0.42 * speed)
                    elif action == "zoom_out": self._ptz_state["zoom"] = max(1.0, float(self._ptz_state.get("zoom") or 1.0) - (0.18 + 0.42 * speed))
                    elif action == "home": self._ptz_state.update({"pan": 0.0, "tilt": 0.0, "zoom": 1.0})
                    self._ptz_state["message"] = "Digital PTZ đang hoạt động" if action != "home" else "Đã về vị trí trung tâm"
        return self.ptz_status()

    def ptz_status(self) -> dict:
        with self._lock:
            data = dict(self._ptz_state)
            data["camera_source"] = str(self._status.get("source") or CAMERA_SOURCE)
            data["camera_online"] = bool(self._status.get("opened")) and str(self._status.get("state")) == "online"
        return data

    def _set_handover_state(self, **updates) -> None:
        with self._lock:
            self._handover.update(updates)
            self._status["recognition_paused"] = bool(self._recognition_paused)
            self._status["handover_active"] = bool(self._handover.get("active"))
            self._status["handover_state"] = str(self._handover.get("state") or "IDLE")

    def _clear_transient_recognition(self, *, clear_recent: bool = True) -> None:
        self._walkby.reset(self._ai_session_id)
        with self._lock:
            self._result = {"tracks": [], "events": [], "frame_width": 0, "frame_height": 0}
            self._last_event = None
            if clear_recent:
                self._recent_events.clear()
            self._latencies.clear()
            self._status["last_ai_ms"] = 0.0
            self._status["avg_ai_ms"] = 0.0
            self._status["p95_ai_ms"] = 0.0

    def _clear_camera_buffers_for_handover(self) -> None:
        with self._lock:
            self._frame = None
            self._frame_at = 0.0
            self._jpeg = b""
            self._raw_jpeg = b""
            self._observation_jpeg = b""
            self._observation_jpeg_seq = 0
            self._observation_jpeg_at = 0.0



    def select_source(self, source: str, source_label: str | None = None) -> dict:
        return self.safe_select_source(source, source_label=source_label)


    def _reconcile_stale_pause(self) -> None:
        """Resume FaceID when handover already ended but the recovered camera is healthy.

        This is a fail-safe for slow Windows/PTZ drivers: the rollback timeout can
        expire a moment before frames resume. The runtime may therefore be ONLINE
        while the old V14.1 pause bit is still True. That stale bit must not keep
        the UI locked in "Đang chuyển" or block recognition indefinitely.
        """
        now = time.perf_counter()
        with self._lock:
            if bool(self._handover.get("active")) or not self._recognition_paused:
                return
            frame_at = float(self._frame_at or 0.0)
            healthy = bool(self._status.get("opened")) and str(self._status.get("state") or "") == "online"
            fresh = frame_at > 0.0 and (now - frame_at) <= 1.0
            if not (healthy and fresh):
                return
            self._recognition_paused = False
            self._handover.update({
                "active": False,
                "state": "RECOVERED",
                "message": f"{self._status.get('source_label') or self._default_source_label(str(self._status.get('source') or CAMERA_SOURCE))} đã phục hồi · FaceID tiếp tục",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            self._status["recognition_paused"] = False
            self._status["handover_active"] = False
            self._status["handover_state"] = "RECOVERED"

    def status(self) -> dict:
        self._reconcile_stale_pause()
        with self._lock:
            out = dict(self._status)
            out["recognition_paused"] = bool(self._recognition_paused)
            out["ai_paused"] = bool(self._recognition_paused or not self._pipeline_enabled
                                    or time.perf_counter() < self._enrollment_hold_until
                                    or time.perf_counter() < self._ptz_guard_until)
            if self._ai_result_source_epoch != self._source_epoch:
                out["ai_successful_results_current_source"] = 0
            if self._ai_error_source_epoch != self._source_epoch:
                out["ai_error_code"] = ""
            out["handover"] = dict(self._handover)
            out["source_label"] = str(self._status.get("source_label") or self._source_label_override or self._default_source_label(str(self._status.get("source") or CAMERA_SOURCE)))
            frame_at = float(self._frame_at or 0.0)
        if frame_at > 0.0:
            age_ms = max(0.0, (time.perf_counter() - frame_at) * 1000.0)
            out["last_frame_age_ms"] = round(age_ms, 1)
            if age_ms > 1300 and out.get("state") == "online":
                out["opened"] = False
                out["state"] = "reconnecting"
                out["error"] = out.get("error") or "Frame camera bị trễ - đang phục hồi"
        else:
            out["last_frame_age_ms"] = None
        perf = self.performance_status()
        out["performance"] = perf
        out["ai_target_fps_effective"] = perf["effective_target_fps"]
        out["ai_load_state"] = perf["load_state"]
        out["ai_drop_ratio"] = perf["drop_ratio"]
        out["ptz_guard_active"] = perf["ptz_guard_active"]
        out["ptz_guard_remaining_ms"] = perf["ptz_guard_remaining_ms"]
        return out


CAMERA = StaticCameraService()
