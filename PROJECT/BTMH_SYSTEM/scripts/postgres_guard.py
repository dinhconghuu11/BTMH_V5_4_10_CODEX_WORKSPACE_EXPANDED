from __future__ import annotations

"""BTMH Face V3.3 PostgreSQL supervisor for Windows.

Goals:
- never wait forever;
- never assume an unused port is actually bindable on Windows;
- prefer the existing private cluster and preserve customer data;
- start PostgreSQL directly with postgres.exe so pg_ctl cannot block startup;
- persist the selected local port for the web application;
- provide bounded status/stop/ensure commands for diagnostics and setup.
"""

import argparse
import csv
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

DEFAULT_PORT = 55442
PORT_SEARCH_RADIUS = 160
START_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 15
EXIT_WINDOWS_ASLR_487 = 87

if os.name == "nt":
    CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
else:
    CREATE_NO_WINDOW = 0
    CREATE_NEW_PROCESS_GROUP = 0


def data_root() -> Path:
    explicit = os.getenv("CAMPUSFACE_DATA_ROOT", "").strip()
    if explicit:
        return Path(os.path.expandvars(os.path.expanduser(explicit)))
    if os.name == "nt":
        return Path(os.path.expandvars(r"%LOCALAPPDATA%\CampusFace"))
    return Path.home() / ".campusface"


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines() if path.exists() else []
    output: list[str] = []
    seen: set[str] = set()
    for raw in existing:
        if "=" not in raw or raw.lstrip().startswith("#"):
            output.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(raw)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_runtime_env_bat(root: Path, values: dict[str, str]) -> Path:
    path = root / "config" / "postgres_runtime_env.bat"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["@echo off", "rem Generated automatically by BTMH Face V3.3."]
    for key in (
        "CAMPUSFACE_DATA_ROOT",
        "CAMPUSFACE_DB_MODE",
        "CAMPUSFACE_POSTGRES_HOST",
        "CAMPUSFACE_POSTGRES_PORT",
        "CAMPUSFACE_POSTGRES_DB",
        "CAMPUSFACE_POSTGRES_USER",
        "CAMPUSFACE_POSTGRES_SSLMODE",
        "CAMPUSFACE_POSTGRES_BIN",
        "CAMPUSFACE_POSTGRES_DATA",
        "CAMPUSFACE_POSTGRES_LAUNCH_MODE",
    ):
        value = str(values.get(key, "")).replace("%", "%%")
        lines.append(f'set "{key}={value}"')
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def tcp_connects(port: int, timeout: float = 0.30) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def port_can_bind(port: int) -> tuple[bool, str]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", int(port)))
        return True, ""
    except OSError as exc:
        win = getattr(exc, "winerror", None)
        code = f"winerror={win}" if win is not None else f"errno={getattr(exc, 'errno', None)}"
        return False, f"{code}: {exc}"
    finally:
        try:
            s.close()
        except Exception:
            pass


