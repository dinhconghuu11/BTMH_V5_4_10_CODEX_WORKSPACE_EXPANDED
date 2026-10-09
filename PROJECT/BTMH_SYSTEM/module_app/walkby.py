from __future__ import annotations

import itertools
import math
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

import numpy as np

from .config import (
    ANTI_SPOOF_ENABLED,
    FACE_MIN_PX,
    LONG_RANGE_EVERY,
    MAX_FACES,
    MAX_SAMPLES_PER_TRACK,
    ONE_SHOT_CONF,
    ONE_SHOT_MARGIN,
    QUICK_REARM_SEC,
    SAMPLE_MIN_GAP_SEC,
    THREE_SHOT_CONF,
    THREE_SHOT_MARGIN,
    TRACK_DIST_MAX,
    TRACK_IOU_MIN,
    IDENTITY_REVERIFY_SEC,
    IDENTITY_REVERIFY_SCORE,
    IDENTITY_REVERIFY_MARGIN,
    IDENTITY_REVERIFY_MISMATCHES,
    IDENTITY_OWNER_GRACE_SEC,
    TWO_SHOT_CONF,
    TWO_SHOT_MARGIN,
    UNKNOWN_MIN_SCORE,
)
from .anti_spoof import ANTI_SPOOF
from .db import add_event, add_spoof_event, add_unknown_event, fetchone, utc_now
from .production_ops import apply_successful_checkin, apply_rejected_checkin, persist_recognition_evidence
from .face_core import CORE, FaceObservation
from .registry import INDEX
from .visitor import touch_unknown as touch_visitor_unknown, close_track as close_visitor_track
from .ai_pipeline_v550 import AsyncInferencePipeline, InferenceJob, MAX_RESULT_AGE_SEC


@dataclass
class Track:
    id: int
    bbox: tuple[int, int, int, int]
    first_seen: float
    last_seen: float
    center: tuple[float, float]
    velocity: tuple[float, float] = (0.0, 0.0)
    last_capture_at: float = 0.0
    recognized: bool = False
    recognized_student_id: int | None = None
    recognized_confidence: float = 0.0
    recognized_at: float = 0.0
    # Identity is allowed to become a candidate before liveness passes.  Only after
    # anti-spoof PASS do we set recognized=True and persist a successful event.
    candidate_student_id: int | None = None
    candidate_confidence: float = 0.0
    candidate_reason: str = ""
    candidate_student: dict | None = None
    spoof_blocked: bool = False
    spoof_emitted: bool = False
    liveness: dict = field(default_factory=dict)
    samples: deque = field(default_factory=lambda: deque(maxlen=MAX_SAMPLES_PER_TRACK))
    # V5.3.6 Recognition V2 keeps a short, quality-gated embedding window per
    # physical track. Identity is ranked from the fused vector rather than one
    # unlucky oblique/blurred frame. Raw images are never stored here.
    identity_vectors: deque = field(default_factory=lambda: deque(maxlen=6))
    quality_gate_ok: bool = False
    quality_wait_reason: str = "Đang chờ khung hình khuôn mặt rõ hơn"
    best_match_score: float = 0.0
    best_match_student_id: int | None = None
    best_snapshot: str = ""
    best_quality: float = 0.0
    best_pose: str = ""
    best_shots: list[dict] = field(default_factory=list)
    best_shots_revision: int = 0
    visitor_synced_revision: int = -1
    last_best_shot_at: float = 0.0
    last_sample_at: float = 0.0
    processed: int = 0
    unknown: bool = False
    unknown_emitted: bool = False
    unknown_since: float = 0.0
    unknown_event_id: int = 0
    # R2 identity guard: periodically verify that a locked name still belongs to
    # the face currently assigned to this track. This reduces name swaps in crowds.
    last_identity_verify_at: float = 0.0
    identity_mismatch_streak: int = 0
    identity_conflict_student_id: int | None = None
    identity_last_verify_score: float = 0.0
    identity_guard_state: str = "IDLE"
    pad_completed_seq: int = -1
    pad_submitted_seq: int = -1
    pad_capture_at: float = 0.0
    identity_completed_seq: int = -1
    candidate_seq: int = -1
    identity_result: object = None


