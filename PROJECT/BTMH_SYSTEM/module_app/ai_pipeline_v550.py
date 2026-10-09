"""Bounded, independent model lanes for the service camera.

There is one in-flight batch and at most one waiting batch per lane. A newer
waiting batch replaces the older one; results never accumulate a video queue.
Workers return immutable packets and never mutate WalkBy tracks or persist events.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


MAX_RESULT_AGE_SEC = 2.0


@dataclass(frozen=True)
class InferenceJob:
    session_id: str
    epoch: int
    track_id: int
    seq: int
    captured_at: float
    observed_at: float
    image: Any
    observation: Any
    kind: str = "sample"
    source_epoch: int = 0

    @property
    def key(self) -> tuple[str, int, int]:
        return self.session_id, self.epoch, self.track_id


@dataclass(frozen=True)
class InferenceResult:
    job: InferenceJob
    value: Any = None
    error: bool = False
    completed_at: float = 0.0


class LatestBatchLane:
    """A replaceable single slot, without ThreadPoolExecutor's unbounded queue."""

    def __init__(self, name: str, infer: Callable[[InferenceJob], Any], *, on_discard=None) -> None:
        self.name, self._infer = name, infer
        self._on_discard = on_discard
        self._condition = threading.Condition()
        self._pending: tuple[InferenceJob, ...] = ()
        self._inflight: tuple[InferenceJob, ...] = ()
        self._results: tuple[InferenceResult, ...] = ()
        self._invalid: set[tuple[str, int]] = set()
        self._invalid_tracks: set[tuple[str, int, int]] = set()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._started_at = time.perf_counter()
        self._completed = self._dropped = self._errors = 0
        self._last_ms = 0.0
        self._pending_at = 0.0
        self._last_queue_wait_ms = None
        self._last_result_at = 0.0
        self._last_capture_at = 0.0
        self._last_progress_at = self._started_at
        self._restarts = 0
        self._recent: list[float] = []

    def _valid(self, job: InferenceJob) -> bool:
        return (job.session_id, job.epoch) not in self._invalid and job.key not in self._invalid_tracks

    def _discard(self, job: InferenceJob) -> None:
        if self._on_discard is not None:
            try:
                self._on_discard(job)
            except Exception:
                pass

    def submit(self, jobs: list[InferenceJob]) -> None:
        if not jobs:
            return
        with self._condition:
            # A model call cannot be killed safely. Never spawn a replacement while
            # the previous worker is still alive, even if its shutdown timed out.
            if self._stopping:
                if self._thread is not None and self._thread.is_alive():
                    self._dropped += len(jobs)
                    return
                self._stopping = False
            if self._thread is None or not self._thread.is_alive():
                if self._thread is not None:
                    self._restarts += 1
                self._thread = threading.Thread(target=self._run, name=f"btmh-ai-{self.name}", daemon=True)
                self._thread.start()
            self._dropped += len(self._pending)
            self._pending = tuple(j for j in jobs if self._valid(j))
            self._pending_at = time.perf_counter()
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopping or bool(self._pending))
                if self._stopping:
                    return
                batch, self._pending = self._pending, ()
                submitted_at = self._pending_at
                self._inflight = batch
                self._last_progress_at = time.perf_counter()
            outputs: list[InferenceResult] = []
            for job in batch:
                with self._condition:
                    valid = self._valid(job) and not self._stopping
                age = time.perf_counter() - job.captured_at
                if not valid or not 0.0 <= age <= MAX_RESULT_AGE_SEC:
                    with self._condition:
                        self._dropped += 1
                    self._discard(job)
                    continue
                began = time.perf_counter()
                try:
                    value, failed = self._infer(job), False
                except Exception:
                    # Raw model errors can contain local paths/config. Diagnostics
                    # expose a code/count, never arbitrary exception text.
                    value, failed = None, True
                ended = time.perf_counter()
                with self._condition:
                    self._completed += 1
                    self._errors += int(failed)
                    self._last_ms = (ended - began) * 1000.0
                    self._last_queue_wait_ms = max(0., began - submitted_at) * 1000.
                    self._last_progress_at = ended
                    self._recent = [x for x in self._recent if ended - x <= 5.0]
                    self._recent.append(ended)
                    accepted = bool(self._valid(job) and not self._stopping
                                    and 0.0 <= ended - job.captured_at <= MAX_RESULT_AGE_SEC)
                    if accepted:
                        outputs.append(InferenceResult(job, value, failed, ended))
                        self._last_result_at = ended
                        self._last_capture_at = job.captured_at
                    else:
                        self._dropped += 1
                if not accepted:
                    self._discard(job)
            with self._condition:
                discarded = [r.job for r in outputs if not self._valid(r.job) or self._stopping]
                if outputs:
                    self._dropped += len(self._results)
                    self._results = tuple(r for r in outputs if self._valid(r.job) and not self._stopping)
                self._inflight = ()
                self._invalid.clear()
                self._invalid_tracks.clear()
            for job in discarded:
                self._discard(job)

    def drain(self, session_id: str, epoch: int) -> list[InferenceResult]:
        with self._condition:
            selected = [r for r in self._results if r.job.session_id == session_id and r.job.epoch == epoch]
            self._results = tuple(r for r in self._results if not (r.job.session_id == session_id and r.job.epoch == epoch))
            return selected

    def outstanding(self, key: tuple[str, int, int], *, after_seq: int = -1) -> bool:
        with self._condition:
            # A completion can move from in-flight to results after WalkBy drains.
            # Undrained newer PAD observations must still revoke an older PASS.
            jobs = (*self._inflight, *self._pending, *(r.job for r in self._results))
            return any(j.key == key and j.seq > after_seq and self._valid(j) for j in jobs)

    def invalidate(self, session_id: str, epoch: int) -> None:
        with self._condition:
            self._invalid.add((session_id, epoch))
            self._pending = tuple(j for j in self._pending if self._valid(j))
            self._results = tuple(r for r in self._results if self._valid(r.job))
            # Only generations still referenced by a blocked call need a tombstone.
            live = {(j.session_id, j.epoch) for j in self._inflight}
            self._invalid.intersection_update(live)

    def invalidate_track(self, session_id: str, epoch: int, track_id: int) -> None:
        with self._condition:
            self._invalid_tracks.add((session_id, epoch, track_id))
            self._pending = tuple(j for j in self._pending if self._valid(j))
            self._results = tuple(r for r in self._results if self._valid(r.job))
            self._invalid_tracks.intersection_update(j.key for j in self._inflight)

    def shutdown(self, timeout: float = 0.25) -> None:
        with self._condition:
            self._stopping = True
            self._pending = self._results = ()
            self._condition.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def status(self) -> dict:
        now = time.perf_counter()
        with self._condition:
            self._recent = [x for x in self._recent if now - x <= 5.0]
            elapsed = min(5.0, max(0.001, now - self._started_at))
            return {
                "pending": int(bool(self._pending)), "busy": bool(self._inflight),
                "alive": bool(self._thread and self._thread.is_alive()),
                "stopping": self._stopping, "completed": self._completed,
                "dropped": self._dropped, "errors": self._errors,
                "fps": round(len(self._recent) / elapsed, 2),
                "last_ms": round(self._last_ms, 1),
                "last_queue_wait_ms": round(self._last_queue_wait_ms, 1) if self._last_queue_wait_ms is not None else None,
                "last_result_age_ms": round((now - self._last_result_at) * 1000.0, 1) if self._last_result_at else None,
                "last_latency_ms": round((self._last_result_at - self._last_capture_at) * 1000.0, 1) if self._last_result_at else None,
                "stalled": bool(self._inflight and now - self._last_progress_at > MAX_RESULT_AGE_SEC),
                "restarts": self._restarts,
            }


class AsyncInferencePipeline:
    def __init__(self, pad: Callable[[InferenceJob], Any], identity: Callable[[InferenceJob], Any], *, discard_pad=None) -> None:
        self.pad = LatestBatchLane("pad", pad, on_discard=discard_pad)
        self.faceid = LatestBatchLane("faceid", identity)

    def invalidate(self, session_id: str, epoch: int) -> None:
        self.pad.invalidate(session_id, epoch)
        self.faceid.invalidate(session_id, epoch)

    def shutdown(self) -> None:
        self.pad.shutdown()
        self.faceid.shutdown()

    def invalidate_track(self, session_id: str, epoch: int, track_id: int) -> None:
        self.pad.invalidate_track(session_id, epoch, track_id)
        self.faceid.invalidate_track(session_id, epoch, track_id)

    def status(self) -> dict:
        return {"pad": self.pad.status(), "faceid": self.faceid.status()}
