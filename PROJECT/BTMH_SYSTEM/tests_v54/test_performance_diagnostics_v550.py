"""Diagnostics reads expose observations, never credentialed runtime objects."""
from datetime import datetime, timezone
import json
import threading
from types import SimpleNamespace

import pytest

from module_app import performance_diagnostics_v550 as module


SECRET = "FakeDiagnosticsSecret"
SOURCE = "rtsp://fake:FakeDiagnosticsSecret@camera.invalid/Streaming/Channels/101?token=FakeToken"


def forbidden(*args, **kwargs):
    raise AssertionError("diagnostics triggered collection, I/O or lifecycle mutation")


def owner(**attrs):
    return SimpleNamespace(_lock=threading.RLock(), status=forbidden, performance_status=forbidden,
                           force_check=forbidden, ensure=forbidden, restart=forbidden,
                           acquire=forbidden, sweep_idle=forbidden, _http_request=forbidden,
                           _port_open=forbidden, **attrs)


def process(code=None):
    return SimpleNamespace(returncode=code, poll=forbidden, wait=forbidden,
                           terminate=forbidden, kill=forbidden, args=SOURCE)


@pytest.fixture
def rig(monkeypatch):
    clock = SimpleNamespace(perf=100.0, mono=200.0, wall=1_700_000_000.0)
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock.perf)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.mono)
    monkeypatch.setattr(module.time, "time", lambda: clock.wall)
    lane = dict(pending=1, busy=True, alive=True, stopping=False, completed=5,
                dropped=2, errors=0, fps=2.5, last_ms=42.0, last_latency_ms=55.0,
                last_result_age_ms=100.0, stalled=False, restarts=1,
                source=SOURCE, error=SECRET, unknown={"password": SECRET})
    capture = owner(_latest=SimpleNamespace(frame=object(), seq=7, at=99.8, source_epoch=4),
                    _source_epoch=4, _state="READY", _reason="", _blocked=False,
                    _retry_at=0.0, _reconnects=2, _capture_fps=10., _source=SOURCE)
    camera = owner(_status=dict(running=True, opened=True, state="online", camera_quality="GOOD",
                               capture_fps=25.0, preview_fps=20.0, ai_fps=7.0,
                               actual_width=1920, actual_height=1080, reconnect_count=3,
                               last_ai_ms=65., avg_ai_ms=50., p95_ai_ms=80.,
                               dropped_for_ai=30, ai_target_fps_base=10.0,
                               visible_tracks=2, visible_faces=2, pipeline_backlog=0,
                               ai_metrics={"pad": dict(lane), "faceid": dict(lane)},
                               source=SOURCE, source_label=SECRET, error=SOURCE,
                               latest_event={"employee_name": SECRET}, unknown=SECRET),
                   _frame_at=99.9, _observation_jpeg_at=99.8, _ai_result_at=99.9,
                   _capture_total=100, _ai_total=50, _frame_seq=100,
                   _performance_effective_fps=8.0, _performance_load_state="BUSY", _ai_capture=capture)
    gateway = owner(_process=process(), _desired=True, _retire_failed=False,
                    _restart_count=3, _next_restart_at=202., _sessions={SECRET: {"source": SOURCE}},
                    _pending_sessions={SECRET: SECRET}, _small_retired_sessions={},
                    _small_configured=True, _small_fallback_reason="", _diagnostics_at=199.,
                    _diagnostics=dict(api_ready=True, source_healthy=True, source_state="READY",
                                      source_reader_count=2, webrtc_session_count=2, webrtc_connected_count=1,
                                      source_error=SOURCE, diagnostics_error=SECRET),
                    _source=SOURCE, _internal_password=SECRET)
    recorder = owner(_processes={1: process(), 2: process(1)}, _last_error={2: SOURCE},
                     _restart_count={1: 1, 2: 3}, _running=True, _sources={1: SOURCE})
    worker = SimpleNamespace(lock=threading.RLock(), running=True, opened=True,
                             latest_jpeg=b"jpeg", latest_at=99.5, reconnects=2,
                             _blocked_code="", source=SOURCE, name=SECRET,
                             status=forbidden, start=forbidden)
    fleet = SimpleNamespace(lock=threading.RLock(), workers={1: worker},
                            _leases={1: {SECRET: 103., "expired": 99.}}, _reserved={2: 1},
                            ensure=forbidden, acquire=forbidden, sweep_idle=forbidden)
    pilot = owner(_latest=dict(generated_at=datetime.fromtimestamp(clock.wall - 2, timezone.utc).isoformat(),
                              resources=dict(cpu_percent=34., ram_percent=42., ram_used_bytes=420,
                                             ram_total_bytes=1000, process_rss_bytes=100, root=SOURCE),
                              gpu=dict(mode="GPU_ASSISTED", nvidia_driver_visible=True, torch_cuda=True,
                                       utilization_percent=50., memory_used_mb=500., memory_total_mb=2000.,
                                       name=SECRET, error=SOURCE), config={"password": SECRET}))
    return SimpleNamespace(clock=clock, camera=camera, capture=capture, gateway=gateway,
                           recorder=recorder, fleet=fleet, pilot=pilot)


