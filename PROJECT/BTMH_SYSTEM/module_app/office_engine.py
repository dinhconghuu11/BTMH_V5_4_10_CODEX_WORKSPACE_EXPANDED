from __future__ import annotations

import json
import math
import hashlib
import threading
import time

import cv2
from collections import deque
from pathlib import Path
from typing import Any

from .camera import CAMERA
from .config import CONFIG_DIR
from .camera_profiles import normalize_camera_source
from .db import (
    add_audit_event, add_hr_event, add_office_crossing_event, close_presence_session, fetchone,
    office_crossing_history, office_crossing_summary, open_presence_session, touch_presence_session,
)
from .production_ops import persist_hr_evidence


_DEFAULT_CONFIG: dict[str, Any] = {
    "monitoring_enabled": True,
    "hr_tracking": {
        "enabled": True,
        "status_debounce_sec": 4.0,
        "event_cooldown_sec": 45.0,
        "min_stable_dwell_sec": 20.0,
        "lost_after_sec": 20.0,
        "close_after_sec": 120.0,
        "session_touch_sec": 60.0,
        "persist_status_changes": False,
        "persist_visibility_events": False,
        "close_on_camera_absence": False,
    },
    "line": {
        "configured": False,
        "enabled": False,
        "name": "Cửa văn phòng",
        "x1": 0.15,
        "y1": 0.55,
        "x2": 0.85,
        "y2": 0.55,
        "inside_side": "positive",
        "deadband": 0.025,
        "cooldown_sec": 2.5,
        "anchor": "person_center",
        "camera_id": None,
        "camera_name": "",
        "zone_name": "",
        "camera_source_fingerprint": "",
    },
}


