from __future__ import annotations

import io
import threading
import time
from collections import Counter, defaultdict

import numpy as np

from .config import ENROLL_MIN_FACE_PX, ENROLL_MIN_SHARPNESS, ENROLL_MIN_TOTAL, ENROLL_SAMPLE_GAP_SEC, ENROLL_TARGET
from .crypto import decrypt_bytes, encrypt_bytes
from .db import fetchall, fetchone
from .face_core import CORE


def encode_template(arr: np.ndarray) -> bytes:
    bio = io.BytesIO()
    np.save(bio, np.asarray(arr, dtype=np.float32), allow_pickle=False)
    return encrypt_bytes(bio.getvalue())


def decode_template(blob: bytes) -> np.ndarray:
    raw = decrypt_bytes(bytes(blob))
    return np.load(io.BytesIO(raw), allow_pickle=False).astype(np.float32)


class TemplateIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._matrix: np.ndarray | None = None
        self._student_ids: np.ndarray | None = None
        self._centroids: dict[int, np.ndarray] = {}
        self._loaded_at = 0.0
        self._errors: list[str] = []

    def invalidate(self) -> None:
        with self._lock:
            self._matrix = None
            self._student_ids = None
            self._centroids = {}
            self._loaded_at = 0.0

    def load(self, force: bool = False) -> None:
        with self._lock:
            if self._matrix is not None and not force:
                return
            mats, ids, per_student = [], [], defaultdict(list)
            errors = []
            for rec in fetchall("SELECT student_id,embedding_blob FROM face_templates"):
                try:
                    arr = decode_template(rec["embedding_blob"])
                    if arr.ndim == 1:
                        arr = arr.reshape(1, -1)
                    norms = np.linalg.norm(arr, axis=1, keepdims=True)
                    arr = arr / np.maximum(norms, 1e-8)
                    mats.append(arr)
                    sid = int(rec["student_id"])
                    ids.extend([sid] * arr.shape[0])
                    per_student[sid].append(arr)
                except Exception as exc:
                    errors.append(f"student_id={rec.get('student_id')}: {exc}")
            self._matrix = np.vstack(mats).astype(np.float32) if mats else None
            self._student_ids = np.asarray(ids, dtype=np.int32) if ids else None
            self._centroids = {}
            for sid, blocks in per_student.items():
                c = np.vstack(blocks).mean(axis=0)
                c = c / max(1e-8, float(np.linalg.norm(c)))
                self._centroids[sid] = c.astype(np.float32)
            self._errors = errors
            self._loaded_at = time.time()

    def status(self) -> dict:
        self.load()
        return {
            "ready": self._matrix is not None and self._matrix.size > 0,
            "template_vectors": int(self._matrix.shape[0]) if self._matrix is not None else 0,
            "students": len(self._centroids), "decode_errors": list(self._errors),
        }

    def rank(self, query: np.ndarray, top_k: int = 2) -> list[tuple[int, float]]:
        """Robust multi-template ranking.

        Earlier releases let one unusually high template dominate a student's score.
        That is fast but can create false matches at oblique angles. V1 FACE BEST
        combines the best template, the mean of the best few templates, and the
        student centroid. A genuine student with several enrollment angles stays
        strong, while a single accidental template match is damped.
        """
        self.load()
        if self._matrix is None or self._student_ids is None:
            return []
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        q = q / max(1e-8, float(np.linalg.norm(q)))
        if self._matrix.shape[1] != q.shape[0]:
            return []
        sims = self._matrix @ q
        fused: list[tuple[int, float]] = []
        for sid in np.unique(self._student_ids):
            vals = np.asarray(sims[self._student_ids == sid], dtype=np.float32)
            if vals.size == 0:
                continue
            vals = np.sort(vals)[::-1]
            best = float(vals[0])
            topn = vals[: min(3, vals.size)]
            top_mean = float(np.mean(topn))
            centroid_score = float(self._centroids[int(sid)] @ q) if int(sid) in self._centroids else top_mean
            # Keep best-template sensitivity for angled faces, but require support
            # from other templates/centroid before the final score stays high.
            score = 0.60 * best + 0.24 * top_mean + 0.16 * centroid_score
            fused.append((int(sid), float(score)))
        fused.sort(key=lambda x: x[1], reverse=True)
        return fused[:max(1, top_k)]


INDEX = TemplateIndex()