def collect(rig):
    return module.collect_performance_diagnostics(rig.camera, rig.gateway, rig.recorder, rig.fleet, rig.pilot)


def test_observations_expose_actual_bounded_metrics_without_collecting_or_polling(rig):
    result = collect(rig)
    assert result["camera"]["capture_fps"] == 25.0
    assert result["camera"]["state"] == "ONLINE"
    assert result["ai"]["target_fps"] == 8.0 and result["ai"]["drop_ratio"] == .3
    assert result["ai"]["pad"]["pending"] == 1 and result["ai"]["faceid"]["last_ms"] == 42.0
    assert result["ai"]["detector_ms"] is None and result["ai"]["tracker_ms"] is None
    assert result["ai_capture"]["mode"] == "HIKVISION_SUBSTREAM"
    assert result["native_gateway"]["process_owned"] and result["native_gateway"]["small_available"]
    assert result["native_gateway"]["restart_backoff_ms"] == 2000
    assert result["recorder"] == dict(running=True, owned_count=2, active_count=1, error_count=1, restart_count=4)
    assert result["fleet"]["online_count"] == 1 and result["fleet"]["reader_count"] == 1
    assert result["resources"]["cpu_percent"] == 34.0 and result["resources"]["sample_age_ms"] == 2000


def test_poisoned_fields_sources_identities_paths_and_errors_never_escape(rig):
    encoded = json.dumps(collect(rig), allow_nan=False)
    for poison in (SECRET, SOURCE, "FakeToken", "camera.invalid", "employee_name", "password", "source_label"):
        assert poison not in encoded
    assert "PASS" not in encoded
    assert set(collect(rig)) == {"schema_version", "generated_at", "camera", "ai", "ai_capture",
                                 "native_gateway", "recorder", "fleet", "resources"}


@pytest.mark.parametrize("value", [True, "12", float("nan"), float("inf"), -1, {}, 10**400])
def test_untrusted_number_types_are_null_and_json_remains_valid(rig, value):
    rig.camera._status["capture_fps"] = value
    rig.camera._status["ai_metrics"]["pad"]["last_ms"] = value
    rig.pilot._latest["resources"]["cpu_percent"] = value
    result = collect(rig)
    assert result["camera"]["capture_fps"] is None
    assert result["ai"]["pad"]["last_ms"] is None
    assert result["resources"]["cpu_percent"] is None
    json.dumps(result, allow_nan=False)