def excluded_ranges_windows() -> list[tuple[int, int]]:
    if os.name != "nt":
        return []
    ranges: list[tuple[int, int]] = []
    for family in ("ipv4", "ipv6"):
        try:
            cp = subprocess.run(
                ["netsh", "interface", family, "show", "excludedportrange", "protocol=tcp"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=6,
                check=False,
            )
        except Exception:
            continue
        for raw in cp.stdout.splitlines():
            m = re.match(r"^\s*(\d{2,5})\s+(\d{2,5})(?:\s+\*)?\s*$", raw)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                if 1 <= start <= end <= 65535:
                    ranges.append((start, end))
    return ranges


def in_ranges(port: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(start <= port <= end for start, end in ranges)


def run_bounded(cmd: list[str], timeout: float = 8) -> int | None:
    """Run a short helper without stdout/stderr pipes.

    Avoiding PIPE is intentional: on Windows a child spawned by pg_ctl can inherit
    pipe handles and keep communicate() open even after pg_ctl itself exits.
    """
    creationflags = CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            return None
    except OSError:
        return -1


def read_postmaster_pid(pgdata: Path) -> int | None:
    path = pgdata / "postmaster.pid"
    try:
        first = path.read_text(encoding="ascii", errors="ignore").splitlines()[0].strip()
        pid = int(first)
        return pid if pid > 0 else None
    except Exception:
        return None


def windows_process_image(pid: int | None) -> str:
    if not pid or os.name != "nt":
        return ""
    try:
        cp = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=4,
            check=False,
        )
        if "no tasks are running" in cp.stdout.lower():
            return ""
        rows = list(csv.reader(cp.stdout.splitlines()))
        if not rows or len(rows[0]) < 2:
            return ""
        try:
            listed_pid = int(str(rows[0][1]).replace(",", "").strip())
        except ValueError:
            return ""
        return str(rows[0][0]).strip().lower() if listed_pid == int(pid) else ""
    except Exception:
        return "__unknown__"


def pid_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    return bool(windows_process_image(pid))


def pid_is_postgres(pid: int | None) -> bool:
    if os.name != "nt":
        return pid_is_alive(pid)
    image = windows_process_image(pid)
    # Unknown is treated conservatively as alive; a known recycled PID that is
    # not postgres.exe must not keep a stale postmaster.pid forever.
    return image == "__unknown__" or image == "postgres.exe"


def clean_stale_pid(pgdata: Path) -> None:
    pid_file = pgdata / "postmaster.pid"
    pid = read_postmaster_pid(pgdata)
    if pid_file.exists() and (not pid or not pid_is_postgres(pid)):
        try:
            pid_file.unlink()
            print(f"[PG] Removed stale postmaster.pid for old/recycled PID {pid or 'unknown'}.", flush=True)
        except OSError:
            pass


def candidate_ports(preferred: int, excluded: list[tuple[int, int]]) -> list[int]:
    raw = [preferred]
    raw += list(range(preferred + 1, min(65535, preferred + PORT_SEARCH_RADIUS) + 1))
    raw += list(range(54320, 54520))
    out: list[int] = []
    seen: set[int] = set()
    for port in raw:
        if port < 1024 or port > 65535 or port in seen or in_ranges(port, excluded):
            continue
        seen.add(port)
        out.append(port)
    return out


def choose_bindable_port(preferred: int, excluded: list[tuple[int, int]]) -> int:
    for port in candidate_ports(preferred, excluded):
        if tcp_connects(port):
            continue
        ok, _ = port_can_bind(port)
        if ok:
            return port
    raise RuntimeError("No usable localhost TCP port was found for private PostgreSQL.")


def pg_is_ready(pg_bin: Path, port: int, timeout: float = 2.0) -> bool:
    exe = pg_bin / "pg_isready.exe"
    if not exe.exists():
        return tcp_connects(port, timeout=min(timeout, 0.4))
    rc = run_bounded([str(exe), "-h", "127.0.0.1", "-p", str(port)], timeout=timeout)
    return rc == 0


def tail(path: Path, count: int = 80) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="ignore").splitlines()[-count:])
    except Exception:
        return ""


