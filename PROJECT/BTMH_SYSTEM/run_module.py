from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Bundle a small pure-Python WebSocket transport so existing offline customer
# runtimes do not need pip/network access just to enable the realtime preview.
VENDOR_PY = ROOT / "vendor_py"
if VENDOR_PY.exists():
    sys.path.insert(0, str(VENDOR_PY))


def _data_root() -> Path:
    configured = os.getenv("CAMPUSFACE_DATA_ROOT", "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    if os.name == "nt":
        return Path(os.path.expandvars(r"%LOCALAPPDATA%\CampusFace"))
    return ROOT / ".campusface-data"


def _load_postgres_runtime_env() -> None:
    """Force this process to use the port selected by postgres_guard.

    This intentionally overrides inherited CAMPUSFACE_POSTGRES_* variables for
    normal Windows launches. A stale user/system environment variable must not
    pin the application to a Windows-reserved port after the guard has moved the
    private cluster to a safe port.
    """
    path = _data_root() / "config" / "module.env"
    if not path.exists():
        return
    allowed = {
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
    }
    for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in allowed:
            os.environ[key] = value.strip().strip('"').strip("'")


def _postgres_preflight() -> None:
    if os.name != "nt" or os.getenv("BTMH_SKIP_POSTGRES_GUARD", "").strip() == "1":
        return
    guard = ROOT / "scripts" / "postgres_guard.py"
    if not guard.exists():
        return
    cp = subprocess.run([sys.executable, str(guard)], cwd=str(ROOT), check=False)
    if cp.returncode != 0:
        print("[ERROR] Local PostgreSQL preflight failed.")
        print("[ACTION] Run INSTALL_NEW_PC.bat or 03_TOOLS_DIAGNOSTIC\\CHECK_DATABASE.bat.")
        raise SystemExit(cp.returncode)
    _load_postgres_runtime_env()


def _websocket_mode() -> str:
    if importlib.util.find_spec("websockets") or importlib.util.find_spec("wsproto"):
        return "auto"
    return "none"


def _web_url(host: str, port: int) -> str:
    # Wildcard binds are listen addresses, not destinations for the browser.
    address = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    if ":" in address and not address.startswith("["):
        address = f"[{address}]"
    return f"http://{address}:{port}/"


def main() -> int:
    if os.getenv("BTMH_UI_PREVIEW", "0") == "1":
        print("[ERROR] UI_PREVIEW cannot use the real runtime entrypoint. Use the separate preview launcher.", flush=True)
        return 7
    _postgres_preflight()
    import uvicorn
    from module_app.config import HOST, PORT

    class StartupServer(uvicorn.Server):
        async def startup(self, sockets=None) -> None:
            await super().startup(sockets=sockets)
            # Uvicorn sets started only after successful application lifespan
            # startup and socket binding. A failed startup must never open UI.
            if self.started:
                url = _web_url(HOST, PORT)
                print(f"[WEB_READY] Backend startup complete. Web: {url}", flush=True)
                print("[INFO] Camera, AI and recording availability are reported by the real runtime status.", flush=True)
                if os.getenv("BTMH_OPEN_BROWSER", "0") == "1":
                    try:
                        import webbrowser
                        if not webbrowser.open(url):
                            print("[ACTION] Open the web URL above in your browser.", flush=True)
                    except Exception:
                        print("[ACTION] Open the web URL above in your browser.", flush=True)

    server = StartupServer(uvicorn.Config(
        "module_app.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        access_log=False,
        ws=_websocket_mode(),
        timeout_graceful_shutdown=1,
    ))
    server.run()
    if not server.started:
        print("[ERROR] Backend startup did not complete. Review the startup error above.", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
