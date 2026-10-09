from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import DATA_ROOT
from .db import connection, fetchone, utc_now
from .production_ops import list_camera_devices
from .camera_profiles import normalize_camera_source
from .recording import ensure_recording_schema, RECORDING_ROOT
from .media_gateway_v5410 import MEDIA_GATEWAY
from .rtsp_native_v545 import input_manifest

try:
    import imageio_ffmpeg  # type: ignore
except Exception:  # pragma: no cover
    imageio_ffmpeg = None


SEGMENT_SECONDS = 60
FINALIZE_GRACE_SECONDS = 3.0
LOGGER = logging.getLogger(__name__)


class LocalRecorderSupervisorV4:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stopped = threading.Event()
        self._processes: dict[int, subprocess.Popen] = {}
        # Private identities are never returned by status(). A gateway restart
        # rotates its relay credential, so readers of an old source cannot
        # reconnect to a newly selected camera under the previous camera id.
        self._sources: dict[int, str] = {}
        self._inputs: dict[int, str] = {}
        self._input_transport: dict[int, str] = {}
        self._fallback_reason: dict[int, str] = {}
        self._last_error: dict[int, str] = {}
        self._restart_count: dict[int, int] = {}
        self._started_at: dict[int, float] = {}
        self._last_scan = 0.0

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._running = True
            self._stopped.clear()
            self._thread = threading.Thread(target=self._run, name='btmh-recorder-v4', daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._stopped.set()
            thread = self._thread
            for cid in list(self._processes):
                self._stop_camera_locked(cid)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    @staticmethod
    def _close_process(proc: subprocess.Popen) -> bool:
        """Reap the owned child before a replacement is allowed to open RTSP."""
        reaped = False
        try:
            if getattr(proc, 'poll', lambda: None)() is None:
                proc.terminate()
            proc.wait(timeout=1.5)
            reaped = True
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=1.5)
                reaped = True
            except Exception:
                pass
        for pipe in (getattr(proc, 'stdin', None), getattr(proc, 'stdout', None), getattr(proc, 'stderr', None)):
            if pipe is not None:
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
        return reaped

    def _stop_camera_locked(self, camera_id: int) -> bool:
        proc = self._processes.get(camera_id)
        if proc is not None and not self._close_process(proc):
            self._last_error[camera_id] = 'RECORDER_STOP_TIMEOUT'
            return False  # Keep ownership; never spawn beside an unreaped child.
        self._processes.pop(camera_id, None)
        self._sources.pop(camera_id, None)
        self._inputs.pop(camera_id, None)
        self._started_at.pop(camera_id, None)
        return True

    def _ffmpeg(self) -> str:
        if imageio_ffmpeg is None:
            return ''
        try:
            return str(imageio_ffmpeg.get_ffmpeg_exe() or '')
        except Exception:
            return ''

    def invalidate_camera(self, camera_id: int) -> None:
        """Stop one recorder so the supervisor reopens it from the persisted registry.

        Used after an operator edits a camera connection. This prevents a recorder
        process from continuing to use the pre-edit RTSP URI indefinitely.
        """
        cid = int(camera_id)
        with self._lock:
            self._stop_camera_locked(cid)

    def camera_status(self, camera_id: int) -> dict:
        cid = int(camera_id)
        with self._lock:
            proc = self._processes.get(cid)
            code = proc.poll() if proc is not None else None
            active = bool(proc is not None and code is None)
            err = str(self._last_error.get(cid) or '')
            restarts = int(self._restart_count.get(cid) or 0)
            started = float(self._started_at.get(cid) or 0.0)
            transport = self._input_transport.get(cid, '')
            fallback = self._fallback_reason.get(cid, '')
        return {
            'active': active,
            'exit_code': code,
            'last_error': err,
            'restart_count': restarts,
            'uptime_sec': round(max(0.0, time.time() - started), 1) if active and started else 0.0,
            'input_transport': transport,
            'fallback_reason': fallback,
        }

    def status(self) -> dict:
        exe = self._ffmpeg()
        with self._lock:
            ids = set(self._processes) | set(self._last_error) | set(self._restart_count)
        per_camera = {f'CAM{cid:02d}': self.camera_status(cid) for cid in sorted(ids)}
        running = sum(1 for item in per_camera.values() if item.get('active'))
        return {
            'ready': bool(exe),
            'ffmpeg': exe,
            'active_recorders': running,
            'root': str(RECORDING_ROOT),
            'segment_seconds': SEGMENT_SECONDS,
            'cameras': per_camera,
        }

    def _start_camera(self, row: dict, exe: str) -> None:
        cid = int(row.get('id') or 0)
        if cid <= 0:
            return
        source = normalize_camera_source(str(row.get('source') or ''))
        ctype = str(row.get('camera_type') or '').upper()
        if source in {'0', 'laptop'} or ctype in {'USB', 'WEBCAM', 'LAPTOP'}:
            with self._lock:
                self._stop_camera_locked(cid)
            return
        if not source.lower().startswith('rtsp://'):
            with self._lock:
                if not self._stop_camera_locked(cid):
                    return
                self._last_error[cid] = 'UNSUPPORTED_RECORDING_SOURCE'
            return
        # Serialize selection, spawn and stop together. A source edit or shutdown
        # cannot race a Popen outside the lock and leave an unowned child running.
        with self._lock:
            if not self._running or self._stopped.is_set():
                return
            try:
                relay = MEDIA_GATEWAY.relay_source(source)
                fallback = '' if relay else 'NATIVE_GATEWAY_RELAY_UNAVAILABLE_OR_SOURCE_MISMATCH'
            except Exception:
                relay = ''
                fallback = 'NATIVE_GATEWAY_RELAY_LOOKUP_FAILED'
            selected = relay or source
            transport = 'NATIVE_GATEWAY_RTSP_RELAY' if relay else 'DIRECT_CAMERA_RTSP'
            old = self._processes.get(cid)
            if old is not None:
                code = old.poll()
                # A prior stop/start failure retained child ownership. Retry
                # reaping it even when its source and relay token are unchanged.
                if (code is None and self._sources.get(cid) == source and self._inputs.get(cid) == selected
                        and not self._last_error.get(cid)):
                    return
                if not self._stop_camera_locked(cid):
                    return
                self._restart_count[cid] = int(self._restart_count.get(cid) or 0) + 1
            self._input_transport[cid] = transport
            self._fallback_reason[cid] = fallback
            if fallback:
                LOGGER.warning('CAM%02d recording transport=%s fallback_reason=%s', cid, transport, fallback)
            proc = None
            try:
                manifest = input_manifest(selected, 6000)
                folder = RECORDING_ROOT / f'CAM{cid:02d}'
                folder.mkdir(parents=True, exist_ok=True)
                pattern = str(folder / '%Y%m%d_%H%M%S.mp4')
                cmd = [
                    exe, '-hide_banner', '-nostdin', '-loglevel', 'error',
                    '-protocol_whitelist', 'pipe,rtsp,tcp,rtp', '-f', 'concat', '-safe', '0', '-i', 'pipe:0',
                    '-map', '0:v:0', '-an', '-c:v', 'copy',
                    '-f', 'segment', '-segment_time', str(SEGMENT_SECONDS), '-reset_timestamps', '1',
                    '-strftime', '1', '-segment_format', 'mp4', '-movflags', '+faststart', pattern,
                ]
                flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, bufsize=0, creationflags=flags)
                # Relay authentication and upstream credentials are private stdin
                # data, never command arguments, files, logs or public status.
                view = memoryview(manifest)
                while view:
                    count = proc.stdin.write(view)
                    if not count:
                        raise BrokenPipeError
                    view = view[count:]
                proc.stdin.close()
                self._processes[cid] = proc
                self._sources[cid] = source
                self._inputs[cid] = selected
                self._started_at[cid] = time.time()
                self._last_error[cid] = ''
            except Exception as exc:
                if proc is not None:
                    if not self._close_process(proc):
                        self._processes[cid] = proc
                        self._sources[cid] = source
                        self._inputs[cid] = selected
                # Exceptions can contain filenames, argv or a credential-bearing
                # URI. Return only a controlled category.
                self._last_error[cid] = 'RECORDER_START_FAILED_' + type(exc).__name__.upper()

    def _reconcile(self, rows: list[dict], exe: str) -> None:
        eligible = {int(row.get('id') or 0): row for row in rows
                    if bool(row.get('enabled', True)) and bool(row.get('recording_enabled', True))}
        with self._lock:
            if not self._running or self._stopped.is_set():
                return
            for cid in list(self._processes):
                if cid not in eligible:
                    self._stop_camera_locked(cid)
            for row in eligible.values():
                self._start_camera(row, exe)

    def _index_files(self) -> None:
        ensure_recording_schema()
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        now_ts = time.time()
        for folder in RECORDING_ROOT.glob('CAM*'):
            if not folder.is_dir():
                continue
            try:
                cid = int(folder.name.replace('CAM', ''))
            except Exception:
                continue
            for path in folder.glob('*.mp4'):
                try:
                    stat = path.stat()
                except Exception:
                    continue
                # The current FFmpeg segment is not browser-playable until its MP4
                # trailer/moov metadata has been finalized. Only index files that
                # have stopped changing for a few seconds.
                if now_ts - float(stat.st_mtime) < FINALIZE_GRACE_SECONDS:
                    continue
                if int(stat.st_size) < 1024:
                    continue
                try:
                    local_stamp = datetime.strptime(path.stem, '%Y%m%d_%H%M%S').replace(tzinfo=local_tz)
                    stamp = local_stamp.astimezone(timezone.utc)
                except Exception:
                    stamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                rel = str(path.relative_to(Path(DATA_ROOT)))
                segment_id = 'SEG-' + hashlib.sha1(rel.encode('utf-8')).hexdigest()[:20]
                if fetchone('SELECT segment_id FROM recording_segments WHERE segment_id=?', (segment_id,)):
                    continue
                start_at = stamp.isoformat()
                end_at = (stamp + timedelta(seconds=SEGMENT_SECONDS)).isoformat()
                now = utc_now()
                with connection() as conn:
                    conn.execute(
                        '''INSERT INTO recording_segments(segment_id,camera_source,start_at,end_at,storage_type,media_uri,size_bytes,protected,detail_json,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                        (segment_id, f'CAM{cid:02d}', start_at, end_at, 'LOCAL_FFMPEG', rel, int(stat.st_size), 0, '{}', now, now),
                    )

    def _run(self) -> None:
        while not self._stopped.is_set():
            exe = self._ffmpeg()
            if exe:
                try:
                    rows = list_camera_devices()
                except Exception:
                    rows = None  # A temporary DB read failure is not a camera deletion.
                if rows is not None:
                    self._reconcile(rows, exe)
                if time.time() - self._last_scan > 8.0:
                    self._last_scan = time.time()
                    try:
                        self._index_files()
                    except Exception:
                        pass
            self._stopped.wait(2.0)


RECORDER_V4 = LocalRecorderSupervisorV4()