class OfficeEngine:
    """Office observer + virtual line crossing counter.

    It never opens a camera. It consumes the newest shared CameraService FaceID
    tracks. This preserves the one-camera-handle architecture used by FaceID,
    anti-spoof, attendance and recording without running posture or behaviour inference.

    The virtual gate is intentionally disabled until the operator mounts the fixed
    camera and draws a line in the web UI. Coordinates are normalized (0..1), so a
    later preview resolution change doesn't move the configured gate.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._path = Path(CONFIG_DIR) / "office_ai.json"
        self._config = self._load_config()
        self._track_state: dict[str, dict[str, Any]] = {}
        self._employee_state: dict[int, dict[str, Any]] = {}
        self._outside_students: dict[int, float] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=60)
        self._last_ai_seq = -1
        self._last_tick_at = 0.0
        self._last_error = ""
        self._crossing_total = 0
        self._technical_dedup: dict[tuple[int, str], float] = {}

    @staticmethod
    def _merged(base: dict[str, Any], incoming: dict[str, Any] | None) -> dict[str, Any]:
        out = json.loads(json.dumps(base))
        incoming = incoming or {}
        for key, value in incoming.items():
            if key == "line" and isinstance(value, dict):
                out["line"].update(value)
            else:
                out[key] = value
        return out

    def _load_config(self) -> dict[str, Any]:
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return self._sanitize_config(self._merged(_DEFAULT_CONFIG, raw))
        except Exception:
            pass
        return self._sanitize_config(self._merged(_DEFAULT_CONFIG, {}))

    @staticmethod
    def _clamp01(value: Any, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return float(default)

    @classmethod
    def _sanitize_config(cls, cfg: dict[str, Any]) -> dict[str, Any]:
        out = cls._merged(_DEFAULT_CONFIG, cfg)
        line = out["line"]
        line["configured"] = bool(line.get("configured"))
        line["enabled"] = bool(line.get("enabled")) and line["configured"]
        line["name"] = str(line.get("name") or "Cửa văn phòng").strip()[:80] or "Cửa văn phòng"
        line["x1"] = cls._clamp01(line.get("x1"), 0.15)
        line["y1"] = cls._clamp01(line.get("y1"), 0.55)
        line["x2"] = cls._clamp01(line.get("x2"), 0.85)
        line["y2"] = cls._clamp01(line.get("y2"), 0.55)
        if math.hypot(line["x2"] - line["x1"], line["y2"] - line["y1"]) < 0.08:
            line["x1"], line["y1"], line["x2"], line["y2"] = 0.15, 0.55, 0.85, 0.55
            line["configured"] = False
            line["enabled"] = False
        line["inside_side"] = "negative" if str(line.get("inside_side")).lower() == "negative" else "positive"
        try:
            line["deadband"] = max(0.005, min(0.12, float(line.get("deadband") or 0.025)))
        except Exception:
            line["deadband"] = 0.025
        try:
            line["cooldown_sec"] = max(0.8, min(15.0, float(line.get("cooldown_sec") or 2.5)))
        except Exception:
            line["cooldown_sec"] = 2.5
        line["anchor"] = "bottom_center" if str(line.get("anchor")).lower() == "bottom_center" else "person_center"
        try:
            line["camera_id"] = int(line.get("camera_id")) if line.get("camera_id") is not None else None
        except Exception:
            line["camera_id"] = None
        line["camera_name"] = str(line.get("camera_name") or "").strip()[:120]
        line["zone_name"] = str(line.get("zone_name") or "").strip()[:120]
        fp = str(line.get("camera_source_fingerprint") or "").strip().lower()
        line["camera_source_fingerprint"] = fp[:32] if all(c in "0123456789abcdef" for c in fp) else ""
        hr = out.get("hr_tracking") or {}
        hr["enabled"] = bool(hr.get("enabled", True))
        hr["persist_status_changes"] = bool(hr.get("persist_status_changes", False))
        hr["persist_visibility_events"] = bool(hr.get("persist_visibility_events", False))
        hr["close_on_camera_absence"] = bool(hr.get("close_on_camera_absence", False))
        for key, default, lo, hi in (
            ("status_debounce_sec", 4.0, 1.0, 20.0),
            ("event_cooldown_sec", 45.0, 5.0, 600.0),
            ("min_stable_dwell_sec", 20.0, 3.0, 600.0),
            ("lost_after_sec", 20.0, 5.0, 300.0),
            ("close_after_sec", 120.0, 30.0, 3600.0),
            ("session_touch_sec", 60.0, 10.0, 300.0),
        ):
            try:
                hr[key] = max(lo, min(hi, float(hr.get(key) or default)))
            except Exception:
                hr[key] = default
        if hr["close_after_sec"] <= hr["lost_after_sec"]:
            hr["close_after_sec"] = max(hr["lost_after_sec"] + 30.0, 60.0)
        out["hr_tracking"] = hr
        out["monitoring_enabled"] = bool(out.get("monitoring_enabled", True))
        return out

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._config, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def config(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._config))

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            merged = self._merged(self._config, payload)
            self._config = self._sanitize_config(merged)
            self._persist()
            # A line edit invalidates old side state. Otherwise a person standing in
            # view during setup could be counted immediately after pressing Save.
            self._track_state.clear()
            self._outside_students.clear()
            return json.loads(json.dumps(self._config))

    def set_monitoring(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._config["monitoring_enabled"] = bool(enabled)
            self._persist()
            return json.loads(json.dumps(self._config))

    @property
    def monitoring_enabled(self) -> bool:
        with self._lock:
            return bool(self._config.get("monitoring_enabled", True))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="cf-office-gate", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None

    @staticmethod
    def _signed_side(point: tuple[float, float], line: dict[str, Any]) -> float:
        px, py = point
        x1, y1 = float(line["x1"]), float(line["y1"])
        x2, y2 = float(line["x2"]), float(line["y2"])
        dx, dy = x2 - x1, y2 - y1
        length = max(1e-6, math.hypot(dx, dy))
        # Signed perpendicular distance in normalized frame coordinates.
        return (dx * (py - y1) - dy * (px - x1)) / length

    @staticmethod
    def _side_name(value: float, deadband: float) -> str:
        if value > deadband:
            return "positive"
        if value < -deadband:
            return "negative"
        return "deadband"

    @staticmethod
    def _track_anchor(track: dict[str, Any], fw: int, fh: int, anchor: str) -> tuple[float, float] | None:
        if fw <= 0 or fh <= 0:
            return None
        box = track.get("bbox") or track.get("face_bbox") or [0, 0, 0, 0]
        if len(box) < 4:
            return None
        try:
            x, y, w, h = [float(v) for v in box[:4]]
        except Exception:
            return None
        if w <= 1 or h <= 1:
            return None
        px = x + w * 0.5
        py = y + (h * 0.88 if anchor == "bottom_center" else h * 0.5)
        return max(0.0, min(1.0, px / fw)), max(0.0, min(1.0, py / fh))

    @staticmethod
    def _identity(track: dict[str, Any]) -> tuple[int | None, str, str, float]:
        sid = track.get("student_id")
        try:
            sid = int(sid) if sid is not None else None
        except Exception:
            sid = None
        name = str(track.get("full_name") or track.get("display_name") or "").strip()
        code = str(track.get("student_code") or "").strip()
        confidence = float(track.get("confidence") or 0.0)
        if sid is not None and not name:
            try:
                row = fetchone("SELECT student_code,full_name FROM students WHERE id=?", (sid,)) or {}
                name = str(row.get("full_name") or "")
                code = str(row.get("student_code") or "")
            except Exception:
                pass
        if not name:
            name = "Chưa xác định"
        return sid, name, code, confidence

    def _source_tracks(self) -> tuple[list[dict[str, Any]], int, int, str]:
        # V5.2 identity-only observer: attendance and Virtual Gate consume the same
        # FaceID tracks that power Recognition. No behaviour-analysis worker is started.
        result = CAMERA.latest_result()
        return (
            [dict(x) for x in result.get("tracks") or []],
            int(result.get("frame_width") or 0),
            int(result.get("frame_height") or 0),
            "IDENTITY_TRACK",
        )

    @staticmethod
    def _employee_status(track: dict[str, Any]) -> str:
        # Business status intentionally does not infer posture or behaviour.
        return "PRESENT"

    def _emit_hr_transition(
        self, sid: int, tid: str, event_type: str, now: float, camera_source: str, detail: dict[str, Any],
        *, dedup_seconds: float,
    ) -> dict[str, Any]:
        try:
            event = add_hr_event(
                sid, tid, event_type, status="INFO", camera_source=camera_source,
                detail=dict(detail or {}), dedup_seconds=dedup_seconds,
            )
            # V2.9 evidence policy: one full-scene snapshot per meaningful HR
            # business event. The camera service already owns a cached JPEG, so this
            # does not reopen RTSP or block the realtime AI pipeline.
            meaningful = {"PRESENCE_START", "PRESENCE_END", "ENTRY", "RETURN", "EXIT"}
            if str(event_type or "").upper() in meaningful and int(event.get("id") or 0) > 0 and not bool(event.get("deduplicated")):
                try:
                    # Capture the exact newest native frame at event time. This avoids
                    # a stale cached JPEG when WebRTC has allowed legacy encoders to idle.
                    jpeg = b""
                    frame = CAMERA.latest_frame()
                    if frame is not None and getattr(frame, "size", 0):
                        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                        if ok:
                            jpeg = buf.tobytes()
                    if jpeg:
                        persist_hr_evidence(int(event["id"]), jpeg)
                except Exception as evidence_exc:
                    self._last_error = str(evidence_exc)
            return event
        except Exception as exc:
            self._last_error = str(exc)
            return {"id": 0, "event_at": "", "event_type": event_type, "deduplicated": False}

    def _emit_technical(
        self, sid: int, tid: str, event_type: str, now: float, camera_source: str, detail: dict[str, Any],
        *, dedup_seconds: float = 60.0,
    ) -> None:
        """Persist low-volume diagnostics outside the manager-facing HR timeline.

        Visibility/tracker churn is useful for technicians but should not look like
        attendance movement. A small in-memory guard prevents the audit table from
        becoming a per-frame log during long occlusions.
        """
        key = (int(sid), str(event_type or "").upper())
        last = float(self._technical_dedup.get(key) or 0.0)
        if now - last < max(1.0, float(dedup_seconds)):
            return
        self._technical_dedup[key] = now
        try:
            add_audit_event(
                "TECHNICAL", str(event_type or "TRACK_STATE").upper(), "INFO",
                student_id=int(sid), camera_source=camera_source,
                detail={"track_id": str(tid or ""), **dict(detail or {})},
            )
        except Exception as exc:
            self._last_error = str(exc)

    def _process_hr_tracking(self, tracks: list[dict[str, Any]], now: float, camera_source: str) -> None:
        cfg = self.config().get("hr_tracking") or {}
        if not bool(cfg.get("enabled", True)):
            return
        debounce = float(cfg.get("status_debounce_sec") or 4.0)
        cooldown = float(cfg.get("event_cooldown_sec") or 45.0)
        min_dwell = float(cfg.get("min_stable_dwell_sec") or 20.0)
        lost_after = float(cfg.get("lost_after_sec") or 20.0)
        close_after = float(cfg.get("close_after_sec") or 120.0)
        touch_every = float(cfg.get("session_touch_sec") or 30.0)
        seen_students: set[int] = set()

        for track in tracks:
            sid = track.get("student_id")
            if sid is None or not bool(track.get("identity_verified", track.get("recognized", False))):
                continue
            try:
                sid = int(sid)
            except Exception:
                continue
            # After a verified OUT crossing, the person may remain visible just
            # outside the line for several seconds. Do not reopen a presence session
            # until an IN crossing explicitly brings them back.
            if sid in self._outside_students:
                continue
            tid = str(track.get("track_id") or "")
            seen_students.add(sid)
            name = str(track.get("full_name") or "")
            code = str(track.get("student_code") or "")
            confidence = float(track.get("confidence") or 0.0)
            desired = self._employee_status(track)
            state = self._employee_state.get(sid)
            if state is None:
                session = open_presence_session(
                    sid, tid, camera_source, start_reason="CAMERA_SEEN",
                    detail={"full_name": name, "student_code": code, "confidence": confidence},
                )
                state = {
                    "track_id": tid, "last_seen": now, "last_touch": now, "first_seen": now,
                    "full_name": name, "student_code": code, "confidence": confidence,
                    "stable_status": desired, "stable_since": now, "candidate_status": "",
                    "candidate_since": 0.0, "lost_logged": False, "observation_state": "VISIBLE",
                    "session_id": int(session.get("id") or 0),
                }
                self._employee_state[sid] = state
                if bool(session.get("created")):
                    self._emit_hr_transition(
                        sid, tid, "PRESENCE_START", now, camera_source,
                        {"full_name": name, "student_code": code, "status": desired, "session_id": session.get("id"), "confidence": confidence},
                        dedup_seconds=15.0,
                    )
            else:
                was_lost = bool(state.get("lost_logged"))
                state["track_id"] = tid
                state["last_seen"] = now
                state["full_name"] = name
                state["student_code"] = code
                state["confidence"] = confidence
                state["observation_state"] = "VISIBLE"
                if was_lost:
                    state["lost_logged"] = False
                    absence = round(now - float(state.get("lost_since") or now), 1)
                    self._emit_technical(
                        sid, tid, "TRACK_REACQUIRED", now, camera_source,
                        {"full_name": name, "student_code": code, "absence_sec": absence},
                        dedup_seconds=cooldown,
                    )
                    if bool(cfg.get("persist_visibility_events", False)):
                        self._emit_hr_transition(
                            sid, tid, "BACK_IN_VIEW", now, camera_source,
                            {"full_name": name, "student_code": code, "absence_sec": absence},
                            dedup_seconds=cooldown,
                        )
                if now - float(state.get("last_touch") or 0.0) >= touch_every:
                    touch_presence_session(sid, tid, camera_source)
                    state["last_touch"] = now

                stable = str(state.get("stable_status") or "PRESENT")
                if desired != stable:
                    if state.get("candidate_status") != desired:
                        state["candidate_status"] = desired
                        state["candidate_since"] = now
                    elif now - float(state.get("candidate_since") or now) >= debounce:
                        prior_dwell = now - float(state.get("stable_since") or now)
                        state["stable_status"] = desired
                        state["stable_since"] = now
                        state["candidate_status"] = ""
                        state["candidate_since"] = 0.0
                        # Do not turn normal posture motion into a high-volume audit trail.
                        # Only persist a stable transition after the previous state lasted
                        # long enough to be meaningful for HR review.
                        if bool(cfg.get("persist_status_changes", False)) and prior_dwell >= min_dwell:
                            self._emit_hr_transition(
                                sid, tid, "STATUS_CHANGE", now, camera_source,
                                {"full_name": name, "student_code": code, "from_status": stable, "to_status": desired, "previous_duration_sec": round(prior_dwell, 1)},
                                dedup_seconds=cooldown,
                            )
                else:
                    state["candidate_status"] = ""
                    state["candidate_since"] = 0.0

        gate_enabled = bool((self.config().get("line") or {}).get("configured") and (self.config().get("line") or {}).get("enabled"))
        for sid, state in list(self._employee_state.items()):
            if sid in seen_students:
                continue
            missing = now - float(state.get("last_seen") or now)
            if missing >= lost_after and not bool(state.get("lost_logged")):
                state["lost_logged"] = True
                state["lost_since"] = float(state.get("last_seen") or now)
                state["observation_state"] = "TEMPORARILY_LOST"
                detail = {
                    "absence_sec": round(missing, 1),
                    "message": "Camera tạm không thấy nhân viên; đây là tín hiệu kỹ thuật, không phải OUT.",
                }
                self._emit_technical(
                    sid, str(state.get("track_id") or ""), "TRACK_TEMPORARILY_LOST", now, camera_source,
                    detail, dedup_seconds=max(cooldown, lost_after),
                )
                if bool(cfg.get("persist_visibility_events", False)):
                    self._emit_hr_transition(
                        sid, str(state.get("track_id") or ""), "NOT_VISIBLE", now, camera_source,
                        detail, dedup_seconds=max(cooldown, lost_after),
                    )
            # Professional policy: losing a camera track is not evidence that an
            # employee left the office. By default the session stays open until an
            # authoritative Virtual Gate OUT, manual action, shutdown/restart policy,
            # or another explicit business event closes it. Legacy installations can
            # opt back into camera-absence closure via close_on_camera_absence.
            if bool(cfg.get("close_on_camera_absence", False)) and (not gate_enabled) and missing >= close_after:
                close_presence_session(sid, end_reason="CAMERA_NOT_VISIBLE", detail={"absence_sec": round(missing, 1)})
                self._emit_hr_transition(
                    sid, str(state.get("track_id") or ""), "PRESENCE_END", now, camera_source,
                    {"reason": "CAMERA_NOT_VISIBLE", "absence_sec": round(missing, 1)},
                    dedup_seconds=close_after,
                )
                self._employee_state.pop(sid, None)

    def _process_once(self, now: float) -> None:
        cfg = self.config()
        if not bool(cfg.get("monitoring_enabled", True)):
            with self._lock:
                self._track_state.clear()
            return

        camera_status = CAMERA.status()
        ai_seq = int(camera_status.get("ai_seq") or 0)
        if ai_seq > 0 and ai_seq == self._last_ai_seq:
            return
        if ai_seq > 0:
            self._last_ai_seq = ai_seq

        tracks, fw, fh, track_source = self._source_tracks()
        if fw <= 0 or fh <= 0:
            return
        camera_source = CAMERA.event_camera_source()

        # HR state/session processing runs regardless of whether the virtual gate has
        # been drawn. It writes only meaningful transitions, never per-frame rows.
        self._process_hr_tracking(tracks, now, camera_source)

        line = cfg.get("line") or {}
        binding = str(line.get("camera_source_fingerprint") or "").strip().lower()
        current_source = normalize_camera_source(str(camera_status.get("source") or ""))
        current_fp = hashlib.sha256(current_source.encode("utf-8", errors="ignore")).hexdigest()[:16] if current_source else ""
        camera_match = (not binding) or binding == current_fp
        if not (line.get("configured") and line.get("enabled") and camera_match):
            with self._lock:
                self._track_state.clear()
            self._outside_students.clear()
            if binding and not camera_match:
                self._last_error = "Virtual Gate tạm dừng: camera hiện tại không khớp camera đã cấu hình."
            return
        if str(self._last_error or "").startswith("Virtual Gate tạm dừng"):
            self._last_error = ""

        current_ids: set[str] = set()
        deadband = float(line.get("deadband") or 0.025)
        cooldown = float(line.get("cooldown_sec") or 2.5)
        inside_side = str(line.get("inside_side") or "positive")
        anchor = str(line.get("anchor") or "person_center")

        for track in tracks:
            tid = str(track.get("track_id") or "").strip()
            if not tid:
                continue
            current_ids.add(tid)
            point = self._track_anchor(track, fw, fh, anchor)
            if point is None:
                continue
            signed = self._signed_side(point, line)
            side = self._side_name(signed, deadband)
            state = self._track_state.setdefault(tid, {
                "stable_side": "",
                "last_seen": now,
                "last_event": 0.0,
                "last_point": point,
            })
            state["last_seen"] = now
            state["last_point"] = point
            if side == "deadband":
                continue
            previous = str(state.get("stable_side") or "")
            if not previous:
                state["stable_side"] = side
                continue
            if previous == side:
                continue
            state["stable_side"] = side
            if now - float(state.get("last_event") or 0.0) < cooldown:
                continue
            state["last_event"] = now
            direction = "IN" if side == inside_side else "OUT"
            sid, name, code, confidence = self._identity(track)
            detail = {
                "line": {
                    "name": line.get("name"),
                    "inside_side": inside_side,
                    "from_side": previous,
                    "to_side": side,
                    "point": [round(point[0], 5), round(point[1], 5)],
                    "deadband": deadband,
                },
                "track_source": track_source,
                "full_name": name,
                "student_code": code,
                "recognized": bool(track.get("recognized")),
            }
            try:
                event = add_office_crossing_event(
                    student_id=sid,
                    track_id=tid,
                    direction=direction,
                    confidence=confidence,
                    camera_source=camera_source,
                    line_name=str(line.get("name") or "Cửa văn phòng"),
                    detail=detail,
                )
            except Exception as exc:
                self._last_error = str(exc)
                event = {"id": 0, "event_at": "", "direction": direction}

            # Mirror authoritative gate crossings into the low-volume HR timeline and
            # open/close the employee presence session. Unknown tracks are preserved in
            # crossing history but do not create an employee session.
            if sid is not None and not bool(event.get("deduplicated")):
                if direction == "OUT":
                    self._outside_students[sid] = now
                    closed = close_presence_session(sid, end_reason="VIRTUAL_GATE_OUT", detail={"line_name": line.get("name")})
                    self._emit_hr_transition(
                        sid, tid, "EXIT", now, camera_source,
                        {"full_name": name, "student_code": code, "line_name": line.get("name"), "session_id": (closed or {}).get("id")},
                        dedup_seconds=max(5.0, cooldown),
                    )
                    self._employee_state.pop(sid, None)
                else:
                    self._outside_students.pop(sid, None)
                    prior_closed = fetchone(
                        "SELECT id FROM hr_presence_sessions WHERE student_id=? AND status='CLOSED' ORDER BY id DESC LIMIT 1",
                        (sid,),
                    )
                    opened = open_presence_session(sid, tid, camera_source, start_reason="VIRTUAL_GATE_IN", detail={"line_name": line.get("name")})
                    self._emit_hr_transition(
                        sid, tid, "RETURN" if prior_closed else "ENTRY", now, camera_source,
                        {"full_name": name, "student_code": code, "line_name": line.get("name"), "session_id": opened.get("id")},
                        dedup_seconds=max(5.0, cooldown),
                    )

            public = {
                **event,
                "track_id": tid,
                "student_id": sid,
                "full_name": name,
                "student_code": code,
                "confidence": confidence,
                "camera_source": camera_source,
                "line_name": str(line.get("name") or "Cửa văn phòng"),
                "direction": direction,
            }
            with self._lock:
                self._events.appendleft(public)
                self._crossing_total += 1

        for tid, state in list(self._track_state.items()):
            if tid not in current_ids and now - float(state.get("last_seen") or 0.0) > 3.5:
                self._track_state.pop(tid, None)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = time.time()
                self._process_once(now)
                self._last_tick_at = now
                self._last_error = ""
            except Exception as exc:
                self._last_error = str(exc)
            self._stop.wait(0.08)

    def realtime_state(self) -> list[dict[str, Any]]:
        """Return volatile employee state for UI; no per-frame database writes."""
        cfg = self.config().get("hr_tracking") or {}
        lost_after = float(cfg.get("lost_after_sec") or 20.0)
        now = time.time()
        with self._lock:
            snapshot = [(int(sid), dict(state)) for sid, state in self._employee_state.items()]
        rows: list[dict[str, Any]] = []
        for sid, state in snapshot:
            last_seen = float(state.get("last_seen") or 0.0)
            missing = max(0.0, now - last_seen) if last_seen > 0 else 0.0
            observation = "TEMPORARILY_LOST" if missing >= lost_after else "VISIBLE"
            rows.append({
                "student_id": sid,
                "student_code": str(state.get("student_code") or ""),
                "full_name": str(state.get("full_name") or ""),
                "track_id": str(state.get("track_id") or ""),
                "status": str(state.get("stable_status") or "PRESENT"),
                "observation_state": observation,
                "visible": observation == "VISIBLE",
                "last_seen_epoch": last_seen,
                "missing_sec": round(missing, 1),
                "session_id": int(state.get("session_id") or 0),
                "confidence": float(state.get("confidence") or 0.0),
            })
        rows.sort(key=lambda x: (not bool(x.get("visible")), str(x.get("full_name") or "")))
        return rows

    def status(self) -> dict[str, Any]:
        cfg = self.config()
        summary = {"in_today": 0, "out_today": 0, "occupancy_estimate": 0}
        try:
            summary.update(office_crossing_summary())
        except Exception:
            pass
        with self._lock:
            return {
                "ok": True,
                "running": bool(self._thread and self._thread.is_alive()),
                "monitoring_enabled": bool(cfg.get("monitoring_enabled")),
                "line": cfg.get("line") or {},
                "active_track_states": len(self._track_state),
                "active_employee_states": len(self._employee_state),
                "outside_employee_states": len(self._outside_students),
                "current_presence": len(self._employee_state),
                "temporarily_lost": sum(1 for x in self._employee_state.values() if str(x.get("observation_state") or "") == "TEMPORARILY_LOST"),
                "crossing_total_runtime": int(self._crossing_total),
                "last_tick_at": self._last_tick_at,
                "error": self._last_error,
                **summary,
            }

    def latest(self) -> dict[str, Any]:
        result = CAMERA.latest_result()
        camera = CAMERA.status()
        try:
            performance = CAMERA.performance_status()
        except Exception:
            performance = {}
        persons = [dict(x) for x in result.get("tracks") or []]
        return {
            "ok": True,
            "office": self.status(),
            "camera": camera,
            "performance": performance,
            "observer": {
                "running": bool(camera.get("running")),
                "updated_at": time.time(),
                "frame_width": int(result.get("frame_width") or camera.get("actual_width") or 0),
                "frame_height": int(result.get("frame_height") or camera.get("actual_height") or 0),
                "tracks": persons,
                "mode": "IDENTITY_ONLY",
            },
            "persons": persons,
            "realtime_employees": self.realtime_state(),
            "stats": {
                "persons": len(persons),
                "recognized": sum(1 for x in persons if bool(x.get("recognized"))),
                "customers": sum(1 for x in persons if not bool(x.get("recognized")) and not bool(x.get("spoof_blocked"))),
            },
        }

    def events(self, limit: int = 30) -> list[dict[str, Any]]:
        try:
            return office_crossing_history(limit)
        except Exception:
            with self._lock:
                return [dict(x) for x in list(self._events)[: max(1, min(100, int(limit)))]]


OFFICE = OfficeEngine()
