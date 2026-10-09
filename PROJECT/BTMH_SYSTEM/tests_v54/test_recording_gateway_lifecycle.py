"""Synthetic process tests: no camera, gateway binary or customer data required."""
from __future__ import annotations

import subprocess
import threading
from types import SimpleNamespace

import pytest

from module_app import recording_runtime_v4 as recording


SOURCE = 'rtsp://qa:upstream-secret@192.0.2.7:554/Streaming/Channels/101'
RELAY = 'rtsp://btmh-internal:relay-token@127.0.0.1:8554/btmhmain'


class PrivatePipe:
    def __init__(self, fail=False):
        self.data = bytearray()
        self.closed = False
        self.fail = fail

    def write(self, chunk):
        if self.fail:
            raise OSError(SOURCE)
        count = min(23, len(chunk))  # Exercise partial private-pipe writes.
        self.data.extend(chunk[:count])
        return count

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, *, write_fail=False, stuck=False):
        self.stdin = PrivatePipe(write_fail)
        self.stdout = self.stderr = None
        self.code = None
        self.terminated = self.killed = False
        self.waits = 0
        self.stuck = stuck

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        if not self.stuck:
            self.code = 0

    def kill(self):
        self.killed = True
        if self.stuck:
            raise OSError('Cannot reap synthetic child')
        self.code = -9

    def wait(self, timeout=None):
        self.waits += 1
        if self.stuck:
            raise subprocess.TimeoutExpired('synthetic-ffmpeg', timeout)
        return self.code


@pytest.fixture
def rig(tmp_path, monkeypatch):
    supervisor = recording.LocalRecorderSupervisorV4()
    supervisor._running = True
    processes, commands = [], []
    selected = {'relay': RELAY}
    monkeypatch.setattr(recording, 'RECORDING_ROOT', tmp_path / 'recordings')
    monkeypatch.setattr(recording, 'MEDIA_GATEWAY', SimpleNamespace(relay_source=lambda _source: selected['relay']))

    def spawn(cmd, **kwargs):
        commands.append((cmd, kwargs))
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(recording.subprocess, 'Popen', spawn)
    row = {'id': 7, 'source': SOURCE, 'camera_type': 'RTSP', 'enabled': True, 'recording_enabled': True}
    yield supervisor, row, processes, commands, selected
    supervisor.stop()


def test_relay_stream_copy_keeps_upstream_identity_and_secrets_private(rig, caplog):
    supervisor, row, processes, commands, _ = rig
    supervisor._start_camera(row, 'ffmpeg')
    cmd, kwargs = commands[0]
    assert cmd[cmd.index('-i') + 1] == 'pipe:0'
    assert cmd[cmd.index('-c:v') + 1] == 'copy'
    assert '-vf' not in cmd
    assert kwargs['stdin'] == subprocess.PIPE
    assert RELAY.encode() in processes[0].stdin.data
    assert SOURCE.encode() not in processes[0].stdin.data
    assert processes[0].stdin.closed
    assert supervisor._sources[7] == SOURCE
    status = supervisor.camera_status(7)
    assert status['active'] and status['input_transport'] == 'NATIVE_GATEWAY_RTSP_RELAY'
    assert status['fallback_reason'] == ''
    public = repr(commands) + repr(status) + caplog.text
    assert 'upstream-secret' not in public and 'relay-token' not in public


def test_unavailable_relay_falls_back_explicitly_without_secret_argv(rig, caplog):
    supervisor, row, processes, commands, selected = rig
    selected['relay'] = ''
    supervisor._start_camera(row, 'ffmpeg')
    assert SOURCE.encode() in processes[0].stdin.data
    status = supervisor.camera_status(7)
    assert status['input_transport'] == 'DIRECT_CAMERA_RTSP'
    assert status['fallback_reason'] == 'NATIVE_GATEWAY_RELAY_UNAVAILABLE_OR_SOURCE_MISMATCH'
    assert status['fallback_reason'] in caplog.text
    assert 'upstream-secret' not in repr(commands) + repr(status) + caplog.text


def test_relay_lookup_error_is_classified_without_credentials(rig, monkeypatch, caplog):
    supervisor, row, _, _, _ = rig

    def fail(_source):
        raise RuntimeError(RELAY)

    monkeypatch.setattr(recording.MEDIA_GATEWAY, 'relay_source', fail)
    supervisor._start_camera(row, 'ffmpeg')
    assert supervisor.camera_status(7)['fallback_reason'] == 'NATIVE_GATEWAY_RELAY_LOOKUP_FAILED'
    assert 'relay-token' not in repr(supervisor.status()) + caplog.text