def test_numeric_bounds_and_enum_membership_are_strict(rig):
    rig.pilot._latest["resources"]["cpu_percent"] = 101
    rig.camera._status["state"] = SOURCE
    rig.camera._performance_load_state = SECRET
    rig.capture._reason = SOURCE
    rig.gateway._small_fallback_reason = SOURCE
    rig.gateway._diagnostics["source_state"] = SECRET
    rig.pilot._latest["gpu"]["mode"] = SOURCE
    rig.camera._status["ai_metrics"]["pad"]["pending"] = 2
    result = collect(rig)
    assert result["camera"]["state"] is None
    assert result["ai"]["load_state"] is None and result["ai"]["pad"]["pending"] is None
    assert result["native_gateway"]["source_state"] is None
    assert result["native_gateway"]["small_fallback_reason"] is None
    assert result["resources"]["cpu_percent"] is None and result["resources"]["gpu_mode"] is None
    assert SOURCE not in json.dumps(result)


def test_cold_components_and_missing_measurements_remain_unknown():
    result = module.collect_performance_diagnostics(owner(), owner(), owner(),
                                                    SimpleNamespace(lock=threading.Lock()), owner())
    assert result["camera"]["capture_fps"] is None
    assert result["ai"]["actual_fps"] is None and result["ai"]["pad"]["last_ms"] is None
    assert result["resources"]["cpu_percent"] is None and not result["resources"]["available"]
    assert result["native_gateway"]["available"] is False  # No retained process is known.
    assert result["fleet"]["worker_count"] == 0


def test_initial_and_stale_fps_geometry_do_not_look_measured(rig):
    rig.camera._capture_total = rig.camera._ai_total = 0
    rig.camera._frame_at = rig.camera._ai_result_at = rig.camera._observation_jpeg_at = 0.
    rig.camera._status.update(capture_fps=0., preview_fps=0., ai_fps=0., actual_width=0,
                             actual_height=0, camera_quality="UNKNOWN", brightness=0.)
    result = collect(rig)
    for key in ("capture_fps", "preview_fps", "ai_fps", "last_ai_ms", "actual_width", "actual_height", "brightness"):
        assert result["camera"][key] is None


@pytest.mark.parametrize("delta", [20., -10.])
def test_stale_or_future_resource_samples_are_null_with_honest_age(rig, delta):
    rig.pilot._latest["generated_at"] = datetime.fromtimestamp(rig.clock.wall - delta, timezone.utc).isoformat()
    result = collect(rig)["resources"]
    assert not result["fresh"] and not result["available"]
    assert result["sample_age_ms"] == (delta * 1000 if delta > 0 else None)
    for key in ("cpu_percent", "ram_percent", "process_rss_bytes", "gpu_utilization_percent", "gpu_mode"):
        assert result[key] is None


def test_unavailable_gpu_probe_and_zero_sampler_fallback_are_not_fake_measurements(rig):
    rig.pilot._latest["gpu"].update(nvidia_driver_visible=False, torch_cuda=False,
                                   utilization_percent=0., memory_used_mb=0., memory_total_mb=0., mode="CPU")
    rig.pilot._latest["resources"].update(ram_total_bytes=0, ram_percent=0., process_rss_bytes=0)
    result = collect(rig)["resources"]
    assert result["gpu_utilization_percent"] is None and result["gpu_memory_total_mb"] is None
    assert result["ram_percent"] is None and result["process_rss_bytes"] is None
    assert result["gpu_mode"] == "CPU"


def test_stale_and_future_frames_fail_closed_without_changing_runtime(rig):
    rig.camera._frame_at = 90.
    rig.camera._ai_result_at = 90.
    rig.capture._latest.at = 101.
    result = collect(rig)
    assert not result["camera"]["opened"] and result["camera"]["state"] == "RECONNECTING"
    assert result["ai"]["actual_fps"] is None and result["ai"]["pad"]["pending"] is None
    assert result["ai_capture"]["mode"] == "MAIN_FALLBACK" and result["ai_capture"]["frame_age_ms"] is None
    assert rig.camera._status["opened"] and rig.camera._status["state"] == "online"


def test_wrong_capture_epoch_cannot_be_reported_ready(rig):
    rig.capture._latest.source_epoch = 3
    result = collect(rig)["ai_capture"]
    assert result["mode"] == "MAIN_FALLBACK" and result["fallback_reason"] == "SUBSTREAM_STALE"


