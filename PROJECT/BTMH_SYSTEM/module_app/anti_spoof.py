from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .config import (
    ANTI_SPOOF_MODE, DEVICE_CONTEXT_HARD_RISK, DEVICE_CONTEXT_SUSPECT_RISK,
    PAD_WINDOW, PAD_MIN_OBS, PAD_PASS_LIVE, PAD_STRONG_LIVE, PAD_SPOOF_BLOCK,
    PAD_PASS_VOTES, PAD_BLOCK_VOTES,
    PAD_REQUIRED, CONTEXT_FALLBACK_ENABLED, CONTEXT_BLOCK_STREAK,
    CONTEXT_PASS_STREAK, CONTEXT_PASS_RISK_MAX,
    ANTI_SPOOF_RECOVERY_SEC, ANTI_SPOOF_RECOVERY_CLEAN_FRAMES, ANTI_SPOOF_RECOVERY_CONTEXT_MAX,
)
from .device_context import DEVICE_CONTEXT
from .passive_pad import PAD


@dataclass
class LivenessDecision:
    status: str
    score: float
    reason: str
    challenge: str = ""
    challenge_text: str = ""
    screen_score: float = 0.0
    blink_seen: bool = False
    observations: int = 0
    spoof_method: str = ""
    risk_score: float = 0.0
    context_score: float = 0.0
    decision_version: str = "V1-FACE-context-first"
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def blocked(self) -> bool:
        return self.status == "BLOCKED"

    def public(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": round(float(self.score), 4),
            "reason": self.reason,
            "challenge": self.challenge,
            "challenge_text": self.challenge_text,
            "screen_score": round(float(self.screen_score), 4),
            "blink_seen": bool(self.blink_seen),
            "observations": int(self.observations),
            "spoof_method": str(self.spoof_method or ""),
            "risk_score": round(float(self.risk_score), 4),
            "context_score": round(float(self.context_score), 4),
            "decision_version": str(self.decision_version or "V1-FACE-context-first"),
            "signals": dict(self.signals or {}),
        }


@dataclass
class _LivenessState:
    created_at: float
    last_at: float = 0.0
    last_thumb: np.ndarray | None = None
    observations: int = 0
    yaw_history: deque = field(default_factory=lambda: deque(maxlen=28))
    pitch_history: deque = field(default_factory=lambda: deque(maxlen=28))
    diff_history: deque = field(default_factory=lambda: deque(maxlen=20))
    screen_history: deque = field(default_factory=lambda: deque(maxlen=16))
    risk_history: deque = field(default_factory=lambda: deque(maxlen=18))
    face_size_history: deque = field(default_factory=lambda: deque(maxlen=20))
    blink_seen: bool = False
    eyes_were_open: bool = False
    status: str = "CHECKING"
    reason: str = "Đang xác minh thụ động"
    score: float = 0.0
    risk_score: float = 0.0
    last_mesh_at: float = 0.0
    spoof_method: str = ""
    clean_streak: int = 0
    suspicious_streak: int = 0
    status_since: float = 0.0
    last_context_score: float = 0.0
    device_history: deque = field(default_factory=lambda: deque(maxlen=8))
    hard_device_streak: int = 0
    last_device: dict = field(default_factory=dict)
    pad_live_history: deque = field(default_factory=lambda: deque(maxlen=12))
    pad_spoof_history: deque = field(default_factory=lambda: deque(maxlen=12))
    pad_label_history: deque = field(default_factory=lambda: deque(maxlen=12))
    last_pad: dict = field(default_factory=dict)
    recovery_clean_streak: int = 0
    recovery_clean_since: float = 0.0
    recovery_count: int = 0


