from __future__ import annotations

import ctypes
import json
import os
import shutil
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from .camera import CAMERA
from .office_engine import OFFICE
from .config import CONFIG_DIR, DATA_ROOT
from .db import add_audit_event, fetchone, utc_now
from .gpu_manager import gpu_status
from .production_ops import create_backup, list_backups


_DEFAULT_CONFIG: dict[str, Any] = {
    "watchdog_enabled": True,
    "camera_auto_recovery": True,
    "camera_stale_sec": 8.0,
    "camera_bad_confirm_sec": 4.0,
    "recovery_cooldown_sec": 45.0,
    "auto_backup_enabled": True,
    "auto_backup_interval_hours": 24.0,
    "auto_backup_retention": 14,
    "health_interval_sec": 2.0,
    "disk_warn_free_gb": 8.0,
    "ram_warn_percent": 88.0,
    "cpu_warn_percent": 92.0,
    "gpu_warn_percent": 94.0,
}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _sanitize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = dict(_DEFAULT_CONFIG)
    if isinstance(raw, dict):
        src.update(raw)
    out = {
        "watchdog_enabled": bool(src.get("watchdog_enabled", True)),
        "camera_auto_recovery": bool(src.get("camera_auto_recovery", True)),
        "camera_stale_sec": max(4.0, min(60.0, _safe_float(src.get("camera_stale_sec"), 8.0))),
        "camera_bad_confirm_sec": max(2.0, min(30.0, _safe_float(src.get("camera_bad_confirm_sec"), 4.0))),
        "recovery_cooldown_sec": max(20.0, min(600.0, _safe_float(src.get("recovery_cooldown_sec"), 45.0))),
        "auto_backup_enabled": bool(src.get("auto_backup_enabled", True)),
        "auto_backup_interval_hours": max(6.0, min(168.0, _safe_float(src.get("auto_backup_interval_hours"), 24.0))),
        "auto_backup_retention": max(3, min(60, _safe_int(src.get("auto_backup_retention"), 14))),
        "health_interval_sec": max(1.0, min(10.0, _safe_float(src.get("health_interval_sec"), 2.0))),
        "disk_warn_free_gb": max(1.0, min(500.0, _safe_float(src.get("disk_warn_free_gb"), 8.0))),
        "ram_warn_percent": max(50.0, min(99.0, _safe_float(src.get("ram_warn_percent"), 88.0))),
        "cpu_warn_percent": max(50.0, min(99.0, _safe_float(src.get("cpu_warn_percent"), 92.0))),
        "gpu_warn_percent": max(50.0, min(99.0, _safe_float(src.get("gpu_warn_percent"), 94.0))),
    }
    return out


def _filetime_to_int(ft: wintypes.FILETIME) -> int:
    return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)