def test_stale_gateway_cache_is_unknown_and_retirement_is_always_fail_closed(rig):
    rig.gateway._diagnostics_at = 100.
    result = collect(rig)["native_gateway"]
    assert result["process_owned"] and result["process_alive"] is None
    assert result["available"] is None and result["source_healthy"] is None
    rig.gateway._retire_failed = True
    result = collect(rig)["native_gateway"]
    assert result["source_state"] == "RETIREMENT_BLOCKED"
    assert result["available"] is False and result["small_available"] is False


def test_exited_gateway_cannot_inherit_cached_source_health(rig):
    rig.gateway._process.returncode = 1
    result = collect(rig)["native_gateway"]
    assert result["process_alive"] is False and result["available"] is False
    assert result["source_healthy"] is None and result["small_available"] is False


def test_reads_preserve_sessions_leases_worker_ownership_and_resource_cache(rig):
    before = (dict(rig.gateway._sessions), {key: dict(values) for key, values in rig.fleet._leases.items()},
              dict(rig.fleet.workers), dict(rig.recorder._processes), dict(rig.pilot._latest))
    for _ in range(3):
        collect(rig)
    assert before == (rig.gateway._sessions, rig.fleet._leases, rig.fleet.workers,
                      rig.recorder._processes, rig.pilot._latest)


@pytest.mark.parametrize("kind", ["leases", "ai_metrics"])
def test_nested_snapshot_is_stable_when_owner_mutates_after_copy(rig, monkeypatch, kind):
    copied, mutated = threading.Event(), threading.Event()
    original = module._snapshot
    target = rig.fleet if kind == "leases" else rig.camera

    def intercept(owner, fields, lock_name="_lock"):
        result = original(owner, fields, lock_name)
        if owner is target:
            copied.set()
            assert mutated.wait(2), "mutator did not progress after snapshot released its lock"
        return result

    def mutate():
        assert copied.wait(2)
        lock = rig.fleet.lock if kind == "leases" else rig.camera._lock
        with lock:
            if kind == "leases":
                rig.fleet._leases[1].clear()
                rig.fleet._leases[1]["replacement"] = 105.
                rig.fleet._leases[1]["extra"] = 106.
            else:
                rig.camera._status["ai_metrics"]["pad"].clear()
                rig.camera._status["ai_metrics"]["pad"].update(pending=0, completed=8, last_ms=99.)
        mutated.set()

    monkeypatch.setattr(module, "_snapshot", intercept)
    worker = threading.Thread(target=mutate)
    worker.start()
    try:
        result = collect(rig)
        if kind == "leases":
            assert result["fleet"]["reader_count"] == 1
            assert len(rig.fleet._leases[1]) == 2
        else:
            assert result["ai"]["pad"]["pending"] == 1 and result["ai"]["pad"]["last_ms"] == 42.
    finally:
        mutated.set()
        worker.join(2)
    assert not worker.is_alive()


def test_contended_lock_returns_unknown_without_waiting_or_mutating(rig):
    rig.camera._lock = threading.Lock()
    rig.camera._lock.acquire()
    try:
        result = collect(rig)
        assert result["camera"]["state"] is None and result["ai"]["capture_total"] is None
    finally:
        rig.camera._lock.release()


def test_safe_camera_status_rejects_unknown_nested_fields_and_fractional_counts():
    result = module.safe_camera_status(dict(state="online", actual_width=640, reconnect_count=1.5,
                                           camera_quality="good", capture_fps=25., source=SOURCE,
                                           error=SECRET, handover={"from_source": SOURCE}, performance={"password": SECRET}))
    assert result["state"] == "ONLINE" and result["camera_quality"] == "GOOD"
    assert result["actual_width"] == 640 and result["reconnect_count"] is None
    assert SOURCE not in json.dumps(result) and SECRET not in json.dumps(result)
