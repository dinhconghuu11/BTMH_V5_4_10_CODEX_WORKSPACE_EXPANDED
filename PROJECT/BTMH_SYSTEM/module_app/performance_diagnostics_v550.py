"""Allowlisted observations of existing owners; never collect or recover on reads.

Public status methods can open sockets, probe GPU drivers, load models or trigger
recovery. This module instead copies retained state under nonblocking locks. An
unavailable, invalid or stale observation is represented by None, not a pass.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import sys
import time


RESOURCE_FRESH_SEC = 15.0
GATEWAY_FRESH_SEC = 10.0
CAMERA_STALE_SEC = 1.3
AI_RESULT_FRESH_SEC = 2.0
FLEET_FRAME_FRESH_SEC = 4.0
CAMERA_STATES = frozenset({"STOPPED", "STOPPING", "OPENING", "ONLINE", "RECONNECTING", "ERROR"})
QUALITY_STATES = frozenset({"UNKNOWN", "POOR", "FAIR", "GOOD"})
LOAD_STATES = frozenset({"FIXED", "NORMAL", "BUSY", "HIGH", "RECOVERING"})
CAPTURE_STATES = frozenset({"READY", "OPENING", "MAIN_FALLBACK", "STOPPED"})
GATEWAY_STATES = frozenset({"UNKNOWN", "STOPPED", "READY", "ERROR", "CONNECTING", "IDLE", "RETIREMENT_BLOCKED"})
GPU_MODES = frozenset({"CPU", "GPU_DETECTED", "GPU_ASSISTED"})
SMALL_REASONS = frozenset({
    "", "SMALL_NOT_VALIDATED", "SMALL_UNAVAILABLE", "SMALL_DISABLED", "SMALL_SOURCE_REJECTED",
    "SMALL_GATEWAY_UNAVAILABLE", "SMALL_CONFIG_FAILED", "SMALL_NEGOTIATION_FAILED",
    "SUBSTREAM_NOT_READY", "SUBSTREAM_CONNECTING", "SOURCE_NOT_REGISTERED", "SUBSTREAM_STALE",
    "SUBSTREAM_DISABLED", "NO_KNOWN_SUBSTREAM", "CAMERA_NOT_ACTIVE", "GATEWAY_SOURCE_CHANGED", "ADAPTIVE_DISABLED",
})
CAPTURE_REASONS = SMALL_REASONS | frozenset({
    "NOT_CONFIGURED", "SUBSTREAM_STOPPED", "SUBSTREAM_RETIRE_FAILED", "SUBSTREAM_AUTH_FAILED",
    "SUBSTREAM_PATH_NOT_FOUND", "SUBSTREAM_MASKED_CREDENTIALS", "SUBSTREAM_INVALID_SOURCE",
    "SUBSTREAM_UNREACHABLE", "SUBSTREAM_CONNECTION_REFUSED", "SUBSTREAM_TIMEOUT",
    "SUBSTREAM_DECODER_ERROR", "SUBSTREAM_DECODER_UNAVAILABLE", "SUBSTREAM_DECODER_OPTIONS",
    "SUBSTREAM_DECODER_PROTOCOL", "SUBSTREAM_DECODER_RETIRE_FAILED", "SUBSTREAM_NO_VIDEO_STREAM",
    "SUBSTREAM_FRAME_TOO_LARGE", "SUBSTREAM_CAMERA_BUSY",
})


def _map(value):
    return value if type(value) is dict else {}


def _number(value, *, maximum=None, integer=False, positive=False):
    # In particular bool, numeric strings and non-finite JSON numbers are invalid.
    if type(value) not in (int, float):
        return None
    try:
        if not math.isfinite(value) or value < 0 or (positive and value <= 0):
            return None
        if maximum is not None and value > maximum:
            return None
        if integer:
            return int(value) if int(value) == value else None
        return round(float(value), 3)
    except (OverflowError, ValueError):
        return None


def _boolean(value):
    return value if type(value) is bool else None


def _enum(value, allowed):
    clean = value.upper() if type(value) is str else None
    return clean if clean in allowed else None


def _age_ms(now, at):
    if _number(at, positive=True) is None or at > now:
        return None
    return round((now - at) * 1000.0, 1)


def _snapshot(owner, fields, lock_name="_lock"):
    """Copy only requested private attributes without waiting on an active owner."""
    try:
        attrs = vars(owner)
        lock = attrs.get(lock_name)
        if lock is None or not lock.acquire(blocking=False):
            return None
        try:
            result = {key: dict(attrs[key]) if type(attrs.get(key)) is dict else attrs.get(key)
                      for key in fields}
            if type(result.get("_leases")) is dict:
                result["_leases"] = {key: dict(values) if type(values) is dict else None
                                     for key, values in result["_leases"].items()}
            status = _map(result.get("_status"))
            if type(status.get("ai_metrics")) is dict:
                metrics = status["ai_metrics"]
                status["ai_metrics"] = {key: dict(metrics[key]) if type(metrics.get(key)) is dict else None
                                        for key in ("pad", "faceid")}
            return result
        finally:
            lock.release()
    except (TypeError, AttributeError):
        return None


def safe_camera_status(raw):
    """Drop source paths, errors, labels, identities and unknown nested fields."""
    raw = _map(raw)
    result = {key: _boolean(raw.get(key)) for key in (
        "running", "opened", "recognition_paused", "handover_active", "recovery_blocked",
        "retry_blocked", "ptz_guard_active", "safe_decoder_shutdown",
    )}
    result.update({key: _number(raw.get(key), integer=True, positive=True) for key in (
        "actual_width", "actual_height", "requested_width", "requested_height", "ai_input_width",
        "ai_input_height",
    )})
    result.update({key: _number(raw.get(key), integer=True) for key in (
        "visible_tracks", "visible_faces", "reconnect_count", "dropped_for_ai",
        "pipeline_backlog", "ptz_guard_remaining_ms",
    )})
    result.update({key: _number(raw.get(key)) for key in (
        "capture_fps", "preview_fps", "observation_preview_fps", "ai_fps", "last_frame_age_ms",
        "last_ai_ms", "avg_ai_ms", "p95_ai_ms", "observation_encode_ms", "sharpness_score",
        "brightness", "contrast", "decoder_output_fps", "retry_in_sec",
    )})
    result.update(state=_enum(raw.get("state"), CAMERA_STATES),
                  camera_quality=_enum(raw.get("camera_quality"), QUALITY_STATES),
                  ai_load_state=_enum(raw.get("ai_load_state"), LOAD_STATES))
    return result


def _lane(raw, fresh):
    raw = _map(raw)
    completed = _number(raw.get("completed"), integer=True)
    result = {key: _number(raw.get(key), integer=True) if fresh else None for key in (
        "pending", "completed", "dropped", "errors", "restarts",
    )}
    result["pending"] = _number(raw.get("pending"), maximum=1, integer=True) if fresh else None
    result.update({key: _boolean(raw.get(key)) if fresh else None for key in (
        "busy", "alive", "stopping", "stalled",
    )})
    result["fps"] = _number(raw.get("fps")) if fresh else None
    result.update({key: _number(raw.get(key)) if fresh and completed and completed > 0 else None
                   for key in ("last_ms", "last_latency_ms", "last_result_age_ms")})
    return result


def _camera(owner, now):
    snapshot = _snapshot(owner, ("_status", "_frame_at", "_jpeg_at", "_observation_jpeg_at", "_ai_result_at",
                                 "_capture_total", "_ai_total", "_frame_seq", "_performance_effective_fps",
                                 "_performance_load_state", "_ai_capture")) or {}
    raw = _map(snapshot.get("_status"))
    camera = safe_camera_status(raw)
    frame_age = _age_ms(now, snapshot.get("_frame_at"))
    camera["last_frame_age_ms"] = frame_age
    if camera["state"] == "ONLINE" and (frame_age is None or frame_age > CAMERA_STALE_SEC * 1000):
        camera.update(opened=False, state="RECONNECTING")
    capture_total = _number(snapshot.get("_capture_total"), integer=True)
    frame_fresh = bool(frame_age is not None and frame_age <= CAMERA_STALE_SEC * 1000)
    if not capture_total or not frame_fresh:
        camera["capture_fps"] = None
    preview_at = max(_number(snapshot.get("_jpeg_at")) or 0,
                     _number(snapshot.get("_observation_jpeg_at")) or 0)
    preview_age = _age_ms(now, preview_at)
    if preview_age is None or preview_age > CAMERA_STALE_SEC * 1000:
        camera["preview_fps"] = camera["observation_preview_fps"] = camera["observation_encode_ms"] = None
    ai_age = _age_ms(now, snapshot.get("_ai_result_at"))
    ai_total = _number(snapshot.get("_ai_total"), integer=True)
    fresh = bool(ai_age is not None and ai_age <= AI_RESULT_FRESH_SEC * 1000 and ai_total)
    if not fresh:
        for key in ("ai_fps", "last_ai_ms", "avg_ai_ms", "p95_ai_ms", "visible_tracks", "visible_faces"):
            camera[key] = None
    if not frame_fresh or camera["camera_quality"] == "UNKNOWN":
        for key in ("sharpness_score", "brightness", "contrast"):
            camera[key] = None
    dropped = _number(raw.get("dropped_for_ai"), integer=True)
    sequence = _number(snapshot.get("_frame_seq"), integer=True, positive=True)
    metrics = _map(raw.get("ai_metrics"))
    ai = {
        "sample_age_ms": ai_age, "fresh": fresh,
        "actual_fps": _number(raw.get("ai_fps")) if fresh else None,
        "target_fps": _number(snapshot.get("_performance_effective_fps")),
        "base_target_fps": _number(raw.get("ai_target_fps_base")),
        "load_state": _enum(snapshot.get("_performance_load_state"), LOAD_STATES),
        "capture_total": capture_total, "ai_total": ai_total,
        "dropped_frames": dropped,
        "drop_ratio": round(min(1.0, dropped / sequence), 4) if dropped is not None and sequence else None,
        "visible_tracks": _number(raw.get("visible_tracks"), integer=True) if fresh else None,
        "visible_faces": _number(raw.get("visible_faces"), integer=True) if fresh else None,
        "queue_depth": _number(raw.get("pipeline_backlog"), integer=True),
        "preview_server_age_ms": _age_ms(now, snapshot.get("_observation_jpeg_at") or snapshot.get("_frame_at")),
        "tracking_result_age_ms": ai_age,
        # No separate detector/tracker measurements currently exist.
        "detector_ms": None, "tracker_ms": None,
        "faceid": _lane(metrics.get("faceid"), fresh), "pad": _lane(metrics.get("pad"), fresh),
    }
    ai.update({key: _number(raw.get(source)) if fresh else None
               for key, source in (("last_ms", "last_ai_ms"), ("avg_ms", "avg_ai_ms"), ("p95_ms", "p95_ai_ms"))})
    return camera, ai, snapshot.get("_ai_capture")


def _ai_capture(owner, now):
    snapshot = _snapshot(owner, ("_latest", "_state", "_reason", "_blocked", "_retry_at", "_source_epoch",
                                 "_reconnects", "_capture_fps")) or {}
    packet = snapshot.get("_latest")
    attrs = vars(packet) if hasattr(packet, "__dict__") else {}
    age = _age_ms(now, attrs.get("at"))
    # Read a previously loaded config; importing it here could create runtime paths.
    config = sys.modules.get("module_app.config")
    config_vars = vars(config) if config is not None else {}
    limit = _number(config_vars.get("AI_SUBSTREAM_MAX_AGE_SEC"), positive=True) or .75
    state = _enum(snapshot.get("_state"), CAPTURE_STATES)
    ready = bool(state == "READY" and attrs.get("frame") is not None and age is not None and age <= limit * 1000
                 and _number(attrs.get("source_epoch"), integer=True) is not None
                 and attrs.get("source_epoch") == snapshot.get("_source_epoch"))
    reason = _enum(snapshot.get("_reason"), CAPTURE_REASONS)
    if state == "READY" and not ready:
        state, reason = "MAIN_FALLBACK", "SUBSTREAM_STALE"
    retry_at = _number(snapshot.get("_retry_at"))
    return {
        "state": state, "mode": "HIKVISION_SUBSTREAM" if ready else "MAIN_FALLBACK" if snapshot else None,
        "fallback_reason": "" if ready else reason, "frame_age_ms": age,
        "capture_fps": _number(snapshot.get("_capture_fps")) if age is not None else None,
        "reconnect_count": _number(snapshot.get("_reconnects"), integer=True),
        "retry_blocked": _boolean(snapshot.get("_blocked")),
        "retry_in_sec": round(max(0.0, retry_at - now), 1) if retry_at is not None else None,
        "queue_depth": 0 if snapshot else None, "latest_slot_capacity": 1 if snapshot else None,
    }


def _cached_exit(process):
    # Popen.poll() would update state and query the OS. Read its last observation.
    try:
        attrs = vars(process)
        return "returncode" in attrs, attrs.get("returncode")
    except TypeError:
        return False, None


def _gateway(owner, mono):
    snapshot = _snapshot(owner, ("_process", "_desired", "_retire_failed", "_restart_count",
                                 "_next_restart_at", "_sessions", "_pending_sessions", "_small_retired_sessions",
                                 "_small_configured", "_small_fallback_reason", "_diagnostics", "_diagnostics_at")) or {}
    cached = _map(snapshot.get("_diagnostics"))
    age = _age_ms(mono, snapshot.get("_diagnostics_at"))
    fresh = bool(age is not None and age <= GATEWAY_FRESH_SEC * 1000)
    process = snapshot.get("_process")
    known, exit_code = _cached_exit(process)
    alive = bool(process is not None and exit_code is None) if known else False if snapshot and process is None else None
    retiring = _boolean(snapshot.get("_retire_failed"))
    ready = bool(snapshot.get("_desired") is True and alive and not retiring and cached.get("api_ready") is True)
    restart_at = _number(snapshot.get("_next_restart_at"))
    result = {
        "sample_age_ms": age, "fresh": fresh,
        "process_owned": process is not None if snapshot else None,
        "process_alive": alive if fresh or alive is False else None,
        "available": False if retiring or alive is False else ready if fresh else None,
        "retirement_blocked": retiring, "restart_count": _number(snapshot.get("_restart_count"), integer=True),
        "restart_backoff_ms": round(max(0.0, restart_at - mono) * 1000) if restart_at is not None else None,
        "source_state": "RETIREMENT_BLOCKED" if retiring else _enum(cached.get("source_state"), GATEWAY_STATES) if fresh else None,
        "source_healthy": _boolean(cached.get("source_healthy")) if fresh and alive and not retiring else None,
        "app_session_count": len(_map(snapshot.get("_sessions"))) if snapshot else None,
        "pending_session_count": len(_map(snapshot.get("_pending_sessions"))) if snapshot else None,
        "retired_session_count": len(_map(snapshot.get("_small_retired_sessions"))) if snapshot else None,
        "small_available": False if retiring or alive is False else bool(ready and snapshot.get("_small_configured") is True) if fresh else None,
        "small_fallback_reason": _enum(snapshot.get("_small_fallback_reason"), SMALL_REASONS),
    }
    result.update({key: _number(cached.get(key), integer=True) if fresh else None
                   for key in ("source_reader_count", "webrtc_session_count", "webrtc_connected_count")})
    return result


def _recorder(owner):
    snapshot = _snapshot(owner, ("_processes", "_last_error", "_restart_count", "_running")) or {}
    processes = _map(snapshot.get("_processes"))
    observations = [_cached_exit(process) for process in processes.values()]
    counts = [_number(value, integer=True) for value in _map(snapshot.get("_restart_count")).values()]
    return {
        "running": _boolean(snapshot.get("_running")),
        "owned_count": len(processes) if snapshot else None,
        "active_count": sum(code is None for _, code in observations) if snapshot and all(known for known, _ in observations) else None,
        "error_count": sum(type(value) is str and bool(value) for value in _map(snapshot.get("_last_error")).values()) if snapshot else None,
        "restart_count": sum(counts) if snapshot and all(count is not None for count in counts) else None,
    }


def _fleet(owner, now):
    snapshot = _snapshot(owner, ("workers", "_leases", "_reserved"), lock_name="lock") or {}
    workers = _map(snapshot.get("workers"))
    observations = [_snapshot(worker, ("running", "opened", "latest_jpeg", "latest_at", "reconnects", "_blocked_code"),
                              lock_name="lock") for worker in workers.values()]
    complete = bool(snapshot and all(item is not None for item in observations))
    online = running = blocked = reconnects = 0
    for item in observations:
        if item is None:
            continue
        running += item.get("running") is True
        age = _age_ms(now, item.get("latest_at"))
        online += bool(item.get("running") is True and item.get("opened") is True and item.get("latest_jpeg")
                       and age is not None and age < FLEET_FRAME_FRESH_SEC * 1000)
        blocked += bool(type(item.get("_blocked_code")) is str and item["_blocked_code"])
        count = _number(item.get("reconnects"), integer=True)
        reconnects = reconnects + count if reconnects is not None and count is not None else None
    leases = _map(snapshot.get("_leases"))
    reader_count = sum(_number(deadline) is not None and deadline > now
                       for values in leases.values() for deadline in _map(values).values())
    return {
        "worker_count": len(workers) if snapshot else None,
        "running_count": running if complete else None, "online_count": online if complete else None,
        "reader_count": reader_count if snapshot else None,
        "reserved_count": sum(_number(value, integer=True) is not None and value > 0
                              for value in _map(snapshot.get("_reserved")).values()) if snapshot else None,
        "reconnect_count": reconnects if complete else None, "retry_blocked_count": blocked if complete else None,
    }


def _resources(owner, wall):
    snapshot = _snapshot(owner, ("_latest",)) or {}
    latest = _map(snapshot.get("_latest"))
    stamp = latest.get("generated_at")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if type(stamp) is str else None
        at = parsed.timestamp() if parsed is not None and parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        at = None
    age = _age_ms(wall, at)
    fresh = bool(age is not None and age <= RESOURCE_FRESH_SEC * 1000)
    raw, gpu = _map(latest.get("resources")), _map(latest.get("gpu"))
    ram_known = _number(raw.get("ram_total_bytes"), integer=True, positive=True) is not None
    gpu_measured = gpu.get("nvidia_driver_visible") is True
    gpu_memory_known = gpu_measured or gpu.get("torch_cuda") is True
    result = {"sample_age_ms": age, "fresh": fresh, "available": bool(fresh and raw)}
    result["cpu_percent"] = _number(raw.get("cpu_percent"), maximum=100) if fresh else None
    result["ram_percent"] = _number(raw.get("ram_percent"), maximum=100) if fresh and ram_known else None
    result.update({key: _number(raw.get(key), integer=True, positive=key != "ram_used_bytes") if fresh and ram_known else None
                   for key in ("ram_used_bytes", "ram_total_bytes")})
    result["process_rss_bytes"] = _number(raw.get("process_rss_bytes"), integer=True, positive=True) if fresh else None
    result["gpu_utilization_percent"] = _number(gpu.get("utilization_percent"), maximum=100) if fresh and gpu_measured else None
    result.update({key: _number(gpu.get(source), positive=source == "memory_total_mb") if fresh and gpu_memory_known else None
                   for key, source in (("gpu_memory_used_mb", "memory_used_mb"), ("gpu_memory_total_mb", "memory_total_mb"))})
    result["gpu_mode"] = _enum(gpu.get("mode"), GPU_MODES) if fresh else None
    return result


def collect_performance_diagnostics(camera, gateway, recorder, fleet, pilot):
    """A read-only, credential-free snapshot suitable for diagnostics RBAC."""
    perf, mono, wall = time.perf_counter(), time.monotonic(), time.time()
    camera_status, ai, capture = _camera(camera, perf)
    return {
        "schema_version": 1, "generated_at": datetime.fromtimestamp(wall, timezone.utc).isoformat(),
        "camera": camera_status, "ai": ai, "ai_capture": _ai_capture(capture, perf),
        "native_gateway": _gateway(gateway, mono), "recorder": _recorder(recorder),
        "fleet": _fleet(fleet, perf), "resources": _resources(pilot, wall),
    }
