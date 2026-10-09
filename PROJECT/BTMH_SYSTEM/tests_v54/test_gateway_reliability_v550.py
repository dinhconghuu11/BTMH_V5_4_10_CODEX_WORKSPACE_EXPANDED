"""Gateway recovery proves retired ownership before any replacement."""
from types import SimpleNamespace

import pytest

from module_app import media_gateway_v5410 as module


class FakeProcess:
    def __init__(self, *, stuck=False):
        self.pid = 123
        self.returncode = None
        self.stuck = stuck
        self.terminations = self.kills = self.waits = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminations += 1
        if not self.stuck:
            self.returncode = 0

    def kill(self):
        self.kills += 1
        if not self.stuck:
            self.returncode = -9

    def wait(self, timeout):
        self.waits += 1
        if self.stuck:
            raise module.subprocess.TimeoutExpired("fake gateway", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.fixture
def rig(tmp_path, monkeypatch):
    gateway = module.NativeMediaGateway()
    gateway._source = "rtsp://test:FakeReliabilitySecret@camera.invalid/Streaming/Channels/101"
    gateway._source_label = "Test camera"
    gateway._desired = True
    gateway._runtime_dir = tmp_path / "runtime"
    gateway._config_dir = tmp_path / "config"
    gateway._config_path = gateway._config_dir / "mediamtx.yml"
    gateway._log_path = tmp_path / "logs" / "gateway.log"
    binary = tmp_path / "mediamtx.exe"
    binary.touch()
    clock = SimpleNamespace(now=100.0)
    processes, calls = [], []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(gateway, "binary_path", lambda: binary)
    monkeypatch.setattr(gateway, "_ensure_watchdog_locked", lambda: None)
    monkeypatch.setattr(gateway, "_refresh_diagnostics_locked", lambda: None)
    monkeypatch.setattr(gateway, "_start_log_pump", lambda *a: None)
    monkeypatch.setattr(gateway, "_port_open", lambda *a:
                        bool(processes and processes[-1].poll() is None))

    def spawn(argv, **kwargs):
        assert gateway._process is None, "replacement overlapped a retained gateway owner"
        process = FakeProcess()
        processes.append(process)
        calls.append((argv, kwargs))
        return process

    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    yield gateway, processes, calls, clock
    if gateway._process is not None:
        gateway._process.stuck = False
    gateway.shutdown()


def test_owned_live_child_is_reused_without_duplicate_spawn_even_before_listeners(rig, monkeypatch):
    gateway, processes, calls, _ = rig
    owner = FakeProcess()
    gateway._process = owner
    monkeypatch.setattr(gateway, "_port_open", lambda *a: False)
    assert not gateway._spawn_locked()
    assert gateway._process is owner and not processes and not calls


def test_failed_restart_retains_owner_fails_closed_and_retries_with_backoff(rig):
    gateway, processes, calls, clock = rig
    assert gateway._spawn_locked()
    owner = processes[0]
    owner.stuck = True
    password = gateway._internal_password
    result = gateway.restart()
    assert not result["started"] and not result["available"]
    assert result["retirement_blocked"] and result["last_error"] == "GATEWAY_STOP_TIMEOUT"
    assert result["source_state"] == "RETIREMENT_BLOCKED"
    assert gateway._process is owner and len(processes) == 1
    assert gateway._internal_password == password
    assert gateway.relay_source(gateway._source) == ""
    waits = owner.waits
    assert gateway._watchdog_tick()
    assert owner.waits == waits and len(calls) == 1
    clock.now += 2
    assert gateway._watchdog_tick()
    assert owner.waits > waits and len(calls) == 1
    assert gateway._failure_count == 2
    owner.stuck = False
    clock.now = gateway._next_restart_at + .1
    assert gateway._watchdog_tick()
    assert owner.poll() is not None and len(processes) == 2
    assert gateway._process is processes[1] and not gateway._retire_failed
    assert gateway._internal_password != password
    assert gateway._ready_locked()
    assert "FakeReliabilitySecret" not in repr(gateway.status())


def test_shutdown_retries_retirement_without_starting_a_new_child(rig):
    gateway, processes, calls, clock = rig
    assert gateway._spawn_locked()
    owner = processes[0]
    owner.stuck = True
    gateway.shutdown()
    assert gateway._process is owner and gateway._retire_failed
    assert gateway._watchdog_tick()  # Wait for the existing retirement backoff.
    owner.stuck = False
    clock.now = gateway._next_restart_at + .1
    assert not gateway._watchdog_tick()
    assert gateway._process is None and len(calls) == 1


def test_exception_after_spawn_reaps_or_retains_the_created_owner(rig, monkeypatch):
    gateway, processes, calls, clock = rig

    def fail_log(proc, source):
        proc.stuck = True
        raise RuntimeError("log pipe failed with FakeReliabilitySecret")

    monkeypatch.setattr(gateway, "_start_log_pump", fail_log)
    assert not gateway._spawn_locked()
    assert gateway._process is processes[0] and gateway._retire_failed
    assert gateway._last_error == "GATEWAY_STOP_TIMEOUT"
    assert not gateway._spawn_locked() and len(calls) == 1
    processes[0].stuck = False
    monkeypatch.setattr(gateway, "_start_log_pump", lambda *a: None)
    clock.now = gateway._next_restart_at + .1
    gateway._watchdog_tick()
    assert len(calls) == 2 and processes[0].poll() is not None


def test_reaped_exception_uses_backoff_before_watchdog_replacement(rig, monkeypatch):
    gateway, processes, calls, clock = rig
    monkeypatch.setattr(gateway, "_start_log_pump", lambda *a: (_ for _ in ()).throw(OSError("fake pipe error")))
    assert not gateway._spawn_locked()
    assert gateway._process is None and processes[0].poll() is not None
    assert not gateway._retire_failed and gateway._failure_count == 1
    gateway._watchdog_tick()
    assert len(calls) == 1
    monkeypatch.setattr(gateway, "_start_log_pump", lambda *a: None)
    clock.now = gateway._next_restart_at + .1
    gateway._watchdog_tick()
    assert len(calls) == 2


def test_crash_recovery_rotates_main_auth_and_discards_old_session_metadata(rig):
    gateway, processes, calls, _ = rig
    assert gateway._spawn_locked()
    old = processes[0]
    password, generation = gateway._internal_password, gateway._generation
    gateway._sessions["old"] = {"owner": "viewer"}
    gateway._pending_sessions["pending"] = "viewer"
    gateway._small_retired_sessions["retired"] = {"owner": "viewer"}
    old.returncode = 1
    gateway._watchdog_tick()
    assert len(calls) == 2 and gateway._generation > generation
    assert gateway._internal_password != password
    assert not gateway._sessions and not gateway._pending_sessions and not gateway._small_retired_sessions
    assert gateway._process is processes[1]


def test_alive_gateway_error_does_not_restart_independent_video_owner(rig):
    gateway, processes, calls, _ = rig
    assert gateway._spawn_locked()
    gateway._source_error = "RTSP source camera currently unavailable"
    gateway._watchdog_tick()
    assert gateway._process is processes[0] and len(calls) == 1


def test_retry_delay_is_capped_and_failed_owner_log_cannot_replace_safe_code(rig):
    gateway, processes, calls, clock = rig
    assert gateway._spawn_locked()
    owner = processes[0]
    owner.stuck = True
    gateway.restart()
    for _ in range(8):
        clock.now = gateway._next_restart_at + .1
        gateway._watchdog_tick()
    assert gateway._next_restart_at - clock.now <= 30
    gateway._record_log_error(owner, "ERR FakeReliabilitySecret", "ERR FakeReliabilitySecret", gateway._source)
    assert gateway._last_error == "GATEWAY_STOP_TIMEOUT" and len(calls) == 1