def test_concurrent_start_requests_own_one_recorder(rig):
    supervisor, row, processes, _, _ = rig
    threads = [threading.Thread(target=supervisor._start_camera, args=(row, 'ffmpeg')) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert len(processes) == 1
    assert supervisor._processes[7] is processes[0]


def test_rotated_relay_token_reaps_previous_reader_before_replacement(rig):
    supervisor, row, processes, _, selected = rig
    supervisor._start_camera(row, 'ffmpeg')
    selected['relay'] = RELAY.replace('relay-token', 'new-token')
    supervisor._start_camera(row, 'ffmpeg')
    assert len(processes) == 2
    assert processes[0].terminated and processes[0].waits > 0
    assert supervisor._processes[7] is processes[1]
    assert supervisor._sources[7] == SOURCE
    assert b'new-token' in processes[1].stdin.data
    assert supervisor.camera_status(7)['restart_count'] == 1


def test_registry_source_edit_replaces_input_without_stale_camera_identity(rig):
    supervisor, row, processes, _, selected = rig
    supervisor._start_camera(row, 'ffmpeg')
    selected['relay'] = ''
    new_source = SOURCE.replace('192.0.2.7', '192.0.2.8')
    supervisor._start_camera({**row, 'source': new_source}, 'ffmpeg')
    assert processes[0].terminated and processes[0].waits > 0
    assert new_source.encode() in processes[1].stdin.data
    assert supervisor._sources[7] == new_source


@pytest.mark.parametrize('change', [{'enabled': False}, {'recording_enabled': False}, None])
def test_disabled_or_deleted_recording_reaps_child(rig, change):
    supervisor, row, processes, _, _ = rig
    supervisor._reconcile([row], 'ffmpeg')
    supervisor._reconcile([{**row, **change}] if change is not None else [], 'ffmpeg')
    assert processes[0].terminated and processes[0].waits > 0
    assert not supervisor._processes
    assert not supervisor.camera_status(7)['active']


def test_stop_racing_spawn_cannot_leave_unowned_process(rig, monkeypatch):
    supervisor, row, processes, _, _ = rig
    entered, release = threading.Event(), threading.Event()

    def delayed_spawn(_cmd, **_kwargs):
        entered.set()
        assert release.wait(2)
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(recording.subprocess, 'Popen', delayed_spawn)
    starter = threading.Thread(target=supervisor._start_camera, args=(row, 'ffmpeg'))
    starter.start()
    assert entered.wait(2)
    stopper = threading.Thread(target=supervisor.stop)
    stopper.start()
    release.set()
    starter.join(timeout=2)
    stopper.join(timeout=2)
    assert not starter.is_alive() and not stopper.is_alive()
    assert not supervisor._processes
    assert processes[0].terminated and processes[0].waits > 0
    supervisor._start_camera(row, 'ffmpeg')
    assert len(processes) == 1


def test_failed_private_manifest_write_reaps_child_and_redacts_error(rig, monkeypatch, caplog):
    supervisor, row, processes, _, _ = rig
    process = FakeProcess(write_fail=True)
    processes.append(process)
    monkeypatch.setattr(recording.subprocess, 'Popen', lambda *_args, **_kwargs: process)
    supervisor._start_camera(row, 'ffmpeg')
    assert process.terminated and process.waits > 0
    assert not supervisor._processes
    assert supervisor.camera_status(7)['last_error'] == 'RECORDER_START_FAILED_OSERROR'
    assert 'upstream-secret' not in repr(supervisor.status()) + caplog.text


def test_unreaped_child_prevents_duplicate_replacement(rig):
    supervisor, row, processes, _, selected = rig
    supervisor._start_camera(row, 'ffmpeg')
    processes[0].stuck = True
    selected['relay'] = ''
    supervisor._start_camera(row, 'ffmpeg')
    assert len(processes) == 1
    assert supervisor._processes[7] is processes[0]
    assert supervisor.camera_status(7)['last_error'] == 'RECORDER_STOP_TIMEOUT'
    processes[0].stuck = False


def test_failed_invalidation_retries_reaping_even_when_input_is_unchanged(rig):
    supervisor, row, processes, _, _ = rig
    supervisor._start_camera(row, 'ffmpeg')
    processes[0].stuck = True
    supervisor.invalidate_camera(7)
    assert supervisor._processes[7] is processes[0]
    assert supervisor.camera_status(7)['last_error'] == 'RECORDER_STOP_TIMEOUT'
    processes[0].stuck = False
    supervisor._start_camera(row, 'ffmpeg')
    assert len(processes) == 2
    assert processes[0].poll() is not None
    assert supervisor._processes[7] is processes[1]
    assert supervisor.camera_status(7)['last_error'] == ''


def test_failed_startup_retries_owned_child_cleanup_before_spawning(rig, monkeypatch):
    supervisor, row, processes, _, _ = rig
    failed = FakeProcess(write_fail=True, stuck=True)
    processes.append(failed)
    monkeypatch.setattr(recording.subprocess, 'Popen', lambda *_args, **_kwargs: failed)
    supervisor._start_camera(row, 'ffmpeg')
    assert supervisor._processes[7] is failed
    assert supervisor.camera_status(7)['last_error'] == 'RECORDER_START_FAILED_OSERROR'
    failed.stuck = False

    def replacement(*_args, **_kwargs):
        assert failed.poll() is not None  # Never overlap the abandoned reader.
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(recording.subprocess, 'Popen', replacement)
    supervisor._start_camera(row, 'ffmpeg')
    assert len(processes) == 2
    assert supervisor._processes[7] is processes[1]
    assert supervisor.camera_status(7)['last_error'] == ''


def test_stop_wakes_and_joins_supervisor_without_spawn_after_stop(rig, monkeypatch):
    supervisor, row, processes, _, _ = rig
    observed = threading.Event()

    def rows():
        observed.set()
        return [row]

    monkeypatch.setattr(supervisor, '_ffmpeg', lambda: 'ffmpeg')
    monkeypatch.setattr(supervisor, '_index_files', lambda: None)
    monkeypatch.setattr(recording, 'list_camera_devices', rows)
    supervisor.start()
    assert observed.wait(2)
    supervisor.stop()
    assert not supervisor._thread.is_alive()
    assert not supervisor._processes
    prior_count = len(processes)
    supervisor._reconcile([row], 'ffmpeg')
    assert len(processes) == prior_count
