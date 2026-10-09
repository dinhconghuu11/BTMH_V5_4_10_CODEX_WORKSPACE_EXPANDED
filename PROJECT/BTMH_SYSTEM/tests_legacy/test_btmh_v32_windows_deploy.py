from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]


def load_guard():
    path = ROOT / "scripts" / "postgres_guard.py"
    spec = importlib.util.spec_from_file_location("postgres_guard_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_postgres_guard_can_distinguish_occupied_port() -> None:
    guard = load_guard()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    try:
        assert guard.tcp_connects(port)
        ok, _ = guard.port_can_bind(port)
        assert not ok
    finally:
        sock.close()


def test_env_file_update_is_stable(tmp_path: Path) -> None:
    guard = load_guard()
    env = tmp_path / "config" / "module.env"
    env.parent.mkdir(parents=True)
    env.write_text("X=1\nCAMPUSFACE_POSTGRES_PORT=55442\n", encoding="utf-8")
    guard.update_env_file(env, {"CAMPUSFACE_POSTGRES_PORT": "55477", "CAMPUSFACE_POSTGRES_HOST": "127.0.0.1"})
    values = guard.read_env_file(env)
    assert values["X"] == "1"
    assert values["CAMPUSFACE_POSTGRES_PORT"] == "55477"
    assert values["CAMPUSFACE_POSTGRES_HOST"] == "127.0.0.1"


def test_new_pc_deployment_layout_exists() -> None:
    required = [
        PROJECT / "INSTALL_AND_START_NEW_PC.bat",
        PROJECT / "INSTALL_NEW_PC.bat",
        PROJECT / "START_BTMH_FACE.bat",
        PROJECT / "01_INSTALL_NEW_PC" / "INSTALL_ALL_NEW_PC.bat",
        PROJECT / "01_INSTALL_NEW_PC" / "03_INSTALL_PYTHON.bat",
        PROJECT / "01_INSTALL_NEW_PC" / "04_INSTALL_PYTHON_LIBRARIES.bat",
        PROJECT / "01_INSTALL_NEW_PC" / "05_INSTALL_AI_MODELS.bat",
        PROJECT / "01_INSTALL_NEW_PC" / "06_INSTALL_POSTGRESQL.bat",
        PROJECT / "03_TOOLS_DIAGNOSTIC" / "FULL_SYSTEM_DIAGNOSTIC.bat",
        PROJECT / "03_TOOLS_DIAGNOSTIC" / "CHECK_DATABASE.bat",
    ]
    missing = [str(p) for p in required if not p.exists()]
    assert not missing, missing


def test_launcher_uses_v33_bounded_supervisor() -> None:
    launcher = (ROOT / "START_CAMPUSFACE.bat").read_text(encoding="utf-8", errors="ignore").lower()
    assert "postgres_guard.py ensure" in launcher
    assert "postgres_runtime_env.bat" in launcher
    assert "check_postgres.py" in launcher
    assert "setup_postgresql_windows.bat" in launcher
    assert "30-second" in launcher


def test_setup_uses_supervisor_not_pgctl_start_wait() -> None:
    setup = (ROOT / "scripts" / "setup_embedded_postgres.ps1").read_text(encoding="utf-8", errors="ignore").lower()
    guard = (ROOT / "scripts" / "postgres_guard.py").read_text(encoding="utf-8", errors="ignore").lower()
    assert "test-portbindable" in setup
    assert "tcplistener" in setup
    assert "postgres_guard.py') ensure" in setup
    assert '"start"' not in guard or "pgctl" not in guard
    assert "start_postgres_direct" in guard
    assert "start_timeout_seconds = 30" in guard
    assert "postgres.exe" in guard