class _ResourceSampler:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_cpu: tuple[int, int] | None = None
        self._last_cpu_percent = 0.0

    def _cpu_windows(self) -> float:
        idle = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return self._last_cpu_percent
        idle_i = _filetime_to_int(idle)
        total_i = _filetime_to_int(kernel) + _filetime_to_int(user)
        current = (idle_i, total_i)
        if self._last_cpu is None:
            self._last_cpu = current
            return self._last_cpu_percent
        prev_idle, prev_total = self._last_cpu
        self._last_cpu = current
        total_delta = max(1, total_i - prev_total)
        idle_delta = max(0, idle_i - prev_idle)
        value = max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))
        self._last_cpu_percent = value
        return value

    def _cpu_linux(self) -> float:
        try:
            fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
            vals = [int(x) for x in fields]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
            current = (idle, total)
            if self._last_cpu is None:
                self._last_cpu = current
                return self._last_cpu_percent
            prev_idle, prev_total = self._last_cpu
            self._last_cpu = current
            total_delta = max(1, total - prev_total)
            idle_delta = max(0, idle - prev_idle)
            value = max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))
            self._last_cpu_percent = value
            return value
        except Exception:
            return self._last_cpu_percent

    def cpu_percent(self) -> float:
        with self._lock:
            return round(self._cpu_windows() if os.name == "nt" else self._cpu_linux(), 1)

    @staticmethod
    def memory() -> dict[str, float]:
        if os.name == "nt":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                total = float(st.ullTotalPhys)
                avail = float(st.ullAvailPhys)
                used = max(0.0, total - avail)
                return {
                    "total_bytes": total,
                    "available_bytes": avail,
                    "used_bytes": used,
                    "percent": round((used / total * 100.0) if total else 0.0, 1),
                }
        try:
            rows: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                rows[k] = int(v.strip().split()[0]) * 1024
            total = float(rows.get("MemTotal", 0))
            avail = float(rows.get("MemAvailable", rows.get("MemFree", 0)))
            used = max(0.0, total - avail)
            return {
                "total_bytes": total,
                "available_bytes": avail,
                "used_bytes": used,
                "percent": round((used / total * 100.0) if total else 0.0, 1),
            }
        except Exception:
            return {"total_bytes": 0.0, "available_bytes": 0.0, "used_bytes": 0.0, "percent": 0.0}

    @staticmethod
    def process_rss_bytes() -> int:
        if os.name == "nt":
            try:
                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ]
                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    return int(counters.WorkingSetSize)
            except Exception:
                return 0
        try:
            import resource
            value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return value * (1024 if os.name != "darwin" else 1)
        except Exception:
            return 0

    def snapshot(self) -> dict[str, Any]:
        mem = self.memory()
        disk = shutil.disk_usage(DATA_ROOT)
        return {
            "cpu_percent": self.cpu_percent(),
            "ram_percent": float(mem.get("percent") or 0.0),
            "ram_used_bytes": int(mem.get("used_bytes") or 0),
            "ram_total_bytes": int(mem.get("total_bytes") or 0),
            "process_rss_bytes": self.process_rss_bytes(),
            "disk_free_bytes": int(disk.free),
            "disk_total_bytes": int(disk.total),
        }