class AntiSpoofEngine:
    """RGB-camera anti-spoof gate for CampusFace.

    This is deliberately a *multi-signal* gate rather than a magic single-frame
    classifier. With an ordinary laptop/USB RGB camera we can reliably block many
    obvious phone/photo attacks, but we must not claim TrueDepth-level security.

    Signals:
      * rectangular screen/print carrier around the detected face,
      * temporal texture change and natural pose variation,
      * optional MediaPipe eye-state evidence as a passive bonus only.

    V1 FACE continuously re-validates passive anti-spoof context before and after FaceID. It NEVER asks a student to blink,
    turn, look up, stop walking, or look at the camera. A recognition event is
    FaceID itself is gated behind multi-frame PASS. Strong phone/photo carrier evidence is
    BLOCKED before identity matching, including faces that are not registered.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, _LivenessState] = {}
        self._face_mesh = None
        self._face_mesh_attempted = False

    @staticmethod
    def _clip_box(box, shape, pad: float = 0.70) -> tuple[int, int, int, int]:
        ih, iw = shape[:2]
        x, y, w, h = [float(v) for v in box]
        px, py = w * pad, h * pad
        x1 = max(0, int(round(x - px)))
        y1 = max(0, int(round(y - py)))
        x2 = min(iw, int(round(x + w + px)))
        y2 = min(ih, int(round(y + h + py)))
        return x1, y1, max(x1 + 1, x2), max(y1 + 1, y2)

    @staticmethod
    def _gray_thumb(image: np.ndarray, box) -> np.ndarray | None:
        x1, y1, x2, y2 = AntiSpoofEngine._clip_box(box, image.shape, 0.18)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (56, 56), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        return gray.astype(np.float32) / 255.0

    @staticmethod
    def _rectangular_carrier_score(image: np.ndarray, face_box) -> float:
        """Estimate whether a face is inside a phone/photo-like rectangle.

        The detector is intentionally conservative. It only scores contours that
        fully contain the face centre and are substantially larger than the face.
        This catches the common "hold a phone/photo in front of the webcam" attack
        while avoiding ordinary background rectangles as much as possible.
        """
        ih, iw = image.shape[:2]
        fx, fy, fw, fh = [float(v) for v in face_box]
        if fw <= 4 or fh <= 4:
            return 0.0
        face_area = fw * fh
        face_cx, face_cy = fx + fw * 0.5, fy + fh * 0.5
        x1, y1, x2, y2 = AntiSpoofEngine._clip_box(face_box, image.shape, 1.75)
        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            return 0.0
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 52, 142)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        best = 0.0
        roi_area = float(max(1, roi.shape[0] * roi.shape[1]))
        for cnt in contours:
            area = float(abs(cv2.contourArea(cnt)))
            if area < max(700.0, face_area * 1.35) or area > roi_area * 0.94:
                continue
            peri = float(cv2.arcLength(cnt, True))
            if peri <= 1:
                continue
            approx = cv2.approxPolyDP(cnt, 0.024 * peri, True)
            if len(approx) < 4 or len(approx) > 6:
                continue
            rx, ry, rw, rh = cv2.boundingRect(approx)
            if rw < fw * 1.05 or rh < fh * 1.05:
                continue
            abs_rx, abs_ry = rx + x1, ry + y1
            if not (abs_rx <= face_cx <= abs_rx + rw and abs_ry <= face_cy <= abs_ry + rh):
                continue
            carrier_area = float(rw * rh)
            ratio = carrier_area / max(1.0, face_area)
            if ratio < 1.45 or ratio > 9.0:
                continue
            aspect = rw / max(1.0, float(rh))
            if aspect < 0.40 or aspect > 1.95:
                continue
            rectangularity = min(1.0, area / max(1.0, carrier_area))
            face_fill = face_area / max(1.0, carrier_area)
            # Phone/photo attacks typically have a clear carrier border and the face
            # occupies only part of it. Penalise near-face contours heavily.
            separation = min(1.0, max(0.0, (1.0 - face_fill) / 0.72))
            size_term = min(1.0, max(0.0, (ratio - 1.45) / 2.8))
            score = 0.45 * rectangularity + 0.35 * separation + 0.20 * size_term
            # A rectangle covering almost the entire camera frame is often a wall,
            # window or monitor in the background; require stronger evidence.
            frame_cover = carrier_area / max(1.0, float(iw * ih))
            if frame_cover > 0.72:
                score *= 0.62
            best = max(best, score)

        # Partial phone screens often do not form a closed contour because one edge
        # is outside the camera frame.  Hough-line enclosure catches the common
        # three-sided phone/display case without requiring a complete quadrilateral.
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180.0,
            threshold=max(24, int(min(roi.shape[:2]) * 0.10)),
            minLineLength=max(34, int(min(fw, fh) * 0.55)),
            maxLineGap=max(12, int(min(fw, fh) * 0.16)),
        )
        if lines is not None:
            face_left = fx - x1
            face_right = fx + fw - x1
            face_top = fy - y1
            face_bottom = fy + fh - y1
            fcx = face_cx - x1
            fcy = face_cy - y1
            left_hits = right_hits = top_hits = bottom_hits = 0
            for raw in lines[:, 0]:
                lx1, ly1, lx2, ly2 = [float(v) for v in raw]
                dx, dy = lx2 - lx1, ly2 - ly1
                length = math.hypot(dx, dy)
                if length <= 1:
                    continue
                mx, my = (lx1 + lx2) * 0.5, (ly1 + ly2) * 0.5
                if abs(dx) <= max(3.0, abs(dy) * 0.28) and length >= fh * 0.45:
                    # Vertical carrier edge: close enough to surround the face but not
                    # merely the face box itself.
                    if face_left - 3.2 * fw <= mx <= face_left - 0.18 * fw:
                        left_hits += 1
                    if face_right + 0.18 * fw <= mx <= face_right + 3.2 * fw:
                        right_hits += 1
                elif abs(dy) <= max(3.0, abs(dx) * 0.28) and length >= fw * 0.65:
                    if face_top - 3.4 * fh <= my <= face_top - 0.18 * fh:
                        top_hits += 1
                    if face_bottom + 0.18 * fh <= my <= face_bottom + 2.5 * fh:
                        bottom_hits += 1
            vertical_pair = left_hits > 0 and right_hits > 0
            horizontal_any = top_hits > 0 or bottom_hits > 0
            line_score = 0.0
            if vertical_pair and horizontal_any:
                line_score = 0.88
            elif vertical_pair:
                line_score = 0.68
            elif horizontal_any and (left_hits > 0 or right_hits > 0):
                line_score = 0.62
            # Hough lines are useful as weak evidence, but classroom backgrounds
            # (chair backs, windows, boards) often form three-sided rectangles around
            # a real face. Never let line-only evidence become a hard spoof signal.
            # A closed contour above still remains strong evidence for phone/photo.
            best = max(best, line_score * 0.20)

        return float(max(0.0, min(1.0, best)))

    def _ensure_face_mesh(self):
        if self._face_mesh_attempted:
            return self._face_mesh
        self._face_mesh_attempted = True
        try:
            import mediapipe as mp  # type: ignore
            try:
                api = mp.solutions.face_mesh
            except Exception:
                from mediapipe.python.solutions import face_mesh as api  # type: ignore
            self._face_mesh = api.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=False,
                min_detection_confidence=0.45,
            )
        except Exception:
            self._face_mesh = False
        return self._face_mesh

    @staticmethod
    def _ear(points: np.ndarray, ids: tuple[int, int, int, int, int, int]) -> float:
        p1, p2, p3, p4, p5, p6 = [points[i] for i in ids]
        horizontal = float(np.linalg.norm(p1 - p4))
        if horizontal < 1e-6:
            return 0.0
        vertical = float(np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5))
        return vertical / (2.0 * horizontal)

    def _blink_observation(self, image: np.ndarray, box) -> float | None:
        mesh = self._ensure_face_mesh()
        if not mesh:
            return None
        x1, y1, x2, y2 = self._clip_box(box, image.shape, 0.38)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0 or min(crop.shape[:2]) < 64:
            return None
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        try:
            result = mesh.process(rgb)
        except Exception:
            return None
        if not result or not result.multi_face_landmarks:
            return None
        lm = result.multi_face_landmarks[0].landmark
        pts = np.asarray([[float(p.x), float(p.y)] for p in lm], dtype=np.float32)
        if len(pts) < 388:
            return None
        left = self._ear(pts, (33, 160, 158, 133, 153, 144))
        right = self._ear(pts, (362, 385, 387, 263, 373, 380))
        return float((left + right) * 0.5)

    @staticmethod
    def _range(values: deque) -> float:
        return float(max(values) - min(values)) if values else 0.0

    def update(self, key: str, image: np.ndarray, observation, now: float | None = None) -> LivenessDecision:
        """Continuously evaluate passive anti-spoof state for one physical track.

        BLOCKED is deliberately *recoverable*. A phone/photo attack may disappear while
        the same person remains on the same tracker. We therefore keep analysing every
        fresh frame, require a short clean hysteresis window, transition to CHECKING,
        clear stale spoof votes, and only then allow the ordinary PASS policy to run.
        This avoids the former sticky-block bug without allowing an immediate unblock.
        """
        now = float(now or time.time())
        with self._lock:
            st = self._states.get(key)
            if st is None:
                st = _LivenessState(created_at=now, status_since=now)
                self._states[key] = st

        bbox = tuple(int(v) for v in observation.bbox)
        yaw = float(getattr(observation, "yaw", 0.0))
        pitch = float(getattr(observation, "pitch", 0.0))
        st.yaw_history.append(yaw)
        st.pitch_history.append(pitch)
        st.face_size_history.append(float(min(bbox[2], bbox[3])))

        # Keep temporal texture only as telemetry; it is not a security decision.
        thumb = self._gray_thumb(image, bbox)
        if thumb is not None and st.last_thumb is not None and thumb.shape == st.last_thumb.shape:
            st.diff_history.append(float(np.mean(np.abs(thumb - st.last_thumb))))
        if thumb is not None:
            st.last_thumb = thumb

        # Context detector: explicit device containment can be strong evidence.
        # Geometry fallback remains only a weak hint unless the dedicated context
        # engine itself returns strict carrier evidence.
        device_ev = DEVICE_CONTEXT.evaluate_face(image, bbox, now=now)
        legacy_rect = self._rectangular_carrier_score(image, bbox)
        weak_geometry = min(0.42, float(legacy_rect) * 0.30)
        current_context = float(max(device_ev.risk, weak_geometry))
        st.last_device = device_ev.public()
        st.device_history.append(float(device_ev.risk))
        st.last_context_score = current_context
        st.screen_history.append(current_context)

        explicit_device = bool(
            device_ev.hard
            and device_ev.source in {"yolo", "geometry_carrier"}
            and device_ev.inside_ratio >= (0.72 if device_ev.source == "yolo" else 0.92)
            and device_ev.confidence >= (0.30 if device_ev.source == "yolo" else 0.90)
        )
        if explicit_device:
            st.hard_device_streak += 1
        else:
            st.hard_device_streak = max(0, st.hard_device_streak - 1)

        # Dedicated PAD model is the primary real-vs-print/replay signal when ready.
        pad = PAD.predict(image, bbox)
        st.last_pad = pad.public()
        if pad.ready:
            st.pad_live_history.append(float(pad.live_score))
            st.pad_spoof_history.append(float(pad.spoof_score))
            st.pad_label_history.append(str(pad.label))

        st.observations += 1
        st.last_at = now

        # Optional blink evidence stays telemetry-only. Never prompt for it.
        if now - st.last_mesh_at >= 0.60 and min(bbox[2], bbox[3]) >= 72:
            st.last_mesh_at = now
            ear = self._blink_observation(image, bbox)
            if ear is not None:
                if ear >= 0.205:
                    if st.eyes_were_open is False and st.observations > 2:
                        st.blink_seen = True
                    st.eyes_were_open = True
                elif ear <= 0.155 and st.eyes_were_open:
                    st.eyes_were_open = False

        recent_live = list(st.pad_live_history)[-PAD_WINDOW:]
        recent_spoof = list(st.pad_spoof_history)[-PAD_WINDOW:]
        pad_n = len(recent_live)
        median_live = float(np.median(recent_live)) if recent_live else 0.0
        median_spoof = float(np.median(recent_spoof)) if recent_spoof else 0.0
        current_live = float(pad.live_score) if pad.ready else 0.0
        current_spoof = float(pad.spoof_score) if pad.ready else 0.0
        live_votes = sum(1 for x in recent_live if x >= PAD_PASS_LIVE)
        strong_live_votes = sum(1 for x in recent_live if x >= PAD_STRONG_LIVE)
        spoof_votes = sum(1 for x in recent_spoof if x >= PAD_SPOOF_BLOCK)
        strong_spoof_votes = sum(1 for x in recent_spoof if x >= min(0.96, PAD_SPOOF_BLOCK + 0.08))

        # Risk shown to UI. Geometry contributes only weakly; neural PAD dominates.
        pad_risk = median_spoof if pad_n else 0.0
        context_risk = float(device_ev.risk if explicit_device else min(0.30, current_context * 0.45))
        st.risk_score = float(max(0.0, min(1.0, max(pad_risk, context_risk))))
        st.risk_history.append(st.risk_score)
        st.score = float(max(0.0, min(1.0, median_live if pad_n else 0.0)))

        # Recovery hysteresis for a previously blocked physical track. Do not freeze
        # the detector simply because BLOCKED was reached once. Strong evidence
        # immediately resets recovery. Only several clean frames over a minimum time
        # window may move BLOCKED -> CHECKING. PASS still requires the normal policy.
        if st.status == "BLOCKED":
            if pad.ready:
                clean_for_recovery = bool(
                    not explicit_device
                    and current_context <= max(ANTI_SPOOF_RECOVERY_CONTEXT_MAX, 0.20)
                    and current_live >= max(0.58, PAD_PASS_LIVE - 0.02)
                    and current_spoof <= min(0.52, PAD_SPOOF_BLOCK - 0.20)
                )
            else:
                clean_for_recovery = bool(
                    not explicit_device
                    and current_context <= ANTI_SPOOF_RECOVERY_CONTEXT_MAX
                )

            if clean_for_recovery:
                if st.recovery_clean_streak == 0:
                    st.recovery_clean_since = now
                st.recovery_clean_streak += 1
            else:
                st.recovery_clean_streak = 0
                st.recovery_clean_since = 0.0

            recovery_age = (now - st.recovery_clean_since) if st.recovery_clean_since > 0 else 0.0
            if (
                st.recovery_clean_streak >= ANTI_SPOOF_RECOVERY_CLEAN_FRAMES
                and recovery_age >= ANTI_SPOOF_RECOVERY_SEC
            ):
                st.status = "CHECKING"
                st.status_since = now
                st.reason = "Thiết bị/ảnh giả mạo đã rời khung hình · đang kiểm tra lại trước khi bật FaceID"
                st.spoof_method = ""
                st.recovery_count += 1
                st.recovery_clean_streak = 0
                st.recovery_clean_since = 0.0
                st.clean_streak = 0
                st.suspicious_streak = 0
                st.hard_device_streak = 0
                # Old spoof votes must not immediately re-latch the recovered track.
                st.pad_live_history.clear()
                st.pad_spoof_history.clear()
                st.pad_label_history.clear()
                if pad.ready:
                    st.pad_live_history.append(current_live)
                    st.pad_spoof_history.append(current_spoof)
                    st.pad_label_history.append(str(pad.label))
                st.risk_history.clear()
                st.screen_history.clear()
                st.screen_history.append(current_context)
                st.risk_score = min(st.risk_score, 0.45)
                st.score = max(st.score, 0.45 if not pad.ready else current_live)
                return LivenessDecision(
                    st.status, st.score, st.reason, "", "", current_context, st.blink_seen,
                    st.observations, "", st.risk_score, current_context,
                    decision_version="V5.3.6-temporal-pad-v3",
                    signals={
                        "pad": dict(st.last_pad or {}),
                        "device": dict(st.last_device or {}),
                        "recovery_stage": "CHECKING",
                        "recovery_count": st.recovery_count,
                        "clean_frames": ANTI_SPOOF_RECOVERY_CLEAN_FRAMES,
                    },
                )

            # Still blocked, but expose recovery progress so the UI can explain why.
            if clean_for_recovery:
                st.reason = "Không còn thấy thiết bị giả mạo · đang xác minh lại để tự phục hồi"
            return LivenessDecision(
                "BLOCKED", min(st.score, 0.18), st.reason, "", "", current_context, st.blink_seen,
                st.observations, st.spoof_method, max(st.risk_score, 0.78), current_context,
                decision_version="V5.3.6-temporal-pad-v3",
                signals={
                    "pad": dict(st.last_pad or {}),
                    "device": dict(st.last_device or {}),
                    "recovery_stage": "CLEANING" if clean_for_recovery else "BLOCKED",
                    "recovery_clean_streak": st.recovery_clean_streak,
                    "recovery_age_sec": round(recovery_age, 3),
                    "recovery_required_frames": ANTI_SPOOF_RECOVERY_CLEAN_FRAMES,
                    "recovery_required_sec": ANTI_SPOOF_RECOVERY_SEC,
                },
            )

        # Core-stable fallback: MiniFASNet is an optional strengthening layer, not a
        # single point of failure. When unavailable, FaceID can still pass after
        # repeated clean context frames, while strict device containment blocks it.
        if not pad.ready:
            if PAD_REQUIRED or not CONTEXT_FALLBACK_ENABLED:
                st.status = "CHECKING"
                st.reason = "Passive PAD chưa sẵn sàng · cấu hình hiện tại yêu cầu PAD trước FaceID"
                st.spoof_method = ""
                return LivenessDecision(
                    st.status, st.score, st.reason, "", "", current_context, st.blink_seen,
                    st.observations, "", st.risk_score, current_context,
                    signals={"pad": dict(st.last_pad or {}), "device": dict(st.last_device or {}), "fallback": False},
                )

            if explicit_device:
                st.hard_device_streak = max(1, st.hard_device_streak)
                st.clean_streak = 0
            else:
                st.clean_streak = st.clean_streak + 1 if current_context <= CONTEXT_PASS_RISK_MAX else max(0, st.clean_streak - 1)

            if explicit_device and st.hard_device_streak >= CONTEXT_BLOCK_STREAK:
                st.status = "BLOCKED"
                st.status_since = now
                st.recovery_clean_streak = 0
                st.recovery_clean_since = 0.0
                st.score = 0.08
                st.risk_score = max(st.risk_score, 0.94)
                st.reason = "Phát hiện khuôn mặt nằm trong điện thoại/ảnh thẻ/ảnh phẳng qua nhiều khung hình · check-in bị chặn"
                st.spoof_method = str(device_ev.reason or "FACE_INSIDE_PHONE_OR_PHOTO")
            elif st.clean_streak >= CONTEXT_PASS_STREAK and st.observations >= CONTEXT_PASS_STREAK:
                st.status = "PASS"
                st.status_since = now
                st.score = 0.78
                st.risk_score = min(st.risk_score, 0.30)
                st.reason = "Chống giả mạo bối cảnh đa khung đạt · FaceID hoạt động tự nhiên, không cần nhìn camera"
                st.spoof_method = ""
            else:
                st.status = "CHECKING"
                st.score = 0.50
                st.reason = "Đang kiểm tra điện thoại/ảnh thẻ qua nhiều khung hình · không yêu cầu người dùng thực hiện động tác"
                st.spoof_method = ""

            return LivenessDecision(
                st.status, st.score, st.reason, "", "", current_context, st.blink_seen,
                st.observations, st.spoof_method, st.risk_score, current_context,
                decision_version="V1-FACE-core-context-fallback-r2",
                signals={
                    "pad": dict(st.last_pad or {}), "device": dict(st.last_device or {}),
                    "fallback": True, "clean_streak": st.clean_streak,
                    "device_streak": st.hard_device_streak, "recovery_count": st.recovery_count,
                },
            )

        # A single detector/PAD frame is never enough to condemn a real employee.
        # Only an extremely clear phone/tablet containment may block immediately;
        # normal YOLO/geometry evidence and neural PAD require temporal consensus.
        very_strong_explicit = bool(
            explicit_device
            and device_ev.source == "yolo"
            and float(device_ev.inside_ratio) >= 0.90
            and float(device_ev.confidence) >= 0.75
        )
        explicit_required = 1 if very_strong_explicit else max(2, CONTEXT_BLOCK_STREAK)
        explicit_block = explicit_device and (st.hard_device_streak >= explicit_required)
        neural_block = bool(
            pad_n >= max(PAD_MIN_OBS, 5)
            and spoof_votes >= max(PAD_BLOCK_VOTES, 4)
            and median_spoof >= max(0.80, PAD_SPOOF_BLOCK - 0.02)
            and (strong_spoof_votes >= 2 or (spoof_votes >= 4 and current_spoof >= 0.97))
        )
        if explicit_block or neural_block:
            st.status = "BLOCKED"
            st.status_since = now
            st.recovery_clean_streak = 0
            st.recovery_clean_since = 0.0
            st.score = min(st.score, 0.18)
            st.risk_score = max(st.risk_score, 0.90)
            if explicit_block:
                st.reason = "Phát hiện khuôn mặt nằm trong điện thoại/máy tính bảng · FaceID và check-in bị chặn"
                st.spoof_method = str(device_ev.reason or "FACE_INSIDE_PHONE_SCREEN")
            else:
                labels = list(st.pad_label_history)[-PAD_WINDOW:]
                replay_count = sum(1 for x in labels if x == "REPLAY")
                print_count = sum(1 for x in labels if x == "PRINT")
                method = "REPLAY_SCREEN" if replay_count >= print_count else "PRINT_PHOTO"
                st.reason = "Passive PAD phát hiện trình chiếu/ảnh giả mạo lặp lại nhiều khung hình trước FaceID"
                st.spoof_method = method
            return LivenessDecision(
                st.status, st.score, st.reason, "", "", current_context, st.blink_seen,
                st.observations, st.spoof_method, st.risk_score, current_context,
                decision_version="V5.3.6-temporal-pad-v3",
                signals={
                    "pad": dict(st.last_pad or {}),
                    "device": dict(st.last_device or {}),
                    "pad_median_live": round(median_live, 4),
                    "pad_median_spoof": round(median_spoof, 4),
                    "pad_live_votes": live_votes,
                    "pad_spoof_votes": spoof_votes,
                    "explicit_device": explicit_device,
                    "recovery_stage": "BLOCKED",
                },
            )

        # PASS requires repeated clean PAD frames. Suspicious geometry alone does not
        # block a real student; it only raises the live-evidence requirement.
        required_live = PAD_STRONG_LIVE if current_context >= DEVICE_CONTEXT_SUSPECT_RISK else PAD_PASS_LIVE
        clean_current = current_live >= max(0.58, required_live - 0.16)
        enough_live = bool(
            pad_n >= PAD_MIN_OBS
            and live_votes >= PAD_PASS_VOTES
            and strong_live_votes >= 1
            and median_live >= max(0.70, required_live - 0.06)
            and clean_current
            and spoof_votes <= 1
            and not explicit_device
        )

        if enough_live:
            if st.status != "PASS":
                st.status_since = now
            st.status = "PASS"
            st.reason = "Passive PAD đa khung đạt · không cần nhìn camera hoặc thực hiện động tác"
            st.spoof_method = ""
        else:
            if st.status != "CHECKING":
                st.status_since = now
            st.status = "CHECKING"
            st.spoof_method = ""
            if current_spoof >= 0.60 or spoof_votes > 0:
                st.reason = "PAD đang kiểm tra ảnh in/video/màn hình · FaceID tạm dừng"
            elif current_context >= DEVICE_CONTEXT_SUSPECT_RISK:
                st.reason = "Có tín hiệu bối cảnh giống màn hình/ảnh · tiếp tục xác minh PAD, chưa kết luận giả mạo"
            elif st.recovery_count > 0:
                st.reason = "Đang kiểm tra lại sau cảnh báo giả mạo · FaceID sẽ tự bật khi đủ khung hình sạch"
            else:
                st.reason = "Đang xác minh Passive PAD đa khung · nhân viên không cần nhìn camera"

        return LivenessDecision(
            st.status, st.score, st.reason, "", "", current_context, st.blink_seen,
            st.observations, st.spoof_method, st.risk_score, current_context,
            decision_version="V5.3.6-temporal-pad-v3",
            signals={
                "pad": dict(st.last_pad or {}),
                "device": dict(st.last_device or {}),
                "pad_median_live": round(median_live, 4),
                "pad_median_spoof": round(median_spoof, 4),
                "pad_live_votes": live_votes,
                "pad_strong_live_votes": strong_live_votes,
                "pad_spoof_votes": spoof_votes,
                "explicit_device": explicit_device,
                "geometry_is_hint_only": True,
                "recovery_count": st.recovery_count,
            },
        )

    def reset(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)

    def purge_prefix(self, prefix: str) -> None:
        with self._lock:
            for key in list(self._states):
                if key.startswith(prefix):
                    self._states.pop(key, None)


ANTI_SPOOF = AntiSpoofEngine()