class WalkByEngine:
    """Continuous detector/tracker with FaceID once per physical presence.

    A person can remain in front of the camera without generating duplicate events.
    After the face is truly absent for QUICK_REARM_SEC the track is dropped, so a
    later re-entry is recognized again automatically.
    """

    def __init__(self, *, max_tracks=None, inference_wrapper=None) -> None:
        self._sessions: dict[str, dict] = {}
        self._next = itertools.count(1)
        self._lock = threading.RLock()
        self._generations = itertools.count(1)
        self._pipeline = AsyncInferencePipeline(self._infer_pad, self._infer_identity,
                                                discard_pad=lambda job: ANTI_SPOOF.reset(self._pad_key(job)))
        self._max_tracks = None
        self._resource_limited = False
        if max_tracks is not None:
            self.configure_resource_limits(max_tracks, inference_wrapper)

    def configure_resource_limits(self, max_tracks, inference_wrapper=None):
        """Bound scheduling only; identity/PAD decisions and thresholds are unchanged."""
        with self._lock:
            self._max_tracks = max(1, int(max_tracks))
            if inference_wrapper is not None and not self._resource_limited:
                self._pipeline.pad._infer = inference_wrapper("pad", self._infer_pad)
                self._pipeline.faceid._infer = inference_wrapper("faceid", self._infer_identity)
                self._resource_limited = True

    @staticmethod
    def _pad_key(job: InferenceJob) -> str:
        return f"{job.session_id}:g{job.epoch}:{job.track_id}"

    @classmethod
    def _infer_pad(cls, job: InferenceJob):
        # Anti-spoof owns its temporal state; each generation has a separate key.
        # No worker can mutate a WalkBy track or write attendance/events.
        return ANTI_SPOOF.update(cls._pad_key(job), job.image, job.observation, job.observed_at)

    def _infer_identity(self, job: InferenceJob):
        embedding = CORE.embedding(job.image, job.observation.face)
        evidence = None
        provider = getattr(job.observation, "_evidence_provider", None)
        if provider is not None:
            try:
                evidence = provider(source_epoch=job.source_epoch, capture_at=job.captured_at,
                                    image=job.image, observation=job.observation)
            except Exception:
                pass
        return {"embedding": embedding, "evidence": evidence}

    def _invalidate_state(self, session_id: str, state: dict) -> None:
        generation = state.get("generation")
        if generation is not None:
            self._pipeline.invalidate(session_id, generation)
        ANTI_SPOOF.purge_prefix(f"{session_id}:")

    def shutdown(self, session_id: str | None = None) -> None:
        with self._lock:
            selected = list(self._sessions) if session_id is None else [session_id]
            for selected_id in selected:
                state = self._sessions.pop(selected_id, None)
                if state is not None:
                    self._invalidate_state(selected_id, state)
        self._pipeline.shutdown()

    @staticmethod
    def _freeze_observation(obs: FaceObservation, provider=None) -> FaceObservation:
        frozen = FaceObservation(np.asarray(obs.face).copy(), tuple(obs.bbox), None,
                                 dict(obs.quality or {}), obs.pose, obs.yaw, obs.pitch)
        frozen.face.setflags(write=False)
        frozen._evidence_provider = provider
        return frozen

    def _valid_result(self, result, state: dict, tr: Track, source_epoch: int) -> bool:
        job = result.job
        age = time.perf_counter() - job.captured_at
        return bool(job.epoch == state.get("generation") and job.source_epoch == source_epoch
                    and job.track_id == tr.id and job.observed_at >= tr.first_seen
                    and 0.0 <= age <= MAX_RESULT_AGE_SEC)

    @staticmethod
    def _center(box: tuple[int, int, int, int]) -> tuple[float, float]:
        x, y, w, h = box
        return x + w * 0.5, y + h * 0.5

    @staticmethod
    def _update_best_shots(tr: Track, image, obs: FaceObservation, now: float) -> None:
        """Keep up to three good visitor/recognition crops without encoding every frame.

        V3 deliberately stores a small Best Shots set instead of every detected frame.
        Quality remains the primary ranking signal; the temporal gap prevents three
        byte-identical captures from one instant.
        """
        q = obs.quality or {}
        score = float(q.get("score") or 0.0)
        if score <= 0.0 or int(q.get("face_px") or 0) < max(40, int(FACE_MIN_PX * 0.75)):
            return
        shots = list(tr.best_shots or [])
        before = list(shots)
        worst = min((float(x.get("quality") or 0.0) for x in shots), default=-1.0)
        enough_gap = (now - float(tr.last_best_shot_at or 0.0)) >= 0.30
        should_capture = (len(shots) < 3 and enough_gap) or (len(shots) >= 3 and enough_gap and score > worst + 0.035)
        if not should_capture:
            return
        try:
            crop = CORE.face_crop(image, obs.bbox)
            data_url = CORE.encode_jpeg_data_url(crop, 88)
        except Exception:
            return
        if not data_url:
            return
        candidate = {
            "data_url": data_url,
            "quality": score,
            "pose": str(obs.pose or "CENTER").upper(),
            "captured_at": utc_now(),
        }
        # Prefer pose diversity. A sharper image can replace the same-pose image;
        # a genuinely new pose is preferred over keeping three near-identical frames.
        same_pose = next((i for i, x in enumerate(shots) if str(x.get("pose") or "CENTER").upper() == candidate["pose"]), None)
        if same_pose is not None:
            if score > float(shots[same_pose].get("quality") or 0.0) + 0.01:
                shots[same_pose] = candidate
        elif len(shots) < 3:
            shots.append(candidate)
        else:
            pose_counts = {}
            for x in shots:
                p = str(x.get("pose") or "CENTER").upper(); pose_counts[p] = pose_counts.get(p, 0) + 1
            duplicate_indexes = [i for i, x in enumerate(shots) if pose_counts.get(str(x.get("pose") or "CENTER").upper(), 0) > 1]
            pool = duplicate_indexes or list(range(len(shots)))
            weakest = min(pool, key=lambda i: float(shots[i].get("quality") or 0.0))
            if duplicate_indexes or score > float(shots[weakest].get("quality") or 0.0) + 0.035:
                shots[weakest] = candidate
        shots.sort(key=lambda x: float(x.get("quality") or 0.0), reverse=True)
        if shots[:3] == before:
            return
        tr.best_shots = shots[:3]
        tr.last_best_shot_at = now
        tr.best_shots_revision += 1
        if tr.best_shots:
            best = tr.best_shots[0]
            tr.best_snapshot = str(best.get("data_url") or "")
            tr.best_quality = float(best.get("quality") or score)
            tr.best_pose = str(best.get("pose") or obs.pose or "")

    @staticmethod
    def _iou(a, b) -> float:
        ax, ay, aw, ah = map(float, a)
        bx, by, bw, bh = map(float, b)
        x1, y1 = max(ax, bx), max(ay, by)
        x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    @staticmethod
    def _minimum_assignment(costs: list[list[float]]) -> list[int]:
        """Rectangular minimum-cost matching; rows <= columns, no dependency."""
        if not costs:
            return []
        n, m = len(costs), len(costs[0])
        u, v = [0.] * (n + 1), [0.] * (m + 1)
        owner, previous = [0] * (m + 1), [0] * (m + 1)
        for row in range(1, n + 1):
            owner[0] = row
            col = 0
            distance, used = [float("inf")] * (m + 1), [False] * (m + 1)
            while True:
                used[col] = True
                current, delta, next_col = owner[col], float("inf"), 0
                for candidate in range(1, m + 1):
                    if used[candidate]:
                        continue
                    reduced = costs[current - 1][candidate - 1] - u[current] - v[candidate]
                    if reduced < distance[candidate]:
                        distance[candidate], previous[candidate] = reduced, col
                    if distance[candidate] < delta:
                        delta, next_col = distance[candidate], candidate
                for candidate in range(m + 1):
                    if used[candidate]:
                        u[owner[candidate]] += delta
                        v[candidate] -= delta
                    else:
                        distance[candidate] -= delta
                col = next_col
                if owner[col] == 0:
                    break
            while col:
                parent = previous[col]
                owner[col] = owner[parent]
                col = parent
        assignment = [-1] * n
        for col in range(1, m + 1):
            if owner[col]:
                assignment[owner[col] - 1] = col - 1
        return assignment

    def _assign(self, tracks: dict[int, Track], observations: list[FaceObservation], now: float,
                *, capture_at: float | None = None) -> list[tuple[Track, FaceObservation]]:
        observed_at = float(capture_at if capture_at is not None else now)
        result: list[tuple[Track, FaceObservation]] = []
        # Large/clear faces first, then less-processed tracks get a chance at FaceID.
        observations = sorted(
            observations,
            key=lambda o: (float(o.quality.get("score", 0.0)), o.bbox[2] * o.bbox[3]),
            reverse=True,
        )
        track_ids = sorted(tracks)
        costs = []
        for obs in observations:
            box = obs.bbox
            cx, cy = self._center(box)
            row = []
            for tid in track_ids:
                tr = tracks[tid]
                dt = max(0.0, min(1.2, observed_at - tr.last_capture_at if tr.last_capture_at else now - tr.last_seen))
                pred_x = tr.center[0] + tr.velocity[0] * dt
                pred_y = tr.center[1] + tr.velocity[1] * dt
                scale = max(28.0, 0.5 * (max(box[2], box[3]) + max(tr.bbox[2], tr.bbox[3])))
                dist = math.hypot(cx - pred_x, cy - pred_y) / scale
                predicted_box = (pred_x - tr.bbox[2] * .5, pred_y - tr.bbox[3] * .5, tr.bbox[2], tr.bbox[3])
                overlap = self._iou(box, predicted_box)
                size_sim = min(box[2] * box[3], tr.bbox[2] * tr.bbox[3]) / max(1.0, max(box[2] * box[3], tr.bbox[2] * tr.bbox[3]))
                # A seated/crouching transition can move the face vertically by more
                # than one face height. Keep a short grace window before declaring a new
                # physical person, but still choose the lowest-cost track in crowds.
                recent_gap = max(0.0, now - tr.last_seen)
                dist_gate = TRACK_DIST_MAX + (0.75 if recent_gap <= 0.80 else 0.0)
                if overlap < TRACK_IOU_MIN and dist > dist_gate:
                    row.append(1e9)
                    continue
                gap_penalty = min(0.45, recent_gap * 0.30)
                cost = dist - 1.35 * overlap - 0.18 * size_sim + gap_penalty
                row.append(cost)
            # Each observation has an unmatched column. Global one-to-one matching
            # stops a clear face from taking another person's only good match.
            costs.append(row + [1e4] * len(observations))
        assignment = self._minimum_assignment(costs)
        for obs, column in zip(observations, assignment):
            box = obs.bbox
            cx, cy = self._center(box)
            best_id = track_ids[column] if 0 <= column < len(track_ids) else None
            if best_id is None:
                if self._max_tracks is not None and len(tracks) >= self._max_tracks:
                    continue
                tid = next(self._next)
                tr = Track(tid, box, now, now, (cx, cy))
                tr.last_capture_at = observed_at
                tracks[tid] = tr
            else:
                tr = tracks[best_id]
                dt = max(0.02, observed_at - tr.last_capture_at if tr.last_capture_at else now - tr.last_seen)
                obs_vx = (cx - tr.center[0]) / dt
                obs_vy = (cy - tr.center[1]) / dt
                alpha = 0.55
                tr.velocity = (
                    (1.0 - alpha) * tr.velocity[0] + alpha * obs_vx,
                    (1.0 - alpha) * tr.velocity[1] + alpha * obs_vy,
                )
                tr.bbox = box
                tr.center = (cx, cy)
                tr.last_seen = now
                tr.last_capture_at = observed_at
            result.append((tr, obs))
        return result

    @staticmethod
    def _identity_owner(tracks: dict[int, Track], student_id: int, exclude_track_id: int, now: float) -> Track | None:
        """Return another live track that already owns this identity.

        One student cannot be simultaneously committed to two physical tracks from
        the same camera. This is a presentation/check-in safety guard, not a biometric
        decision: candidates may continue collecting evidence until the owner leaves.
        """
        sid = int(student_id)
        for other in tracks.values():
            if other.id == int(exclude_track_id) or other.spoof_blocked:
                continue
            if not other.recognized or int(other.recognized_student_id or -1) != sid:
                continue
            if now - float(other.last_seen or 0.0) <= IDENTITY_OWNER_GRACE_SEC:
                return other
        return None

    @staticmethod
    def _drop_locked_identity(tr: Track, *, now: float, conflict_sid: int | None = None) -> None:
        tr.recognized = False
        tr.recognized_student_id = None
        tr.recognized_confidence = 0.0
        tr.recognized_at = 0.0
        tr.candidate_student_id = None
        tr.candidate_confidence = 0.0
        tr.candidate_reason = ""
        tr.candidate_student = None
        tr.samples.clear()
        tr.identity_vectors.clear()
        tr.best_match_score = 0.0
        tr.best_match_student_id = None
        tr.processed = 0
        tr.last_sample_at = now
        tr.unknown = False
        tr.unknown_emitted = False
        tr.unknown_since = 0.0
        tr.unknown_event_id = 0
        tr.identity_conflict_student_id = conflict_sid
        tr.identity_guard_state = "REACQUIRE"

    @staticmethod
    def _decision(samples: list[dict]) -> tuple[int | None, float, str]:
        """Identity consensus after PAD PASS.

        Recognition is intentionally multi-frame by default. A one-shot decision is
        allowed only for an exceptionally strong, high-quality, well-separated
        match. This reduces wrong-person check-ins without forcing anyone to stop.
        """
        if not samples:
            return None, 0.0, "collecting"
        latest = samples[-1]
        if (
            latest["score"] >= ONE_SHOT_CONF
            and latest["margin"] >= ONE_SHOT_MARGIN
            and latest["quality"] >= 0.62
        ):
            return int(latest["student_id"]), float(latest["score"]), "very-strong-one-shot"

        if len(samples) >= 2:
            a, b = samples[-2:]
            if a["student_id"] == b["student_id"]:
                weights = np.asarray([max(0.35, float(a["quality"])), max(0.35, float(b["quality"]))], dtype=np.float32)
                scores = np.asarray([float(a["score"]), float(b["score"])], dtype=np.float32)
                margins = np.asarray([float(a["margin"]), float(b["margin"])], dtype=np.float32)
                avg_score = float(np.average(scores, weights=weights))
                avg_margin = float(np.average(margins, weights=weights))
                if avg_score >= TWO_SHOT_CONF and avg_margin >= TWO_SHOT_MARGIN:
                    return int(b["student_id"]), avg_score, "two-frame-consensus"

        if len(samples) >= 4:
            recent = samples[-4:]
            counts = Counter(int(x["student_id"]) for x in recent)
            sid, count = counts.most_common(1)[0]
            chosen = [x for x in recent if int(x["student_id"]) == sid]
            if count >= 3:
                weights = np.asarray([max(0.30, float(x["quality"])) for x in chosen], dtype=np.float32)
                avg_score = float(np.average([float(x["score"]) for x in chosen], weights=weights))
                avg_margin = float(np.average([float(x["margin"]) for x in chosen], weights=weights))
                if avg_score >= THREE_SHOT_CONF and avg_margin >= THREE_SHOT_MARGIN:
                    return int(sid), avg_score, "three-of-four-consensus"

        return None, 0.0, "collecting"

    @staticmethod
    def _recognition_quality_gate(obs: FaceObservation, *, for_pad: bool = False) -> tuple[bool, str]:
        """Treat poor/oblique frames as uncertainty, never as identity/spoof truth."""
        q = obs.quality or {}
        face_px = int(q.get("face_px") or 0)
        score = float(q.get("score") or 0.0)
        sharp = float(q.get("sharpness") or 0.0)
        bright = float(q.get("brightness") or 0.0)
        yaw = abs(float(getattr(obs, "yaw", 0.0) or 0.0))
        pitch = abs(float(getattr(obs, "pitch", 0.0) or 0.0))
        if face_px < max(48, FACE_MIN_PX) or not bool(q.get("usable", True)):
            return False, "Khuôn mặt còn nhỏ hoặc chưa rõ · AI đang chờ khung hình tốt hơn"
        if for_pad:
            if yaw > 0.38 or pitch > 0.32:
                return False, "Góc mặt quá nghiêng để kiểm tra người thật · chưa kết luận giả mạo"
            if score < 0.42 or sharp < 8.0:
                return False, "Khung hình chưa đủ nét để kiểm tra người thật · đang quan sát tiếp"
            if bright < 32.0 or bright > 232.0:
                return False, "Ánh sáng khuôn mặt chưa ổn định · đang quan sát tiếp"
            return True, ""
        if yaw > 0.30:
            return False, "Góc mặt đang quá nghiêng · FaceID chờ góc rõ hơn, chưa kết luận danh tính"
        if pitch > 0.27:
            return False, "Góc nhìn dọc chưa phù hợp · FaceID đang chờ khung hình rõ hơn"
        if score < 0.50 or sharp < 12.0:
            return False, "Khuôn mặt chưa đủ nét · FaceID đang tự chọn frame tốt hơn"
        if bright < 38.0 or bright > 224.0:
            return False, "Ánh sáng khuôn mặt chưa phù hợp · FaceID đang chờ frame tốt hơn"
        return True, ""

    @staticmethod
    def _fused_identity_vector(items: list[dict]) -> np.ndarray | None:
        """Quality-weighted temporal embedding fusion for one physical track."""
        valid = [x for x in items if x.get("embedding") is not None]
        if not valid:
            return None
        arr = np.vstack([np.asarray(x["embedding"], dtype=np.float32).reshape(1, -1) for x in valid])
        weights = np.asarray([max(0.35, min(1.0, float(x.get("quality") or 0.0))) for x in valid], dtype=np.float32)
        fused = np.average(arr, axis=0, weights=weights).astype(np.float32)
        norm = float(np.linalg.norm(fused))
        return None if norm <= 1e-8 else fused / norm

    def _session(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "tracks": {}, "sample_seq": 0, "no_face_streak": 0, "last_face_count": 0,
                "frame_width": 0, "frame_height": 0,
                "generation": next(self._generations), "source_epoch": None,
            }
        return self._sessions[session_id]

    @staticmethod
    def _rescale_tracks_for_frame(state: dict, image) -> None:
        """Preserve physical tracks when the AI frame resolution changes.

        UI navigation/Classroom mode must never create a new person just because the
        inference frame changed size. This keeps FaceID/liveness state tied to the
        physical presence rather than to a pixel coordinate system.
        """
        ih, iw = image.shape[:2]
        old_w = int(state.get("frame_width") or 0)
        old_h = int(state.get("frame_height") or 0)
        if old_w > 0 and old_h > 0 and (old_w != iw or old_h != ih):
            sx = iw / float(old_w)
            sy = ih / float(old_h)
            tracks: dict[int, Track] = state.get("tracks", {})
            for tr in tracks.values():
                x, y, w, h = tr.bbox
                tr.bbox = (
                    int(round(x * sx)), int(round(y * sy)),
                    max(1, int(round(w * sx))), max(1, int(round(h * sy))),
                )
                tr.center = (tr.center[0] * sx, tr.center[1] * sy)
                tr.velocity = (tr.velocity[0] * sx, tr.velocity[1] * sy)
        state["frame_width"] = int(iw)
        state["frame_height"] = int(ih)

    def process(self, session_id: str, image, *, max_faces: int | None = None,
                identity_budget: int | None = None, camera_source: str = "static-camera",
                async_mode: bool = False, async_inference: bool | None = None,
                source_epoch: int = 0, frame_seq: int | None = None,
                capture_at: float | None = None, evidence_provider=None, appearance_observer=None) -> dict:
        if async_inference is not None:
            async_mode = bool(async_inference)
        process_started = time.perf_counter()
        capture_at = float(capture_at if capture_at is not None else time.perf_counter())
        source_epoch = int(source_epoch)
        now = time.time()
        with self._lock:
            state = self._session(session_id)
            if async_mode and state.get("source_epoch") != source_epoch:
                self._invalidate_state(session_id, state)
                self._sessions.pop(session_id, None)
                state = self._session(session_id)
                state["source_epoch"] = source_epoch
            generation = state["generation"]
            self._rescale_tracks_for_frame(state, image)
            state["sample_seq"] = int(state.get("sample_seq", 0)) + 1
            tracks: dict[int, Track] = state["tracks"]
            # A genuine absence ends the physical presence. Re-entering always gets a
            # new track and therefore a fresh FaceID event.
            for tid, tr in list(tracks.items()):
                if now - tr.last_seen >= QUICK_REARM_SEC:
                    tracks.pop(tid, None)
                    self._pipeline.invalidate_track(session_id, generation, tid)
                    ANTI_SPOOF.reset(f"{session_id}:{tid}")
                    ANTI_SPOOF.reset(f"{session_id}:g{generation}:{tid}")

        seq = int(state["sample_seq"])
        input_seq = int(frame_seq if frame_seq is not None else seq)
        effective_max_faces = max(1, int(max_faces if max_faces is not None else MAX_FACES))
        effective_identity_budget = max(1, int(identity_budget if identity_budget is not None else effective_max_faces))
        use_custom = False
        # Fast path first: one YuNet pass on every AI sample. Expensive full-frame
        # long-range recovery is only triggered after misses, never continuously.
        detection_started = time.perf_counter()
        faces = CORE.detect(image, long_range=False, use_custom=False)[:effective_max_faces]
        if faces:
            state["no_face_streak"] = 0
        else:
            state["no_face_streak"] = int(state.get("no_face_streak", 0)) + 1
            streak = int(state["no_face_streak"])
            if streak >= 2 and seq % LONG_RANGE_EVERY == 0:
                use_custom = True
                faces = CORE.detect(image, long_range=True, use_custom=True)[:effective_max_faces]
                if faces:
                    state["no_face_streak"] = 0
        state["last_face_count"] = len(faces)
        detection_ms = (time.perf_counter() - detection_started) * 1000.

        observation_started = time.perf_counter()
        observations: list[FaceObservation] = []
        for face in faces:
            try:
                observations.append(CORE.observe(image, face, with_embedding=False))
            except Exception:
                continue
        observation_ms = (time.perf_counter() - observation_started) * 1000.

        tracking_started = time.perf_counter()
        with self._lock:
            # Reset/handover/deletion may happen while the detector owns its model.
            # Do not attach that old frame to the replacement physical session.
            if self._sessions.get(session_id) is not state or state["generation"] != generation:
                return {"ok": True, "face_count": 0, "track_count": 0, "tracks": [], "events": [],
                        "discarded_generation": True}
            tracks = state["tracks"]
            assignments = self._assign(tracks, observations, now, capture_at=capture_at)
            tracking_ms = (time.perf_counter() - tracking_started) * 1000.
            verification_started = time.perf_counter()
            if appearance_observer is not None:
                appearance_observer(assignments, int(image.shape[1]), int(image.shape[0]), now)
            events: list[dict] = []
            public_tracks: list[dict] = []
            identity_embeddings = 0
            pad_results = {}
            identity_results = {}
            if async_mode:
                pad_results = {r.job.track_id: r for r in self._pipeline.pad.drain(session_id, generation)}
                identity_results = {r.job.track_id: r for r in self._pipeline.faceid.drain(session_id, generation)}
            pad_jobs, identity_jobs = [], []
            frozen_image = None

            # Fairness: clear faces and tracks that have not consumed much identity
            # work go first. This matters when a group walks together.
            assignments.sort(
                key=lambda item: (item[0].recognized, item[0].processed, -float(item[1].quality.get("score", 0.0)))
            )
            assigned_ids = {tr.id for tr, _ in assignments}

            for tr, obs in assignments:
                tr.bbox = obs.bbox
                tr.center = self._center(obs.bbox)
                tr.last_seen = now
                q = obs.quality
                pad_quality_ok, pad_quality_reason = self._recognition_quality_gate(obs, for_pad=True)
                identity_quality_ok, identity_quality_reason = self._recognition_quality_gate(obs, for_pad=False)
                tr.quality_gate_ok = bool(identity_quality_ok)
                tr.quality_wait_reason = identity_quality_reason or pad_quality_reason or ""

                pad_result = pad_results.get(tr.id)
                if pad_result is not None and (not self._valid_result(pad_result, state, tr, source_epoch)
                                                or pad_result.job.seq <= tr.pad_completed_seq):
                    pad_result = None
                returned_identity = identity_results.get(tr.id)
                if returned_identity is not None and self._valid_result(returned_identity, state, tr, source_epoch):
                    if returned_identity.job.seq > tr.identity_completed_seq:
                        tr.identity_result = returned_identity
                identity_result = tr.identity_result
                if identity_result is not None and not self._valid_result(identity_result, state, tr, source_epoch):
                    tr.identity_result = identity_result = None
                if pad_result is not None:
                    tr.pad_completed_seq = pad_result.job.seq
                    tr.pad_capture_at = pad_result.job.captured_at

                # Evidence providers run only in the identity worker (including their
                # main-stream detector). Here we only encode verified result crops.
                if async_mode and identity_result is not None and not identity_result.error:
                    evidence = (identity_result.value or {}).get("evidence")
                    if evidence and evidence.get("image") is not None and evidence.get("observation") is not None:
                        self._update_best_shots(tr, evidence["image"], evidence["observation"], now)

                self._update_best_shots(tr, image, obs, now)

                # compatibility marker: V1.15 Stage 0
                # V1 FACE Stage 0: PASSIVE anti-spoof runs for EVERY physical face track
                # before FaceID. This is the critical policy change for classroom/entrance
                # cameras: a face shown on a phone/photo is blocked even when it is not
                # registered, and no student is ever asked to look at the camera, blink,
                # turn, or stop moving.
                live = None
                if (not async_mode and pad_quality_ok) or (async_mode and pad_result is not None):
                    if ANTI_SPOOF_ENABLED:
                        if async_mode:
                            if pad_result.error or pad_result.value is None:
                                from .anti_spoof import LivenessDecision
                                live = LivenessDecision("CHECKING", 0.0, "PAD_INFERENCE_FAILED")
                            else:
                                live = pad_result.value
                        else:
                            live = ANTI_SPOOF.update(f"{session_id}:{tr.id}", image, obs, now)
                    else:
                        from .anti_spoof import LivenessDecision
                        live = LivenessDecision("PASS", 1.0, "Anti-spoof disabled by local config")
                    tr.liveness = live.public()

                    # A BLOCKED anti-spoof decision is not terminal for the physical
                    # tracker. AntiSpoofEngine keeps analysing new frames; after the
                    # phone/photo disappears it returns CHECKING and later PASS. Clear
                    # the track-level latch at CHECKING so the UI can visibly recover,
                    # while FaceID remains gated until PASS.
                    if tr.spoof_blocked and not live.blocked:
                        tr.spoof_blocked = False
                        tr.spoof_emitted = False
                        tr.recognized = False
                        tr.recognized_student_id = None
                        tr.recognized_confidence = 0.0
                        tr.recognized_at = 0.0
                        tr.candidate_student_id = None
                        tr.candidate_confidence = 0.0
                        tr.candidate_reason = ""
                        tr.candidate_student = None
                        tr.samples.clear()
                        tr.identity_vectors.clear()
                        tr.best_match_score = 0.0
                        tr.best_match_student_id = None
                        tr.processed = 0
                        tr.last_sample_at = 0.0
                        tr.unknown = False
                        tr.unknown_emitted = False
                        tr.unknown_since = 0.0
                        tr.unknown_event_id = 0
                        tr.identity_mismatch_streak = 0
                        tr.identity_conflict_student_id = None
                        tr.identity_guard_state = "RECOVERING"
                        tr.identity_result = identity_result = None
                        tr.candidate_seq = -1

                    if live.blocked:
                        # Security boundary: once a physical track is classified as a
                        # phone/screen/photo carrier, erase every identity candidate from
                        # the live track.  The UI must never continue to display a name
                        # that happened to match before the spoof context became obvious.
                        tr.spoof_blocked = True
                        tr.unknown = False
                        tr.unknown_emitted = False
                        tr.recognized = False
                        tr.recognized_student_id = None
                        tr.recognized_confidence = 0.0
                        tr.recognized_at = 0.0
                        tr.candidate_student_id = None
                        tr.candidate_confidence = 0.0
                        tr.candidate_reason = ""
                        tr.candidate_student = None
                        tr.samples.clear()
                        tr.identity_vectors.clear()
                        tr.best_match_score = 0.0
                        tr.best_match_student_id = None
                        tr.identity_mismatch_streak = 0
                        tr.identity_conflict_student_id = None
                        tr.identity_guard_state = "SPOOF_BLOCKED"
                        tr.identity_result = identity_result = None
                        tr.candidate_seq = -1
                        # Never reveal/continue FaceID for a blocked carrier.
                        if not tr.spoof_emitted:
                            tr.spoof_emitted = True
                            ev = add_spoof_event(
                                f"{session_id}:{tr.id}",
                                {
                                    "reason": live.reason,
                                    "quality": q,
                                    "pose": obs.pose,
                                    "sample_count": 0,
                                    "profile": "v1-face-context-first-anti-spoof",
                                    "liveness": tr.liveness,
                                    "spoof_method": str((tr.liveness or {}).get("spoof_method") or "FACE_INSIDE_PHONE_SCREEN"),
                                    "best_snapshot": tr.best_snapshot,
                                    "bbox": list(map(int, tr.bbox)),
                                    "frame_width": int(image.shape[1]),
                                    "frame_height": int(image.shape[0]),
                                },
                                student_id=None,
                                confidence=0.0,
                                liveness_score=float(live.score),
                                camera_source=camera_source,
                            )
                            # V2.7 event aggregation: PAD may keep evaluating the same
                            # physical carrier for hundreds of frames.  Only a new or
                            # promoted security episode reaches evidence/history/UI.
                            if not ev.get("deduplicated"):
                                try:
                                    persist_recognition_evidence(int(ev.get("id") or 0), tr.best_snapshot)
                                except Exception:
                                    pass
                                try:
                                    apply_rejected_checkin(tr.candidate_student_id, str(ev.get("event_at") or ""))
                                except Exception:
                                    pass
                                events.append(
                                    {
                                        **ev,
                                        "track_id": tr.id,
                                        "confidence": float(tr.candidate_confidence),
                                        "student": tr.candidate_student,
                                        "best_snapshot": tr.best_snapshot,
                                        "best_pose": tr.best_pose,
                                        "reason": live.reason,
                                        "status": "SPOOF_BLOCKED",
                                        "liveness": tr.liveness,
                                        "camera_source": camera_source,
                                    }
                                )
                elif not pad_quality_ok and not tr.spoof_blocked and not tr.recognized:
                    # Poor pose/blur is uncertainty, not an attack. Do not feed it into
                    # the temporal PAD vote window and do not label the person UNKNOWN.
                    previous = dict(tr.liveness or {})
                    if str(previous.get("status") or "") != "PASS":
                        tr.liveness = {
                            "status": "CHECKING", "score": float(previous.get("score") or 0.0),
                            "reason": pad_quality_reason or identity_quality_reason or "Đang chờ khung hình tốt hơn",
                            "risk_score": float(previous.get("risk_score") or 0.0),
                            "context_score": float(previous.get("context_score") or 0.0),
                            "signals": {**dict(previous.get("signals") or {}), "quality_gate": {
                                "ok": False, "reason": pad_quality_reason or identity_quality_reason or "quality-wait",
                                "yaw": round(float(obs.yaw), 4), "pitch": round(float(obs.pitch), 4),
                                "quality": round(float(q.get("score") or 0.0), 4),
                            }},
                        }

                live_status = str((tr.liveness or {}).get("status") or "")
                live_risk = float((tr.liveness or {}).get("risk_score") or 0.0)
                live_context = float((tr.liveness or {}).get("context_score") or 0.0)

                # V1 FACE continuous guard: PASS is revocable. If a phone/photo enters
                # the same tracker after a genuine face was already recognized, freeze
                # and clear the live identity before the UI can keep presenting it as a
                # verified person. A previous genuine attendance event is not deleted.
                if (
                    ANTI_SPOOF_ENABLED
                    and live_status != "PASS"
                    and tr.recognized
                    and (live_context >= 0.50 or live_risk >= 0.55)
                ):
                    tr.recognized = False
                    tr.recognized_student_id = None
                    tr.recognized_confidence = 0.0
                    tr.recognized_at = 0.0
                    tr.candidate_student_id = None
                    tr.candidate_confidence = 0.0
                    tr.candidate_reason = ""
                    tr.candidate_student = None
                    tr.samples.clear()
                    tr.identity_vectors.clear()
                    tr.best_match_score = 0.0
                    tr.best_match_student_id = None

                passive_passed = (not ANTI_SPOOF_ENABLED) or live_status == "PASS"
                if async_mode and ANTI_SPOOF_ENABLED:
                    key = (session_id, generation, tr.id)
                    passive_passed = bool(passive_passed and tr.pad_capture_at
                        and 0.0 <= time.perf_counter() - tr.pad_capture_at <= MAX_RESULT_AGE_SEC
                        and not self._pipeline.pad.outstanding(key, after_seq=tr.pad_completed_seq))
                    if identity_result is not None and identity_result.job.seq > tr.pad_completed_seq:
                        passive_passed = False
                    if tr.candidate_seq > tr.pad_completed_seq:
                        passive_passed = False

                identity_available = (not async_mode) or bool(identity_result is not None and passive_passed)
                identity_obs = identity_result.job.observation if async_mode and identity_result is not None else obs
                identity_q = identity_obs.quality or {}

                # R2 identity-lock revalidation. A tracker can momentarily jump from
                # person A to person B when people cross. Previously the recognized
                # name stayed cached forever. Re-check a good face periodically and
                # release the lock only after repeated strong contradictory matches.
                if (
                    passive_passed
                    and tr.recognized
                    and not tr.spoof_blocked
                    and now - tr.last_identity_verify_at >= IDENTITY_REVERIFY_SEC
                    and identity_quality_ok
                    and identity_embeddings < effective_identity_budget
                    and identity_available
                    and (not async_mode or identity_result.job.kind == "verify")
                ):
                    try:
                        verify_emb = ((identity_result.value or {}).get("embedding") if async_mode and not identity_result.error
                                      else None if async_mode else
                                      obs.embedding if obs.embedding is not None else CORE.embedding(image, obs.face))
                    except Exception:
                        verify_emb = None
                    tr.last_identity_verify_at = now
                    if async_mode:
                        tr.identity_completed_seq = identity_result.job.seq
                        tr.identity_result = None
                    if verify_emb is not None:
                        identity_embeddings += 1
                        ranked_verify = INDEX.rank(verify_emb, top_k=2)
                    else:
                        ranked_verify = []
                    if ranked_verify:
                        verify_sid, verify_score = int(ranked_verify[0][0]), float(ranked_verify[0][1])
                        second_score = float(ranked_verify[1][1]) if len(ranked_verify) > 1 else -1.0
                        verify_margin = verify_score - second_score
                        tr.identity_last_verify_score = verify_score
                        if verify_sid == int(tr.recognized_student_id or -1) and verify_score >= max(0.45, IDENTITY_REVERIFY_SCORE - 0.06):
                            tr.identity_mismatch_streak = 0
                            tr.identity_conflict_student_id = None
                            tr.identity_guard_state = "LOCKED"
                            tr.recognized_confidence = max(float(tr.recognized_confidence), min(1.0, verify_score))
                        elif verify_score >= IDENTITY_REVERIFY_SCORE and verify_margin >= IDENTITY_REVERIFY_MARGIN:
                            tr.identity_mismatch_streak += 1
                            tr.identity_conflict_student_id = verify_sid
                            tr.identity_guard_state = "VERIFYING_MISMATCH"
                            if tr.identity_mismatch_streak >= IDENTITY_REVERIFY_MISMATCHES:
                                self._drop_locked_identity(tr, now=now, conflict_sid=verify_sid)
                                tr.identity_mismatch_streak = 0
                        else:
                            # Weak/ambiguous frames never unlock a known identity.
                            tr.identity_mismatch_streak = max(0, tr.identity_mismatch_streak - 1)
                            tr.identity_guard_state = "LOCKED_WEAK"

                # V1 FACE Stage 1: FaceID is intentionally gated behind PASSIVE PASS.
                # This prevents both registered and unregistered phone/photo faces from
                # being treated as normal people before the spoof decision is known.
                if (
                    passive_passed
                    and not tr.recognized
                    and not tr.spoof_blocked
                    and tr.candidate_student_id is None
                    and identity_quality_ok
                    and now - tr.last_sample_at >= SAMPLE_MIN_GAP_SEC
                    and identity_embeddings < effective_identity_budget
                    and identity_available
                    and (not async_mode or identity_result.job.kind == "sample")
                ):
                    try:
                        emb = ((identity_result.value or {}).get("embedding") if async_mode and not identity_result.error
                               else None if async_mode else
                               obs.embedding if obs.embedding is not None else CORE.embedding(image, obs.face))
                    except Exception:
                        emb = None
                    if async_mode:
                        tr.identity_completed_seq = identity_result.job.seq
                        tr.identity_result = None
                    if emb is None:
                        ranked = []
                    else:
                        identity_embeddings += 1
                        tr.identity_vectors.append({
                            "embedding": np.asarray(emb, dtype=np.float32).copy(),
                            "quality": float(identity_q.get("score", 0.0)),
                            "pose": identity_obs.pose,
                            "at": now,
                        })
                        fused = self._fused_identity_vector(list(tr.identity_vectors))
                        ranked = INDEX.rank(fused if fused is not None else emb, top_k=2)
                    tr.last_sample_at = now
                    tr.processed += 1
                    if ranked:
                        sid, score = ranked[0]
                        second = ranked[1][1] if len(ranked) > 1 else -1.0
                        margin = float(score - second)
                        if float(score) > tr.best_match_score:
                            tr.best_match_score = float(score)
                            tr.best_match_student_id = int(sid)
                        if float(score) >= UNKNOWN_MIN_SCORE:
                            tr.samples.append(
                                {
                                    "student_id": int(sid),
                                    "score": float(score),
                                    "margin": margin,
                                    "quality": float(identity_q.get("score", 0.0)),
                                    "pose": identity_obs.pose,
                                    "fused_frames": len(tr.identity_vectors),
                                }
                            )
                        decision_sid, conf, reason = self._decision(list(tr.samples))
                        if decision_sid is not None:
                            student = fetchone(
                                "SELECT id,student_code,full_name,class_name,faculty FROM students WHERE id=?",
                                (decision_sid,),
                            )
                            if student:
                                tr.candidate_student_id = int(decision_sid)
                                tr.candidate_confidence = float(conf)
                                tr.candidate_reason = str(reason)
                                tr.candidate_student = student
                                tr.candidate_seq = identity_result.job.seq if async_mode else -1
                                tr.unknown = False
                                tr.unknown_emitted = False

                # V1 FACE Stage 2: a successful FaceID candidate can become a check-in
                # only after the passive gate has already passed. No active challenge.
                if (
                    passive_passed
                    and tr.candidate_student_id is not None
                    and not tr.recognized
                    and not tr.spoof_blocked
                ):
                    owner = self._identity_owner(tracks, int(tr.candidate_student_id), tr.id, now)
                    if owner is not None:
                        # Keep collecting/holding the candidate but never display or
                        # persist one identity on two simultaneous physical tracks.
                        tr.identity_guard_state = f"OWNED_BY_TRACK_{owner.id}"
                        student = None
                    else:
                        student = tr.candidate_student or fetchone(
                            "SELECT id,student_code,full_name,class_name,faculty FROM students WHERE id=?",
                            (tr.candidate_student_id,),
                        )
                    if student:
                        tr.recognized = True
                        tr.recognized_student_id = int(tr.candidate_student_id)
                        tr.recognized_confidence = float(tr.candidate_confidence)
                        tr.recognized_at = now
                        tr.last_identity_verify_at = now
                        tr.identity_mismatch_streak = 0
                        tr.identity_conflict_student_id = None
                        tr.identity_last_verify_score = float(tr.candidate_confidence)
                        tr.identity_guard_state = "LOCKED"
                        live_score = float((tr.liveness or {}).get("score") or 1.0)
                        ev = add_event(
                            int(tr.candidate_student_id),
                            f"{session_id}:{tr.id}",
                            float(tr.candidate_confidence),
                            {
                                "reason": tr.candidate_reason,
                                "quality": q,
                                "pose": obs.pose,
                                "sample_count": len(tr.samples),
                                "profile": "v1-face-context-first-anti-spoof",
                                "liveness": tr.liveness,
                                "best_snapshot": tr.best_snapshot,
                            },
                            liveness_score=live_score,
                            anti_spoof_passed=True,
                            status="RECOGNIZED",
                            camera_source=camera_source,
                        )
                        if not ev.get("deduplicated"):
                            try:
                                persist_recognition_evidence(int(ev.get("id") or 0), tr.best_snapshot)
                            except Exception:
                                pass
                            try:
                                attendance = apply_successful_checkin(int(ev.get("id") or 0), int(tr.candidate_student_id), str(ev.get("event_at") or ""))
                                if attendance:
                                    ev.update(attendance)
                            except Exception:
                                pass
                            events.append(
                                {
                                    **ev,
                                    "track_id": tr.id,
                                    "confidence": float(tr.candidate_confidence),
                                    "student": student,
                                    "best_snapshot": tr.best_snapshot,
                                    "best_pose": tr.best_pose,
                                    "reason": tr.candidate_reason,
                                    "status": "RECOGNIZED",
                                    "liveness": tr.liveness,
                                    "camera_source": camera_source,
                                }
                            )
                        else:
                            tr.identity_guard_state = "CROSS_CAMERA_DEDUP"

                # If several usable frames have been evaluated and no registered
                # identity survives the threshold, surface a deterministic
                # "Chưa đăng ký" state.  A known identity waiting for passive anti-spoof must
                # never be downgraded to UNKNOWN while verification is in progress.
                if (
                    passive_passed
                    and not tr.recognized
                    and not tr.spoof_blocked
                    and tr.candidate_student_id is None
                    and not tr.unknown
                ):
                    # UNKNOWN is a stable conclusion, not the result of the first
                    # few unlucky frames. Keep retrying on the same track; a registered
                    # employee can still be promoted to RECOGNIZED as soon as cleaner
                    # frontal evidence arrives.
                    enough_attempts = tr.processed >= 6
                    enough_time = (now - tr.first_seen) >= 1.60
                    no_candidate = (not tr.samples) and tr.processed >= 6
                    ambiguous_exhausted = tr.processed >= max(8, MAX_SAMPLES_PER_TRACK + 2)
                    if enough_attempts and enough_time and (no_candidate or ambiguous_exhausted):
                        tr.unknown = True
                        tr.unknown_since = now

                if tr.unknown and not tr.unknown_emitted:
                    tr.unknown_emitted = True
                    ev = add_unknown_event(
                        f"{session_id}:{tr.id}",
                        {
                            "quality": q,
                            "pose": obs.pose,
                            "sample_count": len(tr.samples),
                            "processed": tr.processed,
                            "best_snapshot": tr.best_snapshot,
                            "bbox": list(map(int, tr.bbox)),
                            "frame_width": int(image.shape[1]),
                            "frame_height": int(image.shape[0]),
                        },
                        camera_source=camera_source,
                    )
                    tr.unknown_event_id = int(ev.get("id") or 0)
                    # V2.7: tracker IDs are allowed to churn briefly without
                    # turning one unknown person into a stream of history rows.
                    if not ev.get("deduplicated"):
                        try:
                            persist_recognition_evidence(int(ev.get("id") or 0), tr.best_snapshot)
                        except Exception:
                            pass
                        events.append(
                            {
                                **ev,
                                "track_id": tr.id,
                                "confidence": 0.0,
                                "student": None,
                                "best_snapshot": tr.best_snapshot,
                                "best_pose": tr.best_pose,
                                "reason": "no-registered-template-match",
                                "status": "UNREGISTERED",
                                "display_name": "Chưa đăng ký",
                                "camera_source": camera_source,
                            }
                        )

                # V3 Visitor Management: turn a real UNKNOWN track into one visit
                # session and sync only when the Best Shots buffer changed.
                if tr.unknown and not tr.spoof_blocked and tr.best_shots_revision != tr.visitor_synced_revision:
                    try:
                        touch_visitor_unknown(
                            track_ref=f"{session_id}:{tr.id}",
                            camera_source=camera_source,
                            event_id=int(tr.unknown_event_id or 0) or None,
                            best_shots=list(tr.best_shots or []),
                        )
                        tr.visitor_synced_revision = tr.best_shots_revision
                    except Exception:
                        pass

                if async_mode and 0.0 <= time.perf_counter() - capture_at <= MAX_RESULT_AGE_SEC:
                    key = (session_id, generation, tr.id)
                    needs_pad = bool(ANTI_SPOOF_ENABLED and pad_quality_ok and input_seq > tr.pad_submitted_seq)
                    kind = "verify" if tr.recognized else "sample"
                    needs_identity = bool(identity_quality_ok and not tr.spoof_blocked
                        and ((not ANTI_SPOOF_ENABLED) or str((tr.liveness or {}).get("status") or "") == "PASS")
                        and tr.identity_result is None and not self._pipeline.faceid.outstanding(key)
                        and (tr.recognized or tr.candidate_student_id is None)
                        and input_seq > tr.identity_completed_seq)
                    enough_gap = (now - tr.last_identity_verify_at >= IDENTITY_REVERIFY_SEC if tr.recognized
                                  else now - tr.last_sample_at >= SAMPLE_MIN_GAP_SEC)
                    needs_identity = needs_identity and enough_gap and len(identity_jobs) < effective_identity_budget
                    if needs_pad or needs_identity:
                        if frozen_image is None:
                            frozen_image = image.copy()
                            frozen_image.setflags(write=False)
                        frozen_obs = self._freeze_observation(obs, evidence_provider)
                        job = InferenceJob(session_id, generation, tr.id, input_seq, capture_at, now,
                                           frozen_image, frozen_obs, kind, source_epoch)
                        if needs_pad:
                            pad_jobs.append(job)
                            tr.pad_submitted_seq = input_seq
                        if needs_identity:
                            identity_jobs.append(job)

                live_status = str((tr.liveness or {}).get("status") or "")
                if tr.spoof_blocked:
                    public_status = "SPOOF_BLOCKED"
                elif tr.recognized:
                    # Identity hysteresis: once safely locked, weak/oblique frames do
                    # not make the UI forget the person. The continuous guard above
                    # still revokes the lock when there is actual spoof/conflict evidence.
                    public_status = "RECOGNIZED"
                elif not tr.quality_gate_ok:
                    public_status = "OBSERVING_QUALITY"
                elif ANTI_SPOOF_ENABLED and str((tr.liveness or {}).get("status") or "") != "PASS":
                    public_status = "VERIFYING_PASSIVE"
                elif tr.unknown:
                    public_status = "UNREGISTERED"
                elif tr.candidate_student_id is not None:
                    public_status = "VERIFYING_PASSIVE"
                else:
                    public_status = "ANALYZING"
                public_tracks.append(
                    {
                        "track_id": tr.id,
                        "bbox": list(map(int, tr.bbox)),
                        "recognized": tr.recognized,
                        "student_id": tr.recognized_student_id,
                        "confidence": round(float(tr.recognized_confidence), 4),
                        "candidate_student_id": tr.candidate_student_id,
                        "candidate_confidence": round(float(tr.candidate_confidence), 4),
                        "candidate_student": tr.candidate_student,
                        "samples": len(tr.samples),
                        "quality": q,
                        "pose": obs.pose,
                        "age_ms": int((now - tr.first_seen) * 1000.0),
                        "unknown": bool(tr.unknown),
                        "spoof_blocked": bool(tr.spoof_blocked),
                        "liveness": dict(tr.liveness or {}),
                        "status": public_status,
                        "display_name": "Nghi giả mạo" if tr.spoof_blocked else ("Chưa đăng ký" if tr.unknown else ""),
                        "best_snapshot": tr.best_snapshot,
                        "stale": False,
                        "observation_age_ms": 0,
                        "quality_gate": {
                            "ok": bool(tr.quality_gate_ok),
                            "reason": str(tr.quality_wait_reason or ""),
                            "best_match_score": round(float(tr.best_match_score), 4),
                            "best_match_student_id": tr.best_match_student_id,
                            "fused_frames": len(tr.identity_vectors),
                        },
                        "identity_guard": {
                            "state": tr.identity_guard_state,
                            "mismatch_streak": int(tr.identity_mismatch_streak),
                            "conflict_student_id": tr.identity_conflict_student_id,
                            "last_verify_score": round(float(tr.identity_last_verify_score), 4),
                        },
                    }
                )

            # Short detector-miss grace: keep a recently observed physical track in the
            # public stream instead of flashing to 0 students when a person sits, bends
            # or briefly turns away. Identity remains cached, but no new FaceID/Pose
            # evidence is invented while the detector is missing.
            display_grace = min(0.90, max(0.45, QUICK_REARM_SEC * 0.72))
            for tid, tr in list(tracks.items()):
                if tid in assigned_ids:
                    continue
                missing_age = now - tr.last_seen
                if missing_age <= 0.0 or missing_age > display_grace:
                    continue
                px = tr.center[0] + tr.velocity[0] * min(0.30, missing_age)
                py = tr.center[1] + tr.velocity[1] * min(0.30, missing_age)
                x, y, w, h = tr.bbox
                pred = [int(round(px - w * 0.5)), int(round(py - h * 0.5)), int(w), int(h)]
                live_status = str((tr.liveness or {}).get("status") or "")
                if tr.spoof_blocked:
                    public_status = "SPOOF_BLOCKED"
                elif tr.recognized:
                    # Identity hysteresis: once safely locked, weak/oblique frames do
                    # not make the UI forget the person. The continuous guard above
                    # still revokes the lock when there is actual spoof/conflict evidence.
                    public_status = "RECOGNIZED"
                elif not tr.quality_gate_ok:
                    public_status = "OBSERVING_QUALITY"
                elif ANTI_SPOOF_ENABLED and str((tr.liveness or {}).get("status") or "") != "PASS":
                    public_status = "VERIFYING_PASSIVE"
                elif tr.unknown:
                    public_status = "UNREGISTERED"
                elif tr.candidate_student_id is not None:
                    public_status = "VERIFYING_PASSIVE"
                else:
                    public_status = "ANALYZING"
                public_tracks.append({
                    "track_id": tr.id, "bbox": pred, "recognized": tr.recognized,
                    "student_id": tr.recognized_student_id, "confidence": round(float(tr.recognized_confidence), 4),
                    "candidate_student_id": tr.candidate_student_id, "candidate_confidence": round(float(tr.candidate_confidence), 4),
                    "candidate_student": tr.candidate_student, "samples": len(tr.samples), "quality": {}, "pose": tr.best_pose,
                    "age_ms": int((now - tr.first_seen) * 1000.0), "unknown": bool(tr.unknown),
                    "spoof_blocked": bool(tr.spoof_blocked), "liveness": dict(tr.liveness or {}), "status": public_status,
                    "display_name": "Nghi giả mạo" if tr.spoof_blocked else ("Chưa đăng ký" if tr.unknown else ""),
                    "best_snapshot": tr.best_snapshot, "stale": True, "observation_age_ms": int(missing_age * 1000.0),
                    "quality_gate": {
                        "ok": bool(tr.quality_gate_ok), "reason": str(tr.quality_wait_reason or ""),
                        "best_match_score": round(float(tr.best_match_score), 4),
                        "best_match_student_id": tr.best_match_student_id, "fused_frames": len(tr.identity_vectors),
                    },
                    "identity_guard": {
                        "state": tr.identity_guard_state,
                        "mismatch_streak": int(tr.identity_mismatch_streak),
                        "conflict_student_id": tr.identity_conflict_student_id,
                        "last_verify_score": round(float(tr.identity_last_verify_score), 4),
                    },
                })

            # Safety cleanup for tracks that somehow survived longer than intended.
            for tid, tr in list(tracks.items()):
                if now - tr.last_seen > max(QUICK_REARM_SEC, 2.2):
                    if tr.unknown:
                        try:
                            close_visitor_track(track_ref=f"{session_id}:{tid}", camera_source=camera_source, reason="TRACK_LOST")
                        except Exception:
                            pass
                    tracks.pop(tid, None)
                    self._pipeline.invalidate_track(session_id, generation, tid)
                    ANTI_SPOOF.reset(f"{session_id}:{tid}")
                    ANTI_SPOOF.reset(f"{session_id}:g{generation}:{tid}")

            if async_mode:
                # Revalidation of a known/candidate employee precedes anonymous sampling.
                priority = lambda job: not bool(tracks.get(job.track_id) and
                    (tracks[job.track_id].recognized or tracks[job.track_id].candidate_student_id))
                pad_jobs.sort(key=priority)
                identity_jobs.sort(key=priority)
                self._pipeline.pad.submit(pad_jobs)
                self._pipeline.faceid.submit(identity_jobs)

            return {
                "ok": True,
                "face_count": len(observations),
                "detection": {
                    "detected_faces": len(faces),
                    "observed_faces": len(observations),
                    "observation_errors": len(faces) - len(observations),
                    "no_face_streak": int(state["no_face_streak"]),
                    "recovery_attempted": bool(use_custom),
                },
                "track_count": len(tracks),
                "tracks": public_tracks,
                "events": events,
                "custom_long_range_used": bool(use_custom and CORE.custom_detector_ready),
                "frame_width": int(image.shape[1]),
                "frame_height": int(image.shape[0]),
                "policy": "tracker-centric/event-driven-faceid/identity-cache/rearm-after-absence",
                "identity_budget": int(effective_identity_budget),
                "identity_embeddings": int(identity_embeddings),
                "ai_metrics": self._pipeline.status() if async_mode else {},
                "stage_times": {"detection_ms": round(detection_ms, 3),
                                "observation_ms": round(observation_ms, 3),
                                "tracking_ms": round(tracking_ms, 3),
                                "verification_dispatch_ms": round((time.perf_counter() - verification_started) * 1000., 3),
                                "sample_total_ms": round((time.perf_counter() - process_started) * 1000., 3)},
            }

    def purge_student(self, student_id: int) -> None:
        """Invalidate an identity immediately after the student is deleted.

        Existing physical tracks are intentionally kept so the person becomes
        UNREGISTERED on the next AI cycle instead of continuing to display a deleted
        name until they leave the frame.
        """
        sid = int(student_id)
        with self._lock:
            for session_id, state in self._sessions.items():
                self._invalidate_state(session_id, state)
                state["generation"] = next(self._generations)
                for tr in state.get("tracks", {}).values():
                    tr.identity_result = None
                    tr.pad_completed_seq = tr.pad_submitted_seq = -1
                    tr.pad_capture_at = 0.0
                    if tr.recognized_student_id == sid or tr.candidate_student_id == sid:
                        tr.recognized = False
                        tr.recognized_student_id = None
                        tr.recognized_confidence = 0.0
                        tr.candidate_student_id = None
                        tr.candidate_confidence = 0.0
                        tr.candidate_reason = ""
                        tr.candidate_student = None
                        tr.spoof_blocked = False
                        tr.spoof_emitted = False
                        tr.liveness = {}
                        tr.samples.clear()
                        tr.processed = max(tr.processed, 3)
                        tr.unknown = True
                        tr.unknown_emitted = False
                        tr.unknown_since = time.time()

    def reset(self, session_id: str) -> None:
        with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is not None:
                self._invalidate_state(session_id, state)
        ANTI_SPOOF.purge_prefix(f"{session_id}:")


WALKBY = WalkByEngine()