class ProductionPilotSupervisor:
    """Small local-only production watchdog for the single-PC pilot.

    It does not open camera streams, start cloud services, or bypass the camera
    ownership rules. Recovery goes through CameraService.restart(), which preserves
    the V2.9.1 single FFmpeg decoder ownership invariant.
    """

    def __init__(self) -> None:
        self._path = Path(CONFIG_DIR) / "production_pilot.json"
        self._config = self._load_config()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = time.time()
        self._sampler = _ResourceSampler()
        self._latest: dict[str, Any] = {}
        self._camera_bad_since = 0.0
        self._last_recovery_at = 0.0
        self._recovery_count = 0
        self._last_recovery_reason = ""
        self._last_backup_check = 0.0
        self._last_auto_backup_at = 0.0
        self._first_backup_not_before = time.time() + 600.0
        self._last_error = ""
        self._event_dedup: dict[str, float] = {}

    def _load_config(self) -> dict[str, Any]:
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return _sanitize_config(raw)
        except Exception:
            pass
        return _sanitize_config({})

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._config, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def config(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._config)

    def save_config(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            merged = dict(self._config)
            merged.update(values or {})
            self._config = _sanitize_config(merged)
            self._persist()
            return dict(self._config)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._loop, name="cf-production-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None

    def _audit(self, event_type: str, status: str, detail: dict[str, Any], *, cooldown: float = 30.0) -> None:
        now = time.time()
        last = float(self._event_dedup.get(event_type) or 0.0)
        if now - last < cooldown:
            return
        self._event_dedup[event_type] = now
        try:
            add_audit_event("TECHNICAL", event_type, status, camera_source=CAMERA.event_camera_source(), detail=detail)
        except Exception:
            pass

    def _db_latency_ms(self) -> tuple[bool, float, str]:
        t0 = time.perf_counter()
        try:
            row = fetchone("SELECT 1 AS ok") or {}
            return bool(int(row.get("ok") or 0) == 1), round((time.perf_counter() - t0) * 1000.0, 1), ""
        except Exception as exc:
            return False, round((time.perf_counter() - t0) * 1000.0, 1), str(exc)

    def _backup_timestamp(self, *, auto_only: bool = False) -> float:
        try:
            rows = list_backups()
            if auto_only:
                rows = [x for x in rows if "-auto" in str(x.get("name") or "")]
            if not rows:
                return 0.0
            raw = str(rows[0].get("created_at") or "")
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            from datetime import datetime
            return datetime.fromisoformat(raw).timestamp()
        except Exception:
            return 0.0

    def _last_auto_backup(self) -> float:
        return self._backup_timestamp(auto_only=True)

    def _prune_auto_backups(self, keep: int) -> None:
        try:
            from .config import BACKUP_DIR
            files = sorted(BACKUP_DIR.glob("CampusFace-Backup-*-auto.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
            for path in files[max(1, int(keep)):]:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass

    def _maybe_auto_backup(self, now: float, cfg: dict[str, Any]) -> None:
        if not bool(cfg.get("auto_backup_enabled")):
            return
        # Backup checks are intentionally sparse. pg_dump + snapshots may be large.
        if now - self._last_backup_check < 60.0:
            return
        self._last_backup_check = now
        last = max(self._last_auto_backup_at, self._last_auto_backup(), self._backup_timestamp(auto_only=False))
        interval = float(cfg.get("auto_backup_interval_hours") or 24.0) * 3600.0
        if last and now - last < interval:
            self._last_auto_backup_at = max(self._last_auto_backup_at, self._last_auto_backup())
            return
        if not last and now < self._first_backup_not_before:
            return
        try:
            result = create_backup("auto")
            self._last_auto_backup_at = now
            self._prune_auto_backups(int(cfg.get("auto_backup_retention") or 14))
            self._audit("AUTO_BACKUP_CREATED", "SUCCESS", {"name": result.get("name"), "size": result.get("size")}, cooldown=5.0)
        except Exception as exc:
            self._last_error = str(exc)
            self._audit("AUTO_BACKUP_FAILED", "WARNING", {"error": str(exc)}, cooldown=3600.0)

    def _recover_if_needed(self, now: float, cfg: dict[str, Any], camera: dict[str, Any]) -> None:
        if not (bool(cfg.get("watchdog_enabled")) and bool(cfg.get("camera_auto_recovery"))):
            self._camera_bad_since = 0.0
            return
        running = bool(camera.get("running", True))
        opened = bool(camera.get("opened"))
        state = str(camera.get("state") or "").lower()
        age = _safe_float(camera.get("last_frame_age_ms"), 0.0) / 1000.0
        stale_sec = float(cfg.get("camera_stale_sec") or 8.0)
        bad = running and (not opened or state in {"error", "offline", "stopped"} or (age > stale_sec and age > 0))
        if not bad:
            self._camera_bad_since = 0.0
            return
        if self._camera_bad_since <= 0:
            self._camera_bad_since = now
            return
        if now - self._camera_bad_since < float(cfg.get("camera_bad_confirm_sec") or 4.0):
            return
        if now - self._last_recovery_at < float(cfg.get("recovery_cooldown_sec") or 45.0):
            return
        reason = f"state={state or 'unknown'}, opened={opened}, frame_age={round(age,1)}s"
        self._last_recovery_at = now
        self._last_recovery_reason = reason
        try:
            CAMERA.restart()
            self._recovery_count += 1
            self._audit("CAMERA_AUTO_RECOVERY", "SUCCESS", {"reason": reason, "recovery_count": self._recovery_count}, cooldown=5.0)
        except Exception as exc:
            self._last_error = str(exc)
            self._audit("CAMERA_AUTO_RECOVERY_FAILED", "WARNING", {"reason": reason, "error": str(exc)}, cooldown=30.0)
        finally:
            self._camera_bad_since = 0.0

    def _ensure_workers(self, cfg: dict[str, Any]) -> None:
        if not bool(cfg.get("watchdog_enabled")):
            return
        try:
            office = OFFICE.status()
            if not bool(office.get("running")):
                OFFICE.start()
                self._audit("OFFICE_WORKER_RECOVERED", "SUCCESS", {}, cooldown=60.0)
        except Exception as exc:
            self._last_error = str(exc)

    def _sample(self) -> dict[str, Any]:
        cfg = self.config()
        camera = CAMERA.status()
        try:
            perf = CAMERA.performance_status()
        except Exception:
            perf = {}
        try:
            office = OFFICE.status()
        except Exception:
            office = {}
        resources = self._sampler.snapshot()
        gpu = gpu_status()
        db_ok, db_latency, db_error = self._db_latency_ms()
        cpu = float(resources.get("cpu_percent") or 0.0)
        ram = float(resources.get("ram_percent") or 0.0)
        gpu_util = float(gpu.get("utilization_percent") or 0.0)
        disk_free_gb = float(resources.get("disk_free_bytes") or 0) / 1024 / 1024 / 1024
        cam_online = bool(camera.get("opened")) and str(camera.get("state") or "").lower() == "online"
        warnings: list[str] = []
        if cpu >= float(cfg.get("cpu_warn_percent") or 92.0): warnings.append("CPU cao")
        if ram >= float(cfg.get("ram_warn_percent") or 88.0): warnings.append("RAM cao")
        if gpu_util >= float(cfg.get("gpu_warn_percent") or 94.0): warnings.append("GPU cao")
        if disk_free_gb <= float(cfg.get("disk_warn_free_gb") or 8.0): warnings.append("Ổ đĩa sắp đầy")
        if not cam_online: warnings.append("Camera chưa online")
        if not db_ok: warnings.append("Database không phản hồi")
        if str(camera.get("camera_quality") or "UNKNOWN").upper() == "POOR": warnings.append("Chất lượng hình ảnh thấp")
        return {
            "ok": not any(x in warnings for x in ("Camera chưa online", "Database không phản hồi")),
            "status": "WARNING" if warnings else "HEALTHY",
            "warnings": warnings,
            "uptime_sec": round(max(0.0, time.time() - self._started_at), 1),
            "resources": resources,
            "gpu": gpu,
            "database": {"ok": db_ok, "latency_ms": db_latency, "error": db_error},
            "camera": camera,
            "performance": perf,
            "identity_observer": {
                "mode": "IDENTITY_ONLY",
                "visible_tracks": int(camera.get("visible_tracks") or 0),
                "ai_fps": float(camera.get("ai_fps") or 0.0),
            },
            "office": office,
            "watchdog": {
                "enabled": bool(cfg.get("watchdog_enabled")),
                "camera_auto_recovery": bool(cfg.get("camera_auto_recovery")),
                "recovery_count": int(self._recovery_count),
                "last_recovery_at": self._last_recovery_at,
                "last_recovery_reason": self._last_recovery_reason,
                "camera_bad_since": self._camera_bad_since,
            },
            "backup": {
                "enabled": bool(cfg.get("auto_backup_enabled")),
                "interval_hours": float(cfg.get("auto_backup_interval_hours") or 24.0),
                "retention": int(cfg.get("auto_backup_retention") or 14),
                "last_auto_backup_at": float(self._last_auto_backup_at or self._last_auto_backup()),
            },
            "last_error": self._last_error,
            "generated_at": utc_now(),
        }

    def force_check(self) -> dict[str, Any]:
        snap = self._sample()
        with self._lock:
            self._latest = snap
        return snap

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest = dict(self._latest)
        if not latest:
            latest = self.force_check()
        latest["config"] = self.config()
        latest["running"] = bool(self._thread and self._thread.is_alive())
        return latest

    def recover_camera_now(self) -> dict[str, Any]:
        try:
            CAMERA.restart()
            self._last_recovery_at = time.time()
            self._recovery_count += 1
            self._last_recovery_reason = "manual production recovery"
            self._audit("CAMERA_MANUAL_RECOVERY", "SUCCESS", {"recovery_count": self._recovery_count}, cooldown=1.0)
        except Exception as exc:
            self._last_error = str(exc)
            raise
        return self.force_check()

    def _loop(self) -> None:
        # Prime the CPU delta sampler before the first UI request.
        try:
            self._sampler.cpu_percent()
        except Exception:
            pass
        while not self._stop.is_set():
            cfg = self.config()
            now = time.time()
            try:
                camera = CAMERA.status()
                self._recover_if_needed(now, cfg, camera)
                self._ensure_workers(cfg)
                self._maybe_auto_backup(now, cfg)
                snap = self._sample()
                with self._lock:
                    self._latest = snap
            except Exception as exc:
                self._last_error = str(exc)
                self._audit("PRODUCTION_WATCHDOG_ERROR", "WARNING", {"error": str(exc)}, cooldown=60.0)
            self._stop.wait(float(cfg.get("health_interval_sec") or 2.0))


PILOT = ProductionPilotSupervisor()
