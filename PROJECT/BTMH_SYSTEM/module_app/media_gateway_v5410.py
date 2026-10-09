from __future__ import annotations

import os
import base64
import json
import re
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

from .config import CONFIG_DIR, DATA_ROOT, LOG_DIR
from .camera_profiles import hikvision_ai_substream, normalize_camera_source
from .mediamtx_runtime import VERSION as GATEWAY_VERSION, invalidate_verification_cache, resolve_mediamtx


GATEWAY_PATH = "btmhmain"
GATEWAY_SMALL_PATH = "btmhsmall"
GATEWAY_QUALITY_PATHS = {"main": GATEWAY_PATH, "small": GATEWAY_SMALL_PATH}
SMALL_FALLBACK_REASONS = frozenset({
    "SMALL_NOT_VALIDATED", "SMALL_UNAVAILABLE", "SMALL_DISABLED", "SMALL_SOURCE_REJECTED",
    "SMALL_GATEWAY_UNAVAILABLE", "SMALL_CONFIG_FAILED", "SMALL_NEGOTIATION_FAILED",
    "SUBSTREAM_NOT_READY", "SUBSTREAM_CONNECTING", "SOURCE_NOT_REGISTERED", "SUBSTREAM_STALE",
    "SUBSTREAM_DISABLED", "NO_KNOWN_SUBSTREAM", "CAMERA_NOT_ACTIVE", "GATEWAY_SOURCE_CHANGED", "ADAPTIVE_DISABLED",
})
# Signalling/control are always private. LAN clients use the authenticated app
# proxy; only the ICE media listener is allowed to bind network interfaces.
GATEWAY_HTTP_HOST = "127.0.0.1"
GATEWAY_HTTP_PORT = max(1024, min(65535, int(os.getenv("BTMH_MEDIA_GATEWAY_HTTP_PORT", "8889"))))
GATEWAY_ICE_PORT = max(1024, min(65535, int(os.getenv("BTMH_MEDIA_GATEWAY_ICE_PORT", "8189"))))
GATEWAY_API_PORT = max(1024, min(65535, int(os.getenv("BTMH_MEDIA_GATEWAY_API_PORT", "9997"))))
GATEWAY_METRICS_PORT = max(1024, min(65535, int(os.getenv("BTMH_MEDIA_GATEWAY_METRICS_PORT", "9998"))))
GATEWAY_ENABLED = os.getenv("BTMH_MEDIA_GATEWAY_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
GATEWAY_RTSP_PORT = max(1024, min(65535, int(os.getenv("BTMH_MEDIA_GATEWAY_RTSP_PORT", "8554"))))
WHEP_MAX_BODY = 65536
WHEP_MAX_SESSIONS = 32
WHEP_MAX_OWNER_SESSIONS = 8


class NativeGatewayError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NativeMediaGateway:
    """Own the local MediaMTX process used only for browser-native live video.

    Camera credentials are passed through the child process environment and are
    never written to the MediaMTX YAML file, browser storage or public API.
    FaceID/PAD keep their existing independent pipeline in V5.4.10.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._source = ""
        self._small_source = ""
        self._small_configured = False
        self._small_generation = 0
        self._small_fallback_reason = "SMALL_NOT_VALIDATED"
        self._small_update_lock = threading.Lock()
        self._small_applied_source = ""
        self._small_retired_sessions: dict[str, dict[str, Any]] = {}
        self._source_label = ""
        self._desired = False
        self._shutting_down = False
        self._restart_count = 0
        self._started_at = 0.0
        self._last_error = ""
        self._watchdog: threading.Thread | None = None
        self._log_thread: threading.Thread | None = None
        self._internal_user = "btmh-internal"
        self._internal_password = secrets.token_urlsafe(32)
        self._generation = 0
        self._sessions: dict[str, dict[str, Any]] = {}
        self._pending_sessions: dict[str, str] = {}
        self._next_restart_at = 0.0
        self._failure_count = 0
        self._retire_failed = False
        self._source_error = ""
        self._diagnostics: dict[str, Any] = {}
        self._diagnostics_at = 0.0
        self._http = build_opener(ProxyHandler({}), _NoRedirect())
        self._runtime_dir = DATA_ROOT / "runtime" / "mediamtx"
        self._binary_reason = ""
        self._config_dir = CONFIG_DIR / "media_gateway"
        self._config_path = self._config_dir / "mediamtx_v5410.yml"
        self._log_path = LOG_DIR / "mediamtx-gateway.log"

    @staticmethod
    def _is_rtsp(source: str) -> bool:
        value = str(source or "").strip().lower()
        return value.startswith(("rtsp://", "rtsps://"))

    def binary_path(self) -> Path:
        result = resolve_mediamtx(self._runtime_dir.parent.parent)
        self._binary_reason = result.reason
        # An existing but unsupported runtime must not reach Popen either.
        return result.binary or self._runtime_dir / "__mediamtx_unavailable__"

    def _write_config(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        # Secrets intentionally do not appear here. MTX_PATHS_BTMHMAIN_SOURCE is
        # injected only into the child environment by _spawn_locked().
        lan = self._lan_mode()
        ice_host = "0.0.0.0" if lan else "127.0.0.1"
        hosts = self._additional_hosts()
        text = f"""# BTMH 5.4.10 native media gateway (secret-free configuration)
logLevel: info
logDestinations: [stdout]
authMethod: internal
authInternalUsers: []
api: true
apiAddress: {GATEWAY_HTTP_HOST}:{GATEWAY_API_PORT}
apiAllowOrigins: []
metrics: true
metricsAddress: {GATEWAY_HTTP_HOST}:{GATEWAY_METRICS_PORT}
metricsAllowOrigins: []
pprof: false
playback: false
rtsp: true
rtspAddress: {GATEWAY_HTTP_HOST}:{GATEWAY_RTSP_PORT}
rtspTransports: [tcp]
rtmp: false
hls: false
srt: false
moq: false
webrtc: true
webrtcAddress: {GATEWAY_HTTP_HOST}:{GATEWAY_HTTP_PORT}
webrtcEncryption: false
webrtcAllowOrigins: []
webrtcLocalUDPAddress: {ice_host}:{GATEWAY_ICE_PORT}
webrtcLocalTCPAddress: {ice_host}:{GATEWAY_ICE_PORT}
webrtcIPsFromInterfaces: {str(lan).lower()}
webrtcAdditionalHosts: {json.dumps(hosts)}
webrtcICEServers2: []
writeQueueSize: 128
paths:
  {GATEWAY_PATH}:
    source: publisher
    sourceOnDemand: true
    sourceOnDemandStartTimeout: 8s
    sourceOnDemandCloseAfter: 5s
    rtspTransport: tcp
  {GATEWAY_SMALL_PATH}:
    source: publisher
    sourceOnDemand: true
    sourceOnDemandStartTimeout: 8s
    sourceOnDemandCloseAfter: 5s
    rtspTransport: tcp
"""
        current = self._config_path.read_text(encoding="utf-8", errors="ignore") if self._config_path.exists() else ""
        if current != text:
            self._config_path.write_text(text, encoding="utf-8")

    @staticmethod
    def _lan_mode() -> bool:
        return (os.getenv("MODULE_HOST", "127.0.0.1").strip() in {"0.0.0.0", "::"}
                or os.getenv("BTMH_NETWORK_MODE", "local").strip().lower() == "lan")

    @staticmethod
    def _additional_hosts() -> list[str]:
        hosts = ["127.0.0.1"]
        for value in os.getenv("BTMH_MEDIA_GATEWAY_ICE_HOSTS", "").split(","):
            value = value.strip()
            # Hostnames/IPs only: never accept URLs or YAML fragments.
            if value and re.fullmatch(r"[a-zA-Z0-9_.:\-]+", value) and value not in hosts:
                hosts.append(value)
        return hosts[:16]

    def _child_environment(self, source: str) -> dict[str, str]:
        # v1.21.1 uses indexed variables for arrays of structures, not JSON.
        env = {key: value for key, value in os.environ.items() if not key.startswith("MTX_")}
        env["MTX_PATHS_BTMHMAIN_SOURCE"] = source
        env["MTX_PATHS_BTMHMAIN_RTSPTRANSPORT"] = "tcp"
        if self._small_source:
            env["MTX_PATHS_BTMHSMALL_SOURCE"] = self._small_source
            env["MTX_PATHS_BTMHSMALL_RTSPTRANSPORT"] = "tcp"
        env["MTX_AUTHINTERNALUSERS_0_USER"] = self._internal_user
        env["MTX_AUTHINTERNALUSERS_0_PASS"] = self._internal_password
        env["MTX_AUTHINTERNALUSERS_0_IPS"] = "127.0.0.1,::1"
        for index, action in enumerate(("read", "api", "metrics")):
            env[f"MTX_AUTHINTERNALUSERS_0_PERMISSIONS_{index}_ACTION"] = action
            env[f"MTX_AUTHINTERNALUSERS_0_PERMISSIONS_{index}_PATH"] = GATEWAY_PATH if action == "read" else ""
        env["MTX_AUTHINTERNALUSERS_0_PERMISSIONS_3_ACTION"] = "read"
        env["MTX_AUTHINTERNALUSERS_0_PERMISSIONS_3_PATH"] = GATEWAY_SMALL_PATH
        return env

    @staticmethod
    def _yaml_quote(value: str) -> str:
        # JSON-style quoting is valid YAML and safely preserves Windows paths.
        import json
        return json.dumps(str(value), ensure_ascii=False)


    @staticmethod
    def _redact_gateway_log_line(line: str, source: str) -> str:
        """Keep gateway diagnostics useful without ever persisting RTSP userinfo."""
        clean = str(line or "")
        if source:
            clean = clean.replace(source, "[RTSP_SOURCE_REDACTED]")
        # Also redact any RTSP(S) userinfo MediaMTX might include in an error.
        clean = re.sub(r"(?i)(rtsps?://)[^\s/]+@", r"\1***@", clean)
        return clean

    def _safe_message(self, message: str, source: str = "", password: str = "") -> str:
        clean = str(message or "")
        # A child/negotiation can finish after auxiliary revocation. Its captured
        # main source also identifies the old derived URL, including query tokens.
        for value in (source or self._source, self._small_source,
                      hikvision_ai_substream(source or self._source) or ""):
            if value:
                clean = clean.replace(value, "[RTSP_SOURCE_REDACTED]")
        clean = self._redact_gateway_log_line(clean, "")
        for value in (password, self._internal_password):
            if value:
                clean = clean.replace(value, "[INTERNAL_SECRET_REDACTED]")
                token = base64.b64encode(f"{self._internal_user}:{value}".encode()).decode()
                clean = clean.replace(token, "[INTERNAL_AUTH_REDACTED]")
        clean = re.sub(r"(?i)(/whep/)[0-9a-f-]{36}", r"\1[SESSION_REDACTED]", clean)
        return clean.strip()[:1000]

    def _record_log_error(self, proc, safe: str, raw: str, source: str) -> None:
        if self._process is not proc or self._retire_failed:
            return
        small = self._small_source or hikvision_ai_substream(source) or ""
        is_small = bool(re.search(rf"\[(?:path\s+)?{GATEWAY_SMALL_PATH}\]", raw)
                        or small and small in raw)
        if is_small:
            self._small_configured = False
            self._small_fallback_reason = "SMALL_UNAVAILABLE"
            return
        self._last_error = safe
        if "RTSP source" in safe:
            self._source_error = safe

    def _start_log_pump(self, proc: subprocess.Popen, source: str) -> None:
        pipe = proc.stdout
        password = self._internal_password
        if pipe is None:
            return

        def pump() -> None:
            try:
                with open(self._log_path, "a", encoding="utf-8", errors="replace") as log:
                    while True:
                        raw = pipe.readline()
                        if not raw:
                            break
                        if isinstance(raw, bytes):
                            line = raw.decode("utf-8", errors="replace")
                        else:
                            line = str(raw)
                        safe = self._safe_message(line, source, password)
                        if re.search(r"\b(ERR|ERROR)\b", safe, re.IGNORECASE):
                            # Do not wait for the startup lock: a failed child
                            # must deliver its precise error before poll() exits.
                            self._record_log_error(proc, safe, line, source)
                        log.write(safe + "\n")
                        log.flush()
            except Exception:
                pass
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        self._log_thread = threading.Thread(target=pump, name="btmh-mediamtx-log", daemon=True)
        self._log_thread.start()

    @staticmethod
    def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            return False

    def _spawn_locked(self) -> bool:
        source = normalize_camera_source(self._source)
        if not self._desired or not self._is_rtsp(source):
            return False
        # A child can be alive before it opens listeners. Port checks cannot
        # prove retirement, and an unreaped owner must never be replaced.
        if self._process is not None:
            if self._process.poll() is None:
                return False if self._retire_failed else self._ready_locked()
            if not self._stop_locked():
                return False
        invalidate_verification_cache()
        binary = self.binary_path()
        if self._binary_reason or not binary.is_file():
            self._last_error = self._binary_reason or "MEDIAMTX_NOT_INSTALLED"
            self._schedule_retry_locked()
            return False
        if any(self._port_open(GATEWAY_HTTP_HOST, port, 0.05)
               for port in (GATEWAY_HTTP_PORT, GATEWAY_API_PORT, GATEWAY_RTSP_PORT)):
            self._last_error = "MEDIA_GATEWAY_PORT_BUSY: cổng gateway đã được tiến trình khác sử dụng"
            self._schedule_retry_locked()
            return False
        # A previous recorder must never reconnect to a different camera under
        # its old source label after handover. Rotate auth on every child start.
        self._internal_password = secrets.token_urlsafe(32)
        self._generation += 1
        self._small_generation += 1
        self._small_configured = False
        self._small_applied_source = ""
        self._small_retired_sessions.clear()
        self._sessions.clear()
        self._pending_sessions.clear()
        self._diagnostics = {}
        self._diagnostics_at = 0.0
        self._source_error = ""
        # Reset before starting the pump: a child that fails immediately may
        # already have delivered its precise startup error when Popen returns.
        self._last_error = ""
        self._write_config()
        env = self._child_environment(source)
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.Popen(
                [str(binary), str(self._config_path)],
                cwd=str(self._runtime_dir if self._runtime_dir.exists() else binary.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            self._process = proc
            self._start_log_pump(proc, source)
            self._started_at = time.time()
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    if self._log_thread:
                        self._log_thread.join(timeout=0.2)
                    self._last_error = self._last_error or f"MediaMTX thoát sớm với mã {proc.returncode}; xem mediamtx-gateway.log"
                    self._process = None
                    self._schedule_retry_locked()
                    return False
                if (self._port_open(GATEWAY_HTTP_HOST, GATEWAY_HTTP_PORT)
                        and self._port_open(GATEWAY_HTTP_HOST, GATEWAY_API_PORT)):
                    self._failure_count = 0
                    self._next_restart_at = 0.0
                    self._small_configured = bool(self._small_source)
                    self._small_applied_source = self._small_source
                    return True
                time.sleep(0.08)
            self._last_error = "MEDIA_GATEWAY_START_TIMEOUT: listener chưa sẵn sàng sau 4 giây"
            self._stop_locked()
            self._schedule_retry_locked()
            return False
        except Exception as exc:
            message = self._safe_message(f"{type(exc).__name__}: {exc}")
            if self._process is None or self._stop_locked():
                self._last_error = message
                self._schedule_retry_locked()
            return False

    def _schedule_retry_locked(self) -> None:
        self._failure_count += 1
        self._next_restart_at = time.monotonic() + min(30.0, 1.5 * 2 ** min(self._failure_count - 1, 5))

    def _stop_locked(self) -> bool:
        proc = self._process
        self._generation += 1
        self._small_generation += 1
        self._small_configured = False
        self._small_applied_source = ""
        self._small_retired_sessions.clear()
        self._sessions.clear()
        self._pending_sessions.clear()
        self._diagnostics = {}
        self._diagnostics_at = 0.0
        if proc is None:
            self._retire_failed = False
            return True
        reaped = False
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=3.0)
            reaped = proc.poll() is not None
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=1.5)
                reaped = proc.poll() is not None
            except Exception:
                pass
        if not reaped:
            # Retain the exact owner for bounded watchdog/explicit-stop retries.
            self._retire_failed = True
            self._last_error = "GATEWAY_STOP_TIMEOUT"
            self._schedule_retry_locked()
            return False
        if self._process is proc:
            self._process = None
        self._retire_failed = False
        return True

    def _ensure_watchdog_locked(self) -> None:
        if self._watchdog and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(target=self._watchdog_loop, name="btmh-media-gateway-watchdog", daemon=True)
        self._watchdog.start()

    def _watchdog_loop(self) -> None:
        while True:
            time.sleep(1.5)
            if not self._watchdog_tick():
                return

    def _watchdog_tick(self) -> bool:
        """One bounded recovery pass; no replacement until the old child exits."""
        cleanup_small = False
        with self._lock:
            if self._retire_failed:
                if time.monotonic() < self._next_restart_at:
                    return True
                if not self._stop_locked():
                    return True
            if self._shutting_down:
                return False
            if not self._desired:
                return True
            proc = self._process
            if proc is not None and proc.poll() is None:
                self._refresh_diagnostics_locked()
                cleanup_small = bool(self._small_retired_sessions)
            else:
                if proc is not None and not self._stop_locked():
                    return True
                if time.monotonic() < self._next_restart_at:
                    return True
                self._restart_count += 1
                self._spawn_locked()
        if cleanup_small and self._small_update_lock.acquire(blocking=False):
            try:
                self._cleanup_retired_small_sessions()
            finally:
                self._small_update_lock.release()
        return True

    def _validated_small_source(self, source: str | None) -> str:
        clean = normalize_camera_source(str(source or ""))
        derived = hikvision_ai_substream(self._source)
        return clean if clean and derived and clean == normalize_camera_source(derived) else ""

    @staticmethod
    def _small_reason(value: str) -> str:
        return value if value in SMALL_FALLBACK_REASONS else "SMALL_NOT_VALIDATED"

    def _small_status_locked(self) -> dict[str, Any]:
        available = bool(self._small_source and self._small_configured and self._ready_locked())
        return {"small_available": available, "small_path": GATEWAY_SMALL_PATH,
                "small_fallback_reason": "" if available else (self._small_fallback_reason or "SMALL_GATEWAY_UNAVAILABLE")}

    def sync_small_source(self, small_source: str = "", *, fallback_reason: str = "SMALL_NOT_VALIDATED") -> dict[str, Any]:
        """Configure only the validated auxiliary path through private memory API.

        Caller supplies current registry/decoded-frame proof. This method never
        switches/restarts main media or writes the credentialed URL to YAML/argv.
        """
        with self._lock:
            requested = normalize_camera_source(str(small_source or ""))
            clean = self._validated_small_source(requested)
            reason = "SMALL_SOURCE_REJECTED" if requested and not clean else self._small_reason(fallback_reason)
            if (clean == self._small_source and (not clean or self._small_configured)
                    and self._small_applied_source == clean and not self._small_retired_sessions):
                self._small_fallback_reason = "" if clean else reason
                return self._small_status_locked()
            if clean != self._small_source:
                self._small_generation += 1
                self._small_configured = False
            self._small_source = clean
            if not self._small_configured:
                self._small_fallback_reason = reason if not clean else "SMALL_GATEWAY_UNAVAILABLE"
                # Revoke immediately, retaining failed cleanup references within
                # the same owner/global quota instead of silently losing readers.
                for sid, session in list(self._sessions.items()):
                    if session.get("path") == GATEWAY_SMALL_PATH:
                        self._small_retired_sessions[sid] = self._sessions.pop(sid)
            if not self._ready_locked():
                return self._small_status_locked()
            if not self._small_update_lock.acquire(blocking=False):
                return self._small_status_locked()
            generation, small_generation = self._generation, self._small_generation
            password = self._internal_password
            patch_needed = self._small_applied_source != clean or bool(clean and not self._small_configured)
        # Auxiliary I/O never holds the main gateway lock. At most two short
        # cleanup attempts plus one PATCH keep each capability refresh bounded.
        try:
            self._cleanup_retired_small_sessions()
            with self._lock:
                current = generation == self._generation and small_generation == self._small_generation
            if patch_needed and current:
                body = json.dumps({"source": clean or "publisher", "sourceOnDemand": True,
                                   "rtspTransport": "tcp"}).encode("utf-8")
                try:
                    status, _, _ = self._http_request("PATCH",
                        f"http://{GATEWAY_HTTP_HOST}:{GATEWAY_API_PORT}/v3/config/paths/patch/{GATEWAY_SMALL_PATH}",
                        body, timeout=1.0, password=password, content_type="application/json")
                    ok = status in {200, 204}
                except NativeGatewayError:
                    ok = False
                with self._lock:
                    if generation == self._generation:
                        if ok:
                            self._small_applied_source = clean
                        if small_generation == self._small_generation:
                            self._small_configured = bool(ok and clean)
                            self._small_fallback_reason = ("" if clean else reason) if ok else "SMALL_CONFIG_FAILED"
        finally:
            self._small_update_lock.release()
        with self._lock:
            return self._small_status_locked()

    def _cleanup_retired_small_sessions(self) -> None:
        with self._lock:
            batch = list(self._small_retired_sessions.items())[:2]
        for sid, session in batch:
            try:
                status, _, _ = self._http_request("DELETE", session["url"], timeout=.25, password=session["password"])
            except NativeGatewayError:
                continue
            if status in {200, 204, 404}:
                with self._lock:
                    if self._small_retired_sessions.get(sid) is session:
                        self._small_retired_sessions.pop(sid, None)

    def start(self, source: str, source_label: str = "", *, small_source: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._shutting_down = False
            self._source = normalize_camera_source(str(source or ""))
            self._small_source = self._validated_small_source(small_source)
            self._small_fallback_reason = "" if self._small_source else "SMALL_NOT_VALIDATED"
            self._source_label = str(source_label or "").strip()
            self._desired = bool(GATEWAY_ENABLED and self._is_rtsp(self._source))
            self._failure_count = 0
            self._next_restart_at = 0.0
            self._stop_locked()
            ok = self._spawn_locked() if self._desired else False
            self._ensure_watchdog_locked()
            return self.status(_already_locked=True) | {"started": bool(ok)}

    def sync_source(self, source: str, source_label: str = "", *, small_source: str | None = None) -> dict[str, Any]:
        clean = normalize_camera_source(str(source or ""))
        label = str(source_label or "").strip()
        with self._lock:
            desired = bool(GATEWAY_ENABLED and self._is_rtsp(clean))
            proc_alive = self._process is not None and self._process.poll() is None
            if clean == self._source and label == self._source_label and desired == self._desired and (proc_alive or not desired):
                if small_source is None:
                    return self.status(_already_locked=True)
            else:
                self._source = clean
                self._small_source = self._validated_small_source(small_source)
                self._small_fallback_reason = "" if self._small_source else "SMALL_NOT_VALIDATED"
                self._source_label = label
                self._desired = desired
                self._failure_count = 0
                self._next_restart_at = 0.0
                self._stop_locked()
                self._next_restart_at = 0.0
                ok = self._spawn_locked() if desired else False
                self._ensure_watchdog_locked()
                return self.status(_already_locked=True) | {"started": bool(ok)}
        self.sync_small_source(small_source or "")
        return self.status()

    def restart(self) -> dict[str, Any]:
        with self._lock:
            self._stop_locked()
            ok = self._spawn_locked() if self._desired else False
            if self._desired:
                self._restart_count += 1
            return self.status(_already_locked=True) | {"started": bool(ok)}

    def stop(self) -> None:
        with self._lock:
            self._desired = False
            self._small_source = ""
            self._small_fallback_reason = "SMALL_NOT_VALIDATED"
            self._stop_locked()

    def shutdown(self) -> None:
        with self._lock:
            self._shutting_down = True
            self._desired = False
            self._small_source = ""
            self._small_fallback_reason = "SMALL_NOT_VALIDATED"
            self._stop_locked()

    def _http_request(self, method: str, url: str, body: bytes | None = None,
                      timeout: float = 0.4, password: str = "",
                      content_type: str = "application/sdp") -> tuple[int, dict[str, str], bytes]:
        auth = base64.b64encode(f"{self._internal_user}:{password or self._internal_password}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
        if body is not None:
            headers.update({"Content-Type": content_type, "Accept": content_type})
        request = Request(url, data=body, headers=headers, method=method)
        try:
            try:
                response = self._http.open(request, timeout=timeout)
            except HTTPError as exc:
                response = exc
            with response:
                payload = response.read(WHEP_MAX_BODY + 1)
                if len(payload) > WHEP_MAX_BODY:
                    raise NativeGatewayError(502, "GATEWAY_RESPONSE_TOO_LARGE", "MediaMTX trả dữ liệu vượt giới hạn")
                return int(response.code), dict(response.headers.items()), payload
        except NativeGatewayError:
            raise
        except (OSError, URLError, TimeoutError) as exc:
            message = self._safe_message(f"MEDIA_GATEWAY_UNREACHABLE: {type(exc).__name__}: {exc}", password=password)
            raise NativeGatewayError(503, "GATEWAY_UNREACHABLE", message) from None

    @staticmethod
    def _header(headers: dict[str, str], name: str) -> str:
        return next((value for key, value in headers.items() if key.lower() == name.lower()), "")

    def _upstream_error(self, status: int, payload: bytes, password: str = "", source: str = "",
                        path: str = GATEWAY_PATH) -> NativeGatewayError:
        try:
            detail = json.loads(payload).get("error") or ""
        except (ValueError, AttributeError):
            detail = payload.decode("utf-8", errors="replace")
        message = self._safe_message(f"MediaMTX WHEP HTTP {status}: {detail}", source=source, password=password)
        with self._lock:
            if path == GATEWAY_SMALL_PATH:
                self._small_fallback_reason = "SMALL_NEGOTIATION_FAILED"
            else:
                self._last_error = message
        return NativeGatewayError(503 if status >= 500 else 502, "GATEWAY_WHEP_REJECTED", message)

    def _validate_session_location(self, value: str, path: str = GATEWAY_PATH) -> str:
        if path not in GATEWAY_QUALITY_PATHS.values():
            raise NativeGatewayError(400, "GATEWAY_INVALID_QUALITY", "Invalid native video quality")
        base = f"http://{GATEWAY_HTTP_HOST}:{GATEWAY_HTTP_PORT}/{path}/whep"
        url = urljoin(base, value)
        try:
            parts = urlsplit(url)
            prefix = f"/{path}/whep/"
            suffix = parts.path[len(prefix):] if parts.path.startswith(prefix) else ""
            valid_id = str(UUID(suffix)) == suffix.lower()
            if (parts.scheme == "http" and parts.hostname == GATEWAY_HTTP_HOST
                    and parts.port == GATEWAY_HTTP_PORT and not parts.username and not parts.password
                    and not parts.query and not parts.fragment and valid_id):
                return url
        except (ValueError, TypeError):
            pass
        raise NativeGatewayError(502, "GATEWAY_INVALID_LOCATION", "MediaMTX trả session Location không hợp lệ")

    def create_whep_session(self, sdp: str, owner: str, *, expected_source: str | None = None,
                            quality: str = "main") -> dict[str, str]:
        if quality not in GATEWAY_QUALITY_PATHS:
            raise NativeGatewayError(400, "GATEWAY_INVALID_QUALITY", "Invalid native video quality")
        with self._lock:
            available = bool(self._small_source and self._small_configured)
            selected = "small" if quality == "small" and available else "main"
            reason = (self._small_fallback_reason or "SMALL_UNAVAILABLE") if quality != selected else ""
            generation = self._generation
            expected_source = self._source if expected_source is None else expected_source
        try:
            result = self._create_whep_session(sdp, owner, expected_source=expected_source,
                                               quality=selected, expected_generation=generation)
        except NativeGatewayError as exc:
            if selected != "small" or exc.code not in {"GATEWAY_WHEP_REJECTED", "GATEWAY_INVALID_SDP"}:
                raise
            with self._lock:
                if generation != self._generation:
                    raise NativeGatewayError(409, "GATEWAY_SOURCE_CHANGED", "Camera changed during video negotiation") from None
            # Failed small peers are cleaned by the inner request's finally block.
            # Retry the fixed main path once, with the original camera guard.
            try:
                result = self._create_whep_session(sdp, owner, expected_source=expected_source,
                                                   quality="main", expected_generation=generation)
            except NativeGatewayError as final_error:
                if final_error.code not in {"GATEWAY_WHEP_REJECTED", "GATEWAY_INVALID_SDP", "GATEWAY_UNREACHABLE", "GATEWAY_NOT_READY"}:
                    raise
                raise NativeGatewayError(final_error.status_code, "SMALL_AND_MAIN_UNAVAILABLE",
                                         "Small and main native video negotiation are unavailable") from None
            reason = "SMALL_NEGOTIATION_FAILED"
        return result | {"requested_quality": quality, "quality_fallback_reason": reason}

    def _create_whep_session(self, sdp: str, owner: str, *, expected_source: str | None,
                             quality: str, expected_generation: int) -> dict[str, str]:
        """Proxy bounded SDP negotiation; the browser gets only an app session ID."""
        if not str(owner or "").strip():
            raise NativeGatewayError(401, "SESSION_OWNER_REQUIRED", "Thiếu phiên đăng nhập")
        body = str(sdp or "").encode("utf-8")
        if len(body) > WHEP_MAX_BODY:
            raise NativeGatewayError(413, "SDP_TOO_LARGE", "SDP vượt giới hạn 64 KiB")
        if not body.startswith(b"v=0"):
            raise NativeGatewayError(400, "INVALID_SDP", "SDP offer không hợp lệ")
        session_id = str(uuid4())
        with self._lock:
            if expected_generation != self._generation:
                raise NativeGatewayError(409, "GATEWAY_SOURCE_CHANGED", "Camera changed during video negotiation")
            if expected_source is not None and normalize_camera_source(expected_source) != self._source:
                raise NativeGatewayError(409, "GATEWAY_SOURCE_CHANGED", "Gateway đang chuyển sang camera được chọn")
            if not self._ready_locked():
                raise NativeGatewayError(503, "GATEWAY_NOT_READY", self._last_error or "MediaMTX chưa sẵn sàng")
            owners = ([item["owner"] for item in self._sessions.values()]
                      + [item["owner"] for item in self._small_retired_sessions.values()]
                      + list(self._pending_sessions.values()))
            if len(owners) >= WHEP_MAX_SESSIONS or owners.count(owner) >= WHEP_MAX_OWNER_SESSIONS:
                raise NativeGatewayError(429, "GATEWAY_SESSION_LIMIT", "Đã đạt giới hạn phiên Live View")
            generation = self._generation
            path = GATEWAY_QUALITY_PATHS[quality]
            small_generation = self._small_generation
            if quality == "small" and not (self._small_source and self._small_configured):
                raise NativeGatewayError(409, "GATEWAY_SOURCE_CHANGED", "Small video source changed")
            password = self._internal_password
            self._pending_sessions[session_id] = owner
        upstream_url = ""
        try:
            status, headers, answer = self._http_request(
                "POST", f"http://{GATEWAY_HTTP_HOST}:{GATEWAY_HTTP_PORT}/{path}/whep",
                body, timeout=10.0, password=password)
            if status != 201:
                raise self._upstream_error(status, answer, password, expected_source or "", path)
            upstream_url = self._validate_session_location(self._header(headers, "Location"), path)
            if (self._header(headers, "Content-Type").split(";", 1)[0].strip().lower() != "application/sdp"
                    or not answer.startswith(b"v=0")):
                raise NativeGatewayError(502, "GATEWAY_INVALID_SDP", "MediaMTX trả SDP answer không hợp lệ")
            answer_text = answer.decode("utf-8", errors="strict")
            with self._lock:
                if (generation != self._generation or not self._desired or self._shutting_down
                        or quality == "small" and (small_generation != self._small_generation or not self._small_configured)):
                    raise NativeGatewayError(409, "GATEWAY_SOURCE_CHANGED", "Camera đã thay đổi trong lúc khởi tạo video")
                upstream_id = self._header(headers, "ID")
                self._sessions[session_id] = {"owner": owner, "url": upstream_url,
                                              "upstream_id": upstream_id, "created": time.monotonic(),
                                              "password": password, "path": path, "quality": quality,
                                              "source": self._source,
                                              "generation": generation, "small_generation": small_generation}
            return {"sdp": answer_text, "session_id": session_id, "quality": quality}
        except UnicodeDecodeError:
            raise NativeGatewayError(502, "GATEWAY_INVALID_SDP", "SDP answer không có mã hóa UTF-8 hợp lệ") from None
        except NativeGatewayError as exc:
            with self._lock:
                if quality == "main":
                    self._last_error = self._safe_message(str(exc), source=expected_source or "", password=password)
            raise
        finally:
            with self._lock:
                self._pending_sessions.pop(session_id, None)
                kept = session_id in self._sessions
            if upstream_url and not kept:
                try:
                    self._http_request("DELETE", upstream_url, timeout=0.5, password=password)
                except NativeGatewayError:
                    pass

    def delete_whep_session(self, session_id: str, owner: str) -> bool:
        with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None:
                return False
            if session["owner"] != owner:
                raise NativeGatewayError(403, "SESSION_OWNER_MISMATCH", "Phiên video thuộc người dùng khác")
            self._validate_session_location(session["url"], session.get("path", GATEWAY_PATH))
        status, _, body = self._http_request("DELETE", session["url"], timeout=1.0, password=session["password"])
        if status not in {200, 204, 404}:
            raise self._upstream_error(status, body, session["password"], session.get("source", ""),
                                       session.get("path", GATEWAY_PATH))
        with self._lock:
            if self._sessions.get(str(session_id)) is session:
                self._sessions.pop(str(session_id), None)
        return True

    def patch_whep_session(self, session_id: str, owner: str, fragment: str) -> bool:
        """Forward bounded trickle ICE only to the owner's already-bound path."""
        body = str(fragment or "").encode("utf-8")
        if not body or len(body) > WHEP_MAX_BODY:
            raise NativeGatewayError(413 if body else 400, "INVALID_ICE_FRAGMENT", "Invalid ICE fragment size")
        with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None:
                return False
            if session["owner"] != owner:
                raise NativeGatewayError(403, "SESSION_OWNER_MISMATCH", "Video session belongs to another user")
            self._validate_session_location(session["url"], session.get("path", GATEWAY_PATH))
            if (session.get("generation", self._generation) != self._generation
                    or session.get("quality") == "small" and session.get("small_generation") != self._small_generation):
                raise NativeGatewayError(409, "GATEWAY_SOURCE_CHANGED", "Camera changed during video negotiation")
        status, _, payload = self._http_request("PATCH", session["url"], body, timeout=1.0,
            password=session["password"], content_type="application/trickle-ice-sdpfrag")
        if status not in {200, 204}:
            raise self._upstream_error(status, payload, session["password"], session.get("source", ""),
                                       session.get("path", GATEWAY_PATH))
        return True

    def _ready_locked(self) -> bool:
        return bool(self._desired and not self._retire_failed and self._process is not None and self._process.poll() is None
                    and self._port_open(GATEWAY_HTTP_HOST, GATEWAY_HTTP_PORT, 0.08))

    def relay_source(self, source: str) -> str:
        """Private recorder input; never serialize or log this credentialed URI."""
        with self._lock:
            if (normalize_camera_source(str(source or "")) != self._source or not self._ready_locked()
                    or not self._port_open(GATEWAY_HTTP_HOST, GATEWAY_RTSP_PORT, 0.08)):
                return ""
            return f"rtsp://{self._internal_user}:{self._internal_password}@{GATEWAY_HTTP_HOST}:{GATEWAY_RTSP_PORT}/{GATEWAY_PATH}"

    def _api_json(self, path: str) -> dict[str, Any]:
        status, _, body = self._http_request("GET", f"http://{GATEWAY_HTTP_HOST}:{GATEWAY_API_PORT}{path}")
        if status != 200:
            raise NativeGatewayError(503, "GATEWAY_API_ERROR", f"MediaMTX diagnostics HTTP {status}")
        try:
            value = json.loads(body)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
        raise NativeGatewayError(503, "GATEWAY_API_INVALID", "MediaMTX diagnostics không hợp lệ")

    @staticmethod
    def _count(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (ValueError, TypeError):
            return 0

    def _refresh_diagnostics_locked(self) -> None:
        now = time.monotonic()
        if now - self._diagnostics_at < 2.0:
            return
        self._diagnostics_at = now
        try:
            path = self._api_json(f"/v3/paths/get/{GATEWAY_PATH}")
            sessions = self._api_json("/v3/webrtc/sessions/list?itemsPerPage=100").get("items", [])
            sessions = [item for item in sessions if isinstance(item, dict)
                        and item.get("path") in GATEWAY_QUALITY_PATHS.values()]
            codecs = []
            for track in path.get("tracks2") or []:
                if not isinstance(track, dict):
                    continue
                codec = str(track.get("codec") or "")
                if not re.fullmatch(r"[A-Za-z0-9]{1,20}", codec):
                    continue
                props = track.get("codecProps") or {}
                item = {"codec": codec}
                for key in ("width", "height"):
                    if key in props:
                        item[key] = self._count(props[key])
                for key in ("profile", "level"):
                    value = str(props.get(key) or "")
                    if re.fullmatch(r"[A-Za-z0-9 ._-]{1,40}", value):
                        item[key] = value
                codecs.append(item)
            # In v1.21.1 an on-demand static source can have online=true while
            # its handler exists but no stream is available yet. Require the
            # stream's availability as well; a listening gateway is not proof
            # that the upstream camera is delivering media.
            source_ready = bool(path.get("available", path.get("ready", False))
                                and path.get("online", True))
            if source_ready:
                # An old connection error must not turn a healthy source's
                # subsequent on-demand idle state into a permanent failure.
                self._source_error = ""
            readers = len(path.get("readers") or [])
            source_state = "READY" if source_ready else (
                "ERROR" if self._source_error else ("CONNECTING" if readers or self._pending_sessions else "IDLE"))
            self._diagnostics = {
                "api_ready": True, "source_healthy": source_ready if source_state != "IDLE" else None,
                "source_state": source_state, "source_on_demand": True, "source_codecs": codecs,
                "source_inbound_bytes": self._count(path.get("inboundBytes", path.get("bytesReceived"))),
                "source_frames_in_error": self._count(path.get("inboundFramesInError")),
                "source_reader_count": readers, "webrtc_session_count": len(sessions),
                "webrtc_connected_count": sum(bool(item.get("peerConnectionEstablished")) for item in sessions),
                "source_error": "" if source_ready else self._source_error,
                "diagnostics_error": "", "diagnostics_updated_at": time.time(),
            }
            # Closed browser peers disappear in MediaMTX. Bound app metadata too,
            # while allowing up to 30 seconds for a new negotiation to appear.
            live_ids = {str(item.get("id") or "") for item in sessions}
            for sid, session in list(self._sessions.items()):
                age = now - session["created"]
                if age > 30 and session["upstream_id"] and session["upstream_id"] not in live_ids:
                    self._sessions.pop(sid, None)
                elif age > 43200:
                    # One expiration per poll keeps diagnostics work bounded.
                    self.delete_whep_session(sid, session["owner"])
                    break
        except NativeGatewayError as exc:
            self._diagnostics = {"api_ready": False, "source_healthy": None, "source_state": "UNKNOWN",
                                 "diagnostics_error": self._safe_message(str(exc)), "source_error": self._source_error}

    def status(self, _already_locked: bool = False) -> dict[str, Any]:
        if not _already_locked:
            with self._lock:
                return self.status(_already_locked=True)
        proc = self._process
        alive = bool(proc is not None and proc.poll() is None)
        port_ready = bool(alive and self._port_open(GATEWAY_HTTP_HOST, GATEWAY_HTTP_PORT, 0.08))
        if alive and port_ready and not self._retire_failed:
            self._refresh_diagnostics_locked()
        source_kind = "rtsp" if self._is_rtsp(self._source) else ("local" if self._source else "none")
        binary = self.binary_path()
        binary_present = bool(not self._binary_reason and binary.is_file())
        available = bool(self._desired and alive and port_ready and not self._retire_failed)
        reason = "" if available else (
            (self._binary_reason or "MEDIAMTX_NOT_INSTALLED") if not binary_present else
            "GATEWAY_STOP_TIMEOUT" if self._retire_failed else
            "NATIVE_GATEWAY_DISABLED" if not GATEWAY_ENABLED else
            "SOURCE_NOT_RTSP" if source_kind == "local" else
            "SOURCE_NOT_CONFIGURED" if source_kind == "none" else "NATIVE_GATEWAY_UNAVAILABLE")
        return {
            "enabled": bool(GATEWAY_ENABLED),
            "available": available,
            "native_webrtc": available,
            "state": "AVAILABLE" if available else "UNAVAILABLE" if not binary_present else "BLOCKED",
            "reason": reason,
            "reason_code": reason,
            "process_alive": alive,
            "port_ready": port_ready,
            "binary_present": binary_present,
            "version": GATEWAY_VERSION,
            "transport": "NATIVE_GATEWAY_WEBRTC" if available else "NONE",
            "preferred_transport": "NATIVE_GATEWAY_WEBRTC",
            "path": GATEWAY_PATH,
            "whep_url": "/api/v1/media/gateway/whep" if self._desired else "",
            "source_kind": source_kind,
            "source_label": self._safe_message(self._source_label),
            "pid": int(proc.pid) if alive and proc is not None else 0,
            "restart_count": int(self._restart_count),
            "started_at": float(self._started_at),
            "last_error": self._safe_message(self._last_error),
            "restart_backoff_ms": max(0, int((self._next_restart_at - time.monotonic()) * 1000)),
            "lan_media": self._lan_mode(),
            "ice_port": GATEWAY_ICE_PORT,
            "signalling_auth": "APPLICATION_RBAC_PROXY",
            "recorder_relay_available": bool(not self._retire_failed and alive and self._port_open(GATEWAY_HTTP_HOST, GATEWAY_RTSP_PORT, 0.08)),
            "retirement_blocked": self._retire_failed,
            "app_session_count": len(self._sessions),
            "pending_session_count": len(self._pending_sessions),
            "api_ready": False,
            "source_healthy": None,
            "source_state": "RETIREMENT_BLOCKED" if self._retire_failed else "UNKNOWN" if alive else "STOPPED",
            "source_codecs": [],
            "source_error": self._source_error,
            "diagnostics_error": "",
            "secret_on_disk": False,
            "ai_independent": True,
            **self._small_status_locked(),
            **self._diagnostics,
        }


MEDIA_GATEWAY = NativeMediaGateway()