def start_postgres_direct(pg_bin: Path, pgdata: Path, log: Path, port: int) -> tuple[bool, str]:
    exe = pg_bin / "postgres.exe"
    if not exe.exists():
        return False, f"Missing {exe}"

    clean_stale_pid(pgdata)
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"[PG] Starting private PostgreSQL on 127.0.0.1:{port}...", flush=True)
    try:
        log_fp = open(log, "ab", buffering=0)
    except OSError as exc:
        return False, f"Cannot open PostgreSQL log: {exc}"

    creationflags = 0
    if os.name == "nt":
        creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    try:
        # Keep the private local instance deliberately small. On PostgreSQL 17
        # for Windows, large shared-memory reservations make Win32 error 487
        # substantially more likely. BTMH is a single-machine application and
        # does not benefit from server-sized shared_buffers/max_connections.
        proc = subprocess.Popen(
            [
                str(exe), "-D", str(pgdata), "-h", "127.0.0.1", "-p", str(port),
                "-c", "shared_buffers=32MB",
                "-c", "max_connections=50",
                "-c", "huge_pages=off",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        log_fp.close()
        return False, f"Could not launch postgres.exe: {exc}"

    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    next_notice = time.monotonic() + 2
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            log_fp.close()
            return False, f"postgres.exe exited early with code {rc}"
        if pg_is_ready(pg_bin, port, timeout=1.5):
            print(f"[OK] PostgreSQL accepted connections on 127.0.0.1:{port}.", flush=True)
            log_fp.close()
            return True, ""
        now = time.monotonic()
        if now >= next_notice:
            elapsed = int(START_TIMEOUT_SECONDS - max(0, deadline - now))
            print(f"[PG] Waiting for PostgreSQL... {elapsed}s/{START_TIMEOUT_SECONDS}s", flush=True)
            next_notice = now + 2
        time.sleep(0.30)

    # We own this process because we just spawned it, so terminating it is safe.
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    log_fp.close()
    return False, f"PostgreSQL did not become ready within {START_TIMEOUT_SECONDS} seconds"


def stop_cluster(pg_bin: Path, pgdata: Path, configured_port: int) -> bool:
    if not (pgdata / "PG_VERSION").exists():
        return True
    pgctl = pg_bin / "pg_ctl.exe"
    pid = read_postmaster_pid(pgdata)
    if not pid_is_alive(pid) and not pg_is_ready(pg_bin, configured_port, timeout=1):
        clean_stale_pid(pgdata)
        return True

    print("[PG] Stopping private PostgreSQL...", flush=True)
    if pgctl.exists():
        rc = run_bounded([str(pgctl), "stop", "-D", str(pgdata), "-m", "fast", "-W"], timeout=7)
        if rc is None:
            print("[WARN] pg_ctl stop timed out; waiting briefly for server shutdown.", flush=True)

    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        current_pid = read_postmaster_pid(pgdata)
        if not pid_is_alive(current_pid) and not pg_is_ready(pg_bin, configured_port, timeout=0.7):
            clean_stale_pid(pgdata)
            print("[OK] PostgreSQL stopped.", flush=True)
            return True
        time.sleep(0.35)
    print("[ERROR] PostgreSQL did not stop within the hard timeout.", flush=True)
    return False


def runtime_config(root: Path) -> tuple[Path, Path, Path, dict[str, str], int]:
    env_path = root / "config" / "module.env"
    cfg = read_env_file(env_path)
    try:
        preferred = int(cfg.get("CAMPUSFACE_POSTGRES_PORT", str(DEFAULT_PORT)) or DEFAULT_PORT)
    except ValueError:
        preferred = DEFAULT_PORT
    pg_bin = Path(os.path.expandvars(cfg.get("CAMPUSFACE_POSTGRES_BIN", str(root / "runtime" / "PostgreSQL17" / "bin"))))
    pg_data = Path(os.path.expandvars(cfg.get("CAMPUSFACE_POSTGRES_DATA", str(root / "PostgreSQL" / "data"))))
    log = root / "logs" / "postgres-runtime.log"
    return pg_bin, pg_data, log, cfg, preferred


def persist(root: Path, cfg: dict[str, str], pg_bin: Path, pg_data: Path, port: int) -> None:
    env_path = root / "config" / "module.env"
    values = {
        "CAMPUSFACE_DATA_ROOT": str(root),
        "CAMPUSFACE_DB_MODE": "postgres",
        "CAMPUSFACE_POSTGRES_HOST": "127.0.0.1",
        "CAMPUSFACE_POSTGRES_PORT": str(port),
        "CAMPUSFACE_POSTGRES_DB": cfg.get("CAMPUSFACE_POSTGRES_DB", "campusface"),
        "CAMPUSFACE_POSTGRES_USER": cfg.get("CAMPUSFACE_POSTGRES_USER", "campusface_app"),
        "CAMPUSFACE_POSTGRES_SSLMODE": "disable",
        "CAMPUSFACE_POSTGRES_BIN": str(pg_bin),
        "CAMPUSFACE_POSTGRES_DATA": str(pg_data),
        "CAMPUSFACE_POSTGRES_LAUNCH_MODE": "direct-postgres-v33",
    }
    update_env_file(env_path, values)
    write_runtime_env_bat(root, values)


def windows_aslr_487_detected(log: Path) -> bool:
    if os.name != "nt":
        return False
    recent = tail(log, 120).lower()
    return "could not reserve shared memory region" in recent and "error code 487" in recent


def rotate_runtime_log(log: Path) -> None:
    """Keep the current startup diagnostics separate from historical failures."""
    try:
        if not log.exists():
            return
        previous = log.with_name(log.stem + "-previous" + log.suffix)
        try:
            previous.unlink(missing_ok=True)
        except TypeError:
            if previous.exists():
                previous.unlink()
        os.replace(log, previous)
    except OSError:
        # Log rotation is diagnostic only; never block a database start for it.
        pass


def ensure() -> int:
    root = data_root()
    pg_bin, pg_data, log, cfg, preferred = runtime_config(root)
    if not (pg_bin / "postgres.exe").exists() or not (pg_data / "PG_VERSION").exists():
        print("[ERROR] Private PostgreSQL runtime/data is not installed yet.", flush=True)
        print("[ACTION] Run INSTALL_NEW_PC.bat once.", flush=True)
        return 20

    # Fast path: the configured PostgreSQL endpoint is already healthy.
    if pg_is_ready(pg_bin, preferred, timeout=2):
        persist(root, cfg, pg_bin, pg_data, preferred)
        print(f"[OK] PostgreSQL already ready: 127.0.0.1:{preferred}", flush=True)
        return 0

    # Start diagnostics for this attempt in a fresh file so an old 487 message
    # cannot poison later repair decisions.
    rotate_runtime_log(log)

    pid = read_postmaster_pid(pg_data)
    if pid_is_alive(pid):
        # A private cluster appears alive but is not healthy on its configured port.
        # Try a bounded clean stop before starting it on a verified port.
        print(f"[PG] Existing private cluster PID {pid} is not ready on port {preferred}.", flush=True)
        if not stop_cluster(pg_bin, pg_data, preferred):
            print("[ERROR] Existing PostgreSQL process could not be stopped safely.", flush=True)
            print(f"[LOG] {log}", flush=True)
            return 30
    else:
        clean_stale_pid(pg_data)

    excluded = excluded_ranges_windows()
    attempts = candidate_ports(preferred, excluded)[:32]
    for port in attempts:
        if tcp_connects(port):
            continue
        ok_bind, _reason = port_can_bind(port)
        if not ok_bind:
            continue
        if port != preferred:
            print(f"[PG] Port {preferred} is unavailable; trying safe port {port}.", flush=True)
        else:
            print(f"[PG] Port {port} passed the localhost bind test.", flush=True)
        ok, reason = start_postgres_direct(pg_bin, pg_data, log, port)
        if ok:
            persist(root, cfg, pg_bin, pg_data, port)
            print(f"[OK] PostgreSQL ready: 127.0.0.1:{port}", flush=True)
            return 0
        print(f"[WARN] Start attempt on port {port} failed: {reason}", flush=True)
        # A failed direct launch might have left a stale pid file; clean it only if dead.
        clean_stale_pid(pg_data)

        # Do not blindly cycle through dozens of ports when PostgreSQL itself
        # exits because of PGDATA/config/permission corruption. Only retry a
        # different port when the server log clearly describes a bind/socket
        # conflict. This keeps startup bounded and surfaces the real error.
        details = tail(log, 40)
        lower = details.lower()
        if windows_aslr_487_detected(log):
            print("[ERROR][PG-WIN-487] Windows blocked a PostgreSQL child shared-memory reservation.", flush=True)
            print("[ACTION] BTMH can apply a PostgreSQL-only Bottom-up ASLR compatibility override after UAC approval.", flush=True)
            print("[ACTION] Run scripts\\repair_postgres_windows_487.bat once, then start BTMH again.", flush=True)
            return EXIT_WINDOWS_ASLR_487
        bind_markers = (
            "could not bind", "address already in use", "could not create any tcp/ip sockets",
            "permission denied", "winsock", "socket",
        )
        if reason.startswith("postgres.exe exited early") and not any(m in lower for m in bind_markers):
            print("[ERROR] PostgreSQL exited for a non-port reason; stopping port retries.", flush=True)
            if details:
                print("[POSTGRES LOG - LAST LINES]", flush=True)
                print(details, flush=True)
            return 31

    print("[ERROR] PostgreSQL could not start on any verified local port.", flush=True)
    details = tail(log)
    if details:
        print("[POSTGRES LOG - LAST LINES]", flush=True)
        print(details, flush=True)
    return 32


def status() -> int:
    root = data_root()
    pg_bin, pg_data, _log, _cfg, preferred = runtime_config(root)
    if not (pg_bin / "postgres.exe").exists() or not (pg_data / "PG_VERSION").exists():
        print("[STATUS] NOT_INSTALLED")
        return 20
    pid = read_postmaster_pid(pg_data)
    ready = pg_is_ready(pg_bin, preferred, timeout=2)
    print(f"[STATUS] {'READY' if ready else 'NOT_READY'}")
    print(f"[PORT] {preferred}")
    print(f"[PID] {pid or ''}")
    return 0 if ready else 1


def stop() -> int:
    root = data_root()
    pg_bin, pg_data, _log, _cfg, preferred = runtime_config(root)
    return 0 if stop_cluster(pg_bin, pg_data, preferred) else 2


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("command", nargs="?", default="ensure", choices=("ensure", "status", "stop"))
    args = parser.parse_args()
    if args.command == "ensure":
        return ensure()
    if args.command == "status":
        return status()
    return stop()


if __name__ == "__main__":
    raise SystemExit(main())