class EnrollmentManager:
    """Easy two-pass Face-ID-style enrollment for a fixed camera.

    The user completes two natural head circles. V1.3.6 first calibrates a neutral
    frontal pose for the current user/webcam, then measures every scan angle relative
    to that baseline. Enrollment no longer forces a rigid pose checklist. Each pass automatically collects useful angular
    coverage in any order (center/left/right/up/down) and stores five quality-gated
    templates. Two passes therefore produce a 10-template multi-angle profile suited
    to oblique office-camera views. Raw frames remain transient; only encrypted SFace
    embeddings are prepared as encrypted drafts and published only after review.
    """

    POSE_VI = {
        "center": "Nhìn thẳng",
        "left": "Góc trái",
        "right": "Góc phải",
        "up": "Góc trên",
        "down": "Góc dưới",
    }
    SECTORS = ("center", "left", "right", "up", "down")
    PASS_COUNT = 2
    # Face Enrollment V2: two natural circles, five useful samples per pass.
    # The scan remains forgiving, but a pass must show horizontal + vertical head
    # travel so the final template set is useful for oblique office-camera views.
    PASS_MIN_SAMPLES = 5
    PASS_MIN_SECONDS = 1.6
    # Real laptop webcams produce smaller pitch changes than yaw changes.  The old
    # 0.10 pitch-span requirement could leave an otherwise complete scan stuck at
    # 98% forever.  Keep meaningful multi-angle coverage, but use targets that are
    # realistic for a normal seated user and a 720p webcam.
    # Enrollment V1.3.6 calibrates a neutral pose first.  Every scan angle is then
    # measured relative to that user/camera-specific baseline.  This is important
    # on laptops where the webcam is above/below eye level: a visually frontal face
    # must not be misclassified as "down" just because of camera placement.
    NEUTRAL_MIN_FRAMES = 4
    NEUTRAL_MIN_SECONDS = 0.62
    NEUTRAL_MAX_YAW = 0.115
    NEUTRAL_STABLE_YAW_STD = 0.030
    NEUTRAL_STABLE_PITCH_STD = 0.040
    CENTER_YAW = 0.040
    CENTER_PITCH = 0.032
    YAW_SECTOR = 0.055
    PITCH_SECTOR = 0.040
    HORIZONTAL_SPAN_TARGET = 0.105
    VERTICAL_SPAN_TARGET = 0.050
    VERTICAL_FALLBACK_SPAN = 0.030
    PASS_FALLBACK_SECONDS = 3.2
    TARGET = max(10, ENROLL_TARGET)
    MIN_TOTAL = max(10, ENROLL_MIN_TOTAL)
    # Duplicate protection is intentionally conservative. A warning requires
    # strong similarity to another employee and human confirmation before save.
    DUPLICATE_WARN_SCORE = 0.68
    DUPLICATE_STRONG_SCORE = 0.76

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.lock = threading.RLock()

    def reset(self, session_id: str) -> None:
        with self.lock:
            self.sessions.pop(session_id, None)

    @staticmethod
    def _geometry(face, image_shape) -> dict:
        ih, iw = image_shape[:2]
        x, y, w, h = CORE.bbox(face, image_shape)
        pts = np.asarray(face[4:14], dtype=np.float32).reshape(5, 2)
        landmarks = [
            {"x": round(float(px) / max(1.0, iw), 5), "y": round(float(py) / max(1.0, ih), 5)}
            for px, py in pts
        ]
        return {
            "frame_width": int(iw),
            "frame_height": int(ih),
            "face_bbox_norm": {
                "x": round(x / max(1.0, iw), 5),
                "y": round(y / max(1.0, ih), 5),
                "w": round(w / max(1.0, iw), 5),
                "h": round(h / max(1.0, ih), 5),
            },
            "landmarks_norm": landmarks,
        }

    @staticmethod
    def _quality_labels(q: dict) -> dict:
        sharp = float(q.get("sharpness", 0.0))
        bright = float(q.get("brightness", 0.0))
        score = float(q.get("score", 0.0))
        face_px = int(q.get("face_px", 0))
        if sharp >= max(42.0, ENROLL_MIN_SHARPNESS * 2.2):
            sharp_label = "Rất tốt"
        elif sharp >= ENROLL_MIN_SHARPNESS:
            sharp_label = "Tốt"
        else:
            sharp_label = "Mờ"
        if 70 <= bright <= 195:
            light_label = "Tốt"
        elif 46 <= bright <= 224:
            light_label = "Tạm ổn"
        elif bright < 46:
            light_label = "Thiếu sáng"
        else:
            light_label = "Quá sáng"
        if score >= 0.72:
            quality_label = "Rất tốt"
        elif score >= 0.56:
            quality_label = "Tốt"
        elif score >= 0.44:
            quality_label = "Tạm ổn"
        else:
            quality_label = "Cần chỉnh"
        size_label = "Tốt" if face_px >= ENROLL_MIN_FACE_PX * 1.18 else "Hơi xa"
        return {
            "sharp_label": sharp_label,
            "light_label": light_label,
            "quality_label": quality_label,
            "size_label": size_label,
        }

    def _new_state(self, student_id: int) -> dict:
        now = time.time()
        return {
            "student_id": int(student_id),
            "samples": [],
            "poses": defaultdict(int),
            "pass_no": 1,
            "coverage": set(),
            "pass_started": now,
            "last": 0.0,
            "last_sector": "",
            "pass_transition_until": 0.0,
            "best_photo": None,
            "best_photo_quality": -1.0,
            "complete": False,
            # Per-session neutral calibration.  Raw pose varies with webcam height,
            # so scan sectors must use deltas from this baseline rather than raw
            # YuNet landmark ratios.
            "neutral_ready": False,
            "neutral_yaw": 0.0,
            "neutral_pitch": 0.0,
            "neutral_yaws": [],
            "neutral_pitches": [],
            "neutral_started": 0.0,
        }

    @staticmethod
    def _sector(obs) -> str:
        """Use forgiving yaw/pitch thresholds for a natural circular motion."""
        yaw = float(obs.yaw)
        pitch = float(obs.pitch)
        # Prefer the dominant axis so diagonal head motion still counts naturally.
        yn = yaw / 0.085
        pn = pitch / 0.065
        if abs(yn) < 0.82 and abs(pn) < 0.82:
            return "center"
        if abs(yn) >= abs(pn):
            return "left" if yaw < 0 else "right"
        return "up" if pitch < 0 else "down"

    def _relative_values(self, state: dict, obs) -> tuple[float, float]:
        if not state.get("neutral_ready"):
            return float(obs.yaw), float(obs.pitch)
        return (
            float(obs.yaw) - float(state.get("neutral_yaw", 0.0)),
            float(obs.pitch) - float(state.get("neutral_pitch", 0.0)),
        )

    def _relative_sector(self, state: dict, obs) -> str:
        yaw, pitch = self._relative_values(state, obs)
        if abs(yaw) <= self.CENTER_YAW and abs(pitch) <= self.CENTER_PITCH:
            return "center"
        yn = yaw / max(1e-6, self.YAW_SECTOR)
        pn = pitch / max(1e-6, self.PITCH_SECTOR)
        if abs(yn) >= abs(pn):
            return "left" if yaw < 0 else "right"
        return "up" if pitch < 0 else "down"

    @staticmethod
    def _neutral_stability(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        return float(np.std(np.asarray(values, dtype=np.float32)))

    def _neutral_accept(self, state: dict, obs, now: float) -> tuple[bool, str]:
        # Only yaw has a meaningful absolute "frontal" reference.  Pitch is
        # intentionally calibrated without a hard absolute threshold because laptop
        # webcams are often above/below eye level.
        if abs(float(obs.yaw)) > self.NEUTRAL_MAX_YAW:
            state["neutral_yaws"] = []
            state["neutral_pitches"] = []
            state["neutral_started"] = 0.0
            return False, "Nhìn thẳng vào camera và giữ đầu tự nhiên trong khoảng một giây."
        if not state.get("neutral_started"):
            state["neutral_started"] = now
        state["neutral_yaws"].append(float(obs.yaw))
        state["neutral_pitches"].append(float(obs.pitch))
        state["neutral_yaws"] = state["neutral_yaws"][-self.NEUTRAL_MIN_FRAMES:]
        state["neutral_pitches"] = state["neutral_pitches"][-self.NEUTRAL_MIN_FRAMES:]
        if len(state["neutral_yaws"]) < self.NEUTRAL_MIN_FRAMES:
            return False, "Giữ nhìn thẳng vào camera một chút nữa để hiệu chuẩn góc mặt."
        elapsed = now - float(state.get("neutral_started", now))
        if elapsed < self.NEUTRAL_MIN_SECONDS:
            return False, "Giữ yên và nhìn thẳng vào camera trong khoảng một giây."
        if self._neutral_stability(state["neutral_yaws"]) > self.NEUTRAL_STABLE_YAW_STD or self._neutral_stability(state["neutral_pitches"]) > self.NEUTRAL_STABLE_PITCH_STD:
            # Keep the newest pair and restart the short hold instead of trapping the
            # user in a permanent calibration loop.
            state["neutral_yaws"] = state["neutral_yaws"][-2:]
            state["neutral_pitches"] = state["neutral_pitches"][-2:]
            state["neutral_started"] = now
            return False, "Giữ đầu ổn định và nhìn thẳng vào camera một chút nữa."
        state["neutral_yaw"] = float(np.median(np.asarray(state["neutral_yaws"], dtype=np.float32)))
        state["neutral_pitch"] = float(np.median(np.asarray(state["neutral_pitches"], dtype=np.float32)))
        state["neutral_ready"] = True
        state["pass_started"] = now
        return True, "Đã hiệu chuẩn tư thế chính diện. Bắt đầu xoay đầu chậm theo vòng quét."

    @staticmethod
    def _current_pass_samples(state: dict) -> list[dict]:
        p = int(state.get("pass_no", 1))
        return [x for x in state.get("samples", []) if int(x.get("pass_no", 1)) == p]

    def _pass_done(self, state: dict, now: float | None = None) -> bool:
        current = self._current_pass_samples(state)
        if len(current) < self.PASS_MIN_SAMPLES:
            return False
        elapsed = (now or time.time()) - float(state.get("pass_started", 0.0))
        if elapsed < self.PASS_MIN_SECONDS:
            return False
        sectors = {str(x.get("pose") or "center") for x in current}
        yaws = [float(x.get("yaw", 0.0)) for x in current]
        pitches = [float(x.get("pitch", 0.0)) for x in current]
        yaw_span = (max(yaws) - min(yaws)) if yaws else 0.0
        pitch_span = (max(pitches) - min(pitches)) if pitches else 0.0
        # A useful multi-angle pass must include left/right travel and some vertical
        # travel. We accept either labelled sectors or equivalent continuous span,
        # so the user can make one smooth circle instead of stopping at exact poses.
        horizontal = ({"left", "right"} <= sectors) or yaw_span >= self.HORIZONTAL_SPAN_TARGET
        vertical = ({"up", "down"} <= sectors) or pitch_span >= self.VERTICAL_SPAN_TARGET
        centerish = "center" in sectors or any(abs(float(x.get("yaw", 0.0))) <= self.CENTER_YAW and abs(float(x.get("pitch", 0.0))) <= self.CENTER_PITCH for x in current)

        # Anti-stall fallback: some webcams/head geometries never cross both labelled
        # vertical sectors even when the user clearly nods up/down.  If the scan has
        # enough good, non-duplicate samples, good horizontal coverage, a centered
        # sample, and a real (but smaller) vertical excursion for a few seconds,
        # accept the pass rather than parking the UI at 98% indefinitely.
        elapsed_ok = elapsed >= self.PASS_FALLBACK_SECONDS
        enough_samples = len(current) >= (self.PASS_MIN_SAMPLES + 1)
        vertical_fallback = pitch_span >= self.VERTICAL_FALLBACK_SPAN and bool(sectors & {"up", "down"})
        fallback_done = elapsed_ok and enough_samples and horizontal and centerish and vertical_fallback
        return bool((horizontal and vertical and centerish) or fallback_done)

    def _pass_progress(self, state: dict) -> float:
        if state.get("complete"):
            return 1.0
        current = self._current_pass_samples(state)
        if self._pass_done(state):
            return 1.0
        count_score = min(1.0, len(current) / float(self.PASS_MIN_SAMPLES))
        sectors = {str(x.get("pose") or "center") for x in current}
        yaws = [float(x.get("yaw", 0.0)) for x in current]
        pitches = [float(x.get("pitch", 0.0)) for x in current]
        yaw_span = (max(yaws) - min(yaws)) if yaws else 0.0
        pitch_span = (max(pitches) - min(pitches)) if pitches else 0.0
        horizontal_score = max(min(1.0, yaw_span / self.HORIZONTAL_SPAN_TARGET), 1.0 if {"left", "right"} <= sectors else min(1.0, len(sectors & {"left", "right"}) / 2.0))
        vertical_score = max(min(1.0, pitch_span / self.VERTICAL_SPAN_TARGET), 1.0 if {"up", "down"} <= sectors else min(1.0, len(sectors & {"up", "down"}) / 2.0))
        center_score = 1.0 if "center" in sectors else 0.0
        # Never display 100% until the pass is truly complete.  Cap at 94% instead
        # of producing the confusing overall 98% plateau on pass 2.
        return min(0.94, 0.50 * count_score + 0.23 * horizontal_score + 0.19 * vertical_score + 0.08 * center_score)

    def _overall_progress(self, state: dict) -> float:
        if state.get("complete"):
            return 1.0
        p = max(1, min(2, int(state.get("pass_no", 1))))
        return min(1.0, ((p - 1) + self._pass_progress(state)) / 2.0)

    def _ready(self, state: dict) -> bool:
        return bool(state.get("complete")) and len(state.get("samples", [])) >= self.MIN_TOTAL

    def _next_guide(self, state: dict) -> str:
        cov = set(state.get("coverage") or set())
        # This is only a gentle visual hint; it is not an enforced order.
        for pose in ("center", "left", "down", "right", "up"):
            if pose not in cov:
                return pose
        return "center"

    def _base_response(self, image, face, obs, *, ok: bool, message: str, accepted: bool = False) -> dict:
        geom = self._geometry(face, image.shape)
        labels = self._quality_labels(obs.quality)
        bb = geom.get("face_bbox_norm") or {}
        cx = float(bb.get("x", 0.0)) + float(bb.get("w", 0.0)) * 0.5
        cy = float(bb.get("y", 0.0)) + float(bb.get("h", 0.0)) * 0.5
        bh = float(bb.get("h", 0.0))
        center_error = min(1.0, abs(cx - 0.5) * 2.0 + abs(cy - 0.49) * 1.55)
        alignment_score = max(0.0, 1.0 - center_error)
        if bh < 0.22:
            distance_state = "too_far"
        elif bh > 0.78:
            distance_state = "too_close"
        else:
            distance_state = "good"
        return {
            "ok": bool(ok),
            "message": message,
            "accepted": bool(accepted),
            "pose": obs.pose,
            "alignment_score": round(alignment_score, 4),
            "distance_state": distance_state,
            "face_locked": bool(ok),
            "pose_label": self.POSE_VI.get(self._sector(obs), obs.pose),
            "yaw": round(float(obs.yaw), 4),
            "pitch": round(float(obs.pitch), 4),
            "quality": obs.quality,
            **labels,
            **geom,
        }

    def _response(self, state: dict, obs, q: dict, message: str, *, accepted: bool, pass_transition: bool = False) -> dict:
        pass_no = max(1, min(2, int(state.get("pass_no", 1))))
        ready = self._ready(state)
        coverage = sorted(set(state.get("coverage") or set()))
        guide = "center" if ready else self._next_guide(state)
        counts = dict(state["poses"])
        current = self._current_pass_samples(state)
        sectors = {str(x.get("pose") or "center") for x in current}
        yaws = [float(x.get("yaw", 0.0)) for x in current]
        pitches = [float(x.get("pitch", 0.0)) for x in current]
        yaw_span = (max(yaws) - min(yaws)) if yaws else 0.0
        pitch_span = (max(pitches) - min(pitches)) if pitches else 0.0
        missing = []
        if not (({"left", "right"} <= sectors) or yaw_span >= self.HORIZONTAL_SPAN_TARGET):
            missing.append("horizontal")
        if not (({"up", "down"} <= sectors) or pitch_span >= self.VERTICAL_SPAN_TARGET):
            missing.append("vertical")
        if not ("center" in sectors or any(abs(float(x.get("yaw", 0.0))) <= self.CENTER_YAW and abs(float(x.get("pitch", 0.0))) <= self.CENTER_PITCH for x in current)):
            missing.append("center")
        rel_yaw, rel_pitch = self._relative_values(state, obs)
        rel_sector = self._relative_sector(state, obs)
        return {
            "ok": True,
            "message": message,
            "accepted": bool(accepted),
            "captured": len(state["samples"]),
            "target": self.TARGET,
            "progress": self._overall_progress(state),
            "scan_pass": pass_no,
            "scan_pass_total": 2,
            "pass_progress": 1.0 if ready else self._pass_progress(state),
            "pass_transition": bool(pass_transition),
            "pose": rel_sector,
            "pose_label": self.POSE_VI.get(rel_sector, rel_sector),
            "pose_counts": counts,
            "pose_goals": {k: 2 for k in self.SECTORS},
            "coverage": coverage,
            "coverage_count": len(coverage),
            "coverage_total": 5,
            "guide": guide,
            "guide_label": self.POSE_VI.get(guide, guide),
            "quality": q,
            "ready_to_finalize": bool(ready),
            "required_total": self.MIN_TOTAL,
            "yaw": round(rel_yaw, 4),
            "pitch": round(rel_pitch, 4),
            "raw_yaw": round(float(obs.yaw), 4),
            "raw_pitch": round(float(obs.pitch), 4),
            "neutral_yaw": round(float(state.get("neutral_yaw", 0.0)), 4),
            "neutral_pitch": round(float(state.get("neutral_pitch", 0.0)), 4),
            "neutral_ready": bool(state.get("neutral_ready")),
            "yaw_span": round(yaw_span, 4),
            "pitch_span": round(pitch_span, 4),
            "missing_requirements": missing,
        }

    def frame(self, session_id: str, student_id: int, image, *, sample_gate=None) -> dict:
        student = fetchone("SELECT * FROM students WHERE id=?", (student_id,))
        if not student:
            raise ValueError("Không tìm thấy nhân viên")
        if student.get("biometric_consent_status") != "GRANTED":
            raise PermissionError("Nhân viên chưa cấp consent sinh trắc học")

        faces = CORE.detect(image, long_range=False)
        if len(faces) != 1:
            return {
                "ok": False,
                "accepted": False,
                "message": "Giữ đúng một khuôn mặt trong vùng đăng ký",
                "face_count": len(faces),
                "guide": "center",
                "progress": 0.0,
                "scan_pass": 1,
                "scan_pass_total": 2,
                "pass_progress": 0.0,
            }

        face = faces[0]
        obs = CORE.observe(image, face)
        q = obs.quality
        base = self._base_response(image, face, obs, ok=False, message="Đang căn chỉnh")
        # The shared desktop/mobile capture wrapper evaluates the existing PAD
        # engine against this observation. No second detector/embedding pipeline.
        if sample_gate is not None and not sample_gate(image, obs):
            with self.lock:
                state = self.sessions.get(session_id)
                response = self._response(state, obs, q, "Đang xác minh người thật", accepted=False) if state else {}
            return {**base, **response, "accepted": False, "ready_to_finalize": False,
                    "message": "Đang xác minh người thật"}
        bb = base.get("face_bbox_norm") or {}
        cx = float(bb.get("x", 0.0)) + float(bb.get("w", 0.0)) * 0.5
        cy = float(bb.get("y", 0.0)) + float(bb.get("h", 0.0)) * 0.5
        bh = float(bb.get("h", 0.0))
        if cx < 0.20 or cx > 0.80 or cy < 0.17 or cy > 0.83:
            return {**base, "message": "Đưa khuôn mặt vào giữa vùng FaceID", "guide": "center", "alignment": "center"}
        if bh > 0.78:
            return {**base, "message": "Lùi ra một chút để thấy đầy đủ khuôn mặt", "guide": "center", "alignment": "too_close"}
        if bh < 0.22 or q["face_px"] < ENROLL_MIN_FACE_PX:
            return {**base, "message": "Tiến gần camera hơn một chút", "guide": "center", "alignment": "too_far"}
        if q["sharpness"] < ENROLL_MIN_SHARPNESS:
            return {**base, "message": "Giữ chuyển động chậm hơn để ảnh rõ", "guide": self._sector(obs)}
        bright = float(q.get("brightness", 0.0))
        if bright < 30:
            return {**base, "message": "Khuôn mặt đang quá tối, hãy tăng ánh sáng phía trước", "guide": self._sector(obs)}
        if bright > 242:
            return {**base, "message": "Khuôn mặt đang quá sáng, tránh nguồn sáng trực tiếp", "guide": self._sector(obs)}

        with self.lock:
            state = self.sessions.setdefault(session_id, self._new_state(student_id))
            if int(state["student_id"]) != int(student_id):
                self.sessions.pop(session_id, None)
                state = self.sessions.setdefault(session_id, self._new_state(student_id))

            now = time.time()

            # Stage 0: calibrate a user/camera-specific frontal pose.  Until this is
            # complete the scan progress stays at zero, preventing the UI from
            # claiming that a circle is almost complete while the backend still
            # lacks a valid frontal reference.
            if not state.get("neutral_ready"):
                neutral_ok, neutral_message = self._neutral_accept(state, obs, now)
                if not neutral_ok:
                    response = {
                        **base,
                        "ok": True,
                        "message": neutral_message,
                        "accepted": False,
                        "captured": 0,
                        "target": self.TARGET,
                        "progress": 0.0,
                        "scan_pass": 1,
                        "scan_pass_total": 2,
                        "pass_progress": 0.0,
                        "pass_transition": False,
                        "pose": "center",
                        "pose_label": "Nhìn thẳng",
                        "pose_counts": {},
                        "pose_goals": {k: 2 for k in self.SECTORS},
                        "coverage": [],
                        "coverage_count": 0,
                        "coverage_total": 5,
                        "guide": "center",
                        "guide_label": "Nhìn thẳng",
                        "ready_to_finalize": False,
                        "required_total": self.MIN_TOTAL,
                        "neutral_ready": False,
                        "calibration_progress": min(1.0, len(state.get("neutral_yaws", [])) / float(self.NEUTRAL_MIN_FRAMES)),
                        "missing_requirements": ["neutral"],
                    }
                    return response

                # Seed pass 1 with the calibrated frontal sample.  This guarantees
                # that a genuine centered pose is represented in the final profile.
                state["samples"].append({
                    "embedding": obs.embedding,
                    "pose": "center",
                    "expected_pose": "center",
                    "quality": float(q["score"]),
                    "sharpness": float(q.get("sharpness", 0.0)),
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "raw_yaw": float(obs.yaw),
                    "raw_pitch": float(obs.pitch),
                    "pass_no": 1,
                })
                state["poses"]["center"] += 1
                state["coverage"].add("center")
                state["last"] = now
                state["last_sector"] = "center"
                photo_quality = float(q.get("score", 0.0)) + min(0.25, float(q.get("sharpness", 0.0)) / 600.0)
                try:
                    crop = CORE.face_crop(image, obs.bbox, pad=0.58)
                    if crop is not None and getattr(crop, "size", 0):
                        state["best_photo"] = crop.copy()
                        state["best_photo_quality"] = photo_quality
                except Exception:
                    pass
                response = self._response(state, obs, q, neutral_message, accepted=True)
                response.update({k: v for k, v in base.items() if k not in response})
                response["ok"] = True
                return response

            if now < float(state.get("pass_transition_until", 0.0)):
                response = self._response(state, obs, q, "Vòng 1 hoàn tất. Đưa mặt về giữa để quét vòng 2.", accepted=False, pass_transition=True)
                response.update({k: v for k, v in base.items() if k not in response})
                response["ok"] = True
                return response

            if self._ready(state):
                response = self._response(state, obs, q, "Đã hoàn tất hai vòng quét", accepted=False)
                response.update({k: v for k, v in base.items() if k not in response})
                response["ok"] = True
                return response

            sector = self._relative_sector(state, obs)
            rel_yaw, rel_pitch = self._relative_values(state, obs)
            current = self._current_pass_samples(state)
            gap_ok = (not state["samples"]) or (now - float(state.get("last", 0.0)) >= ENROLL_SAMPLE_GAP_SEC)
            accepted = False

            current_has_center = any(abs(float(x.get("yaw", 0.0))) <= self.CENTER_YAW and abs(float(x.get("pitch", 0.0))) <= self.CENTER_PITCH for x in current)
            center_confirmation_needed = int(state.get("pass_no", 1)) == 2 and not current_has_center
            # V4 anti-stall: pass 2 may already contain the normal sample cap before
            # the user returns to frontal. Permit one additional center sample so the
            # UI cannot become permanently stuck near completion.
            can_take_more = len(current) < max(self.PASS_MIN_SAMPLES + 1, self.TARGET // 2 + 1) or center_confirmation_needed
            if gap_ok and can_take_more:
                # Accept samples by continuous head-angle distance, not by a rigid
                # one-sample-per-direction checklist. This makes one smooth circular
                # motion enough for each pass while still rejecting near duplicates.
                angular_ok = not current
                if current:
                    def angle_distance(sample: dict) -> float:
                        dy = (float(rel_yaw) - float(sample.get("yaw", 0.0))) / max(1e-6, self.YAW_SECTOR)
                        dp = (float(rel_pitch) - float(sample.get("pitch", 0.0))) / max(1e-6, self.PITCH_SECTOR)
                        return float((dy * dy + dp * dp) ** 0.5)
                    angular_ok = min(angle_distance(x) for x in current) >= 0.42
                duplicate = False
                if state["samples"]:
                    similarity = max(float(x["embedding"] @ obs.embedding) for x in state["samples"][-5:])
                    duplicate = similarity > 0.99945 and now - float(state.get("last", 0.0)) < 0.70
                # A missing frontal confirmation in pass 2 is semantically useful
                # even if its embedding resembles the earlier calibrated frontal.
                if center_confirmation_needed and sector == "center":
                    angular_ok = True
                    duplicate = False
                if angular_ok and not duplicate:
                    state["samples"].append({
                        "embedding": obs.embedding,
                        "pose": sector,
                        "expected_pose": sector,
                        "quality": float(q["score"]),
                        "sharpness": float(q.get("sharpness", 0.0)),
                        "yaw": float(rel_yaw),
                        "pitch": float(rel_pitch),
                        "raw_yaw": float(obs.yaw),
                        "raw_pitch": float(obs.pitch),
                        "pass_no": int(state["pass_no"]),
                    })
                    state["poses"][sector] += 1
                    state["coverage"].add(sector)
                    state["last"] = now
                    state["last_sector"] = sector
                    # Keep only one human-readable portrait in RAM during enrollment.
                    # Raw scan frames are still transient; the selected best crop is
                    # written outside PostgreSQL only after reviewed approval.
                    photo_quality = float(q.get("score", 0.0)) + min(0.25, float(q.get("sharpness", 0.0)) / 600.0)
                    if photo_quality > float(state.get("best_photo_quality", -1.0)):
                        try:
                            crop = CORE.face_crop(image, obs.bbox, pad=0.58)
                            if crop is not None and getattr(crop, "size", 0):
                                state["best_photo"] = crop.copy()
                                state["best_photo_quality"] = photo_quality
                        except Exception:
                            pass
                    accepted = True

            pass_transition = False
            if self._pass_done(state, now):
                if int(state["pass_no"]) == 1:
                    state["pass_no"] = 2
                    state["coverage"] = set()
                    state["pass_started"] = now
                    state["pass_transition_until"] = now + 0.75
                    pass_transition = True
                    message = "Vòng 1 hoàn tất. Quét thêm một vòng để xác nhận."
                else:
                    state["complete"] = True
                    message = "Hai vòng quét đã hoàn tất. Sẵn sàng gửi FaceID để duyệt."
            elif accepted:
                message = "Đã lấy được một góc tốt. Tiếp tục xoay đầu chậm theo vòng tròn."
            else:
                message = "Tiếp tục xoay đầu chậm theo vòng tròn; AI tự chọn các góc tốt."

            response = self._response(state, obs, q, message, accepted=accepted, pass_transition=pass_transition)
            response.update({k: v for k, v in base.items() if k not in response})
            response["ok"] = True
            response["accepted"] = accepted
            return response

    def _duplicate_candidate(self, samples: list[dict], student_id: int, *, conn=None) -> dict | None:
        """Return a likely existing employee for human review before enrollment.

        Re-enrolling the same employee is excluded. We compare the new multi-angle
        centroid against every other employee and blend centroid support with the
        best individual template match so one accidental frame cannot dominate.
        """
        if not samples:
            return None
        try:
            new_arr = np.vstack([np.asarray(x["embedding"], dtype=np.float32).reshape(-1) for x in samples])
            new_arr = new_arr / np.maximum(np.linalg.norm(new_arr, axis=1, keepdims=True), 1e-8)
            new_centroid = new_arr.mean(axis=0)
            new_centroid = new_centroid / max(1e-8, float(np.linalg.norm(new_centroid)))
        except Exception:
            return None
        best: dict | None = None
        sql = "SELECT student_id,embedding_blob FROM face_templates WHERE student_id<>?"
        records = fetchall(sql, (int(student_id),)) if conn is None else [dict(row) for row in conn.execute(sql, (int(student_id),)).fetchall()]
        for rec in records:
            try:
                sid = int(rec.get("student_id") or 0)
                arr = decode_template(rec["embedding_blob"])
                if arr.ndim == 1:
                    arr = arr.reshape(1, -1)
                arr = arr.astype(np.float32)
                arr = arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-8)
                if arr.shape[1] != new_centroid.shape[0]:
                    continue
                existing_centroid = arr.mean(axis=0)
                existing_centroid = existing_centroid / max(1e-8, float(np.linalg.norm(existing_centroid)))
                centroid_score = float(existing_centroid @ new_centroid)
                best_template = float(np.max(arr @ new_centroid))
                # Cross-check several new angles against the existing template set.
                cross = arr @ new_arr.T
                support = float(np.mean(np.sort(np.max(cross, axis=0))[-min(3, new_arr.shape[0]):]))
                score = 0.46 * centroid_score + 0.34 * best_template + 0.20 * support
                if best is None or score > float(best.get("score") or -1.0):
                    student_sql = "SELECT id,student_code,full_name FROM students WHERE id=?"
                    if conn is None:
                        student = fetchone(student_sql, (sid,)) or {}
                    else:
                        row = conn.execute(student_sql, (sid,)).fetchone()
                        student = dict(row) if row is not None else {}
                    best = {
                        "student_id": sid,
                        "student_code": str(student.get("student_code") or ""),
                        "full_name": str(student.get("full_name") or "Nhân viên khác"),
                        "score": round(score, 4),
                        "strong": bool(score >= self.DUPLICATE_STRONG_SCORE),
                    }
            except Exception:
                continue
        if best and float(best.get("score") or 0.0) >= self.DUPLICATE_WARN_SCORE:
            return best
        return None

    def prepare_draft(self, session_id: str, student_id: int) -> dict:
        """Prepare encrypted review material; never modify active templates."""
        student = fetchone("SELECT biometric_consent_status FROM students WHERE id=?", (student_id,))
        if not student or student.get("biometric_consent_status") != "GRANTED":
            raise PermissionError("Nhân viên chưa cấp consent sinh trắc học")
        with self.lock:
            state = self.sessions.get(session_id)
            if not state or int(state.get("student_id", -1)) != int(student_id):
                raise ValueError("Chưa có phiên đăng ký FaceID")
            samples = list(state["samples"])
            best_photo = state.get("best_photo")
            if best_photo is not None:
                try:
                    best_photo = best_photo.copy()
                except Exception:
                    best_photo = None
            ready = self._ready(state)
        if not ready or len(samples) < self.MIN_TOTAL:
            raise ValueError("Cần hoàn thành đủ hai vòng quét trước khi lưu FaceID")

        # Keep every quality-gated multi-angle sample collected during the two passes.
        # Face Enrollment V2 normally stores 10 vectors (5 per pass) to improve
        # recognition when office staff are seated at oblique angles.
        chosen = samples[: max(self.MIN_TOTAL, min(self.TARGET, len(samples)))]
        duplicate = self._duplicate_candidate(chosen, student_id)
        template = np.vstack([x["embedding"] for x in chosen]).astype(np.float32)
        blob = encode_template(template)
        preview_blob = None
        if best_photo is not None:
            import cv2
            ok, encoded = cv2.imencode(".jpg", best_photo, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            if ok:
                if encoded.nbytes > 2 * 1024 * 1024:
                    raise ValueError("Ảnh xem trước vượt giới hạn 2 MiB")
                preview_blob = encrypt_bytes(encoded.tobytes())
        counts = Counter(x["expected_pose"] for x in chosen)
        return {
            "template_blob": blob,
            "preview_blob": preview_blob,
            "pose_count": int(template.shape[0]),
            "quality": {"ready": True, "scan_passes": 2, "pose_counts": dict(counts),
                        "target": self.TARGET, "mode": "two-natural-circles",
                        "minimum_sample_quality": round(min(float(x["quality"]) for x in chosen), 4)},
            "duplicate": duplicate,
        }

    def finalize(self, session_id: str, student_id: int, *, confirm_duplicate: bool = False) -> dict:
        # Kept as a preparation-only compatibility entry point. Publication is
        # exclusively the reviewed QR/desktop transaction, including overrides.
        return self.prepare_draft(session_id, student_id)


ENROLLMENT = EnrollmentManager()


def recheck_prepared_duplicate(template_blob: bytes, student_id: int, conn) -> dict | None:
    """Use active rows in the approval transaction, never a cached index."""
    template = decode_template(template_blob)
    if template.ndim != 2 or template.shape[0] < ENROLLMENT.MIN_TOTAL or not np.isfinite(template).all():
        raise ValueError("Bản nháp FaceID không hợp lệ")
    return ENROLLMENT._duplicate_candidate([{"embedding": row} for row in template], student_id, conn=conn)
