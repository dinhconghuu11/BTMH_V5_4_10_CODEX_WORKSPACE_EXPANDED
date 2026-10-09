"""Run real batch control flow with isolated service/browser collaborators."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from module_app import mediamtx_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode,allowed", [("development", True), ("production", False)])
def test_readiness_gateway_branch_keeps_production_required(monkeypatch, tmp_path, capsys, mode, allowed):
    # Execute the actual gateway readiness block with unrelated model/database
    # readiness excluded; those prerequisites retain their existing checks.
    tree = ast.parse((ROOT / "scripts" / "check_ready.py").read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    block = next(node for node in main.body if isinstance(node, ast.Try) and any(
        isinstance(child, ast.ImportFrom) and child.module == "module_app.mediamtx_runtime"
        for child in ast.walk(node)))
    monkeypatch.setenv("BTMH_ENV", mode)
    monkeypatch.delenv("BTMH_MEDIAMTX_BIN", raising=False)
    monkeypatch.delenv("BTMH_MEDIAMTX_BINARY", raising=False)
    monkeypatch.setattr(runtime.shutil, "which", lambda _: None)
    monkeypatch.setattr(runtime, "PROJECT_ROOT", tmp_path / "project")
    scope = {"sys": SimpleNamespace(platform="win32"), "DATA_ROOT": tmp_path, "errors": []}
    exec(compile(ast.Module(body=[block], type_ignores=[]), "check_ready.py gateway", "exec"), scope)
    assert bool(scope["errors"]) == (not allowed)
    output = capsys.readouterr().out
    assert "MEDIAMTX_NOT_INSTALLED" in output
    assert ("[WARN]" if allowed else "[ERROR]") in output


@pytest.mark.skipif(os.name != "nt", reason="Windows batch integration")
@pytest.mark.parametrize("mode,present,inherited_mode,expected", [
    ("development", False, "production", 0),
    ("development", False, "development", 0),
    ("production", False, None, 6),
    ("production", False, "development", 6),
    ("production", True, "development", 0),
])
def test_launcher_missing_and_present_media_control_flow(tmp_path, mode, present, inherited_mode, expected):
    harness = tmp_path / "launcher with spaces"
    scripts = harness / "scripts"
    package = harness / "module_app"
    scripts.mkdir(parents=True)
    package.mkdir()
    data_root = tmp_path / "data with spaces"
    data_root.mkdir()
    sentinel = data_root / "existing-data.txt"
    sentinel.write_text("existing runtime data must be preserved", encoding="ascii")
    source = (ROOT / "START_CAMPUSFACE.bat").read_text(encoding="utf-8")
    # Use the actual interpreter; all business services live in this disposable
    # harness. Only browser opening/pause/runtime selection are test substitutions.
    source = source.replace('set "PY=%CAMPUSFACE_DATA_ROOT%\\runtime\\venv\\Scripts\\python.exe"',
                            f'set "PY={sys.executable}"')
    lines = []
    for line in source.splitlines():
        if line.strip() == "pause":
            lines.append("rem pause suppressed in isolated test")
        elif line.startswith('start "" /min cmd /c '):
            lines.append("echo FRONTEND_OPENED")
        else:
            lines.append(line)
    (harness / "START_CAMPUSFACE.bat").write_bytes("\r\n".join(lines).encode("ascii"))
    shutil.copyfile(ROOT / "START_CAMPUSFACE_DEV.bat", harness / "START_CAMPUSFACE_DEV.bat")
    shutil.copyfile(ROOT / "scripts" / "check_mediamtx_runtime.py", scripts / "check_mediamtx_runtime.py")
    shutil.copyfile(ROOT / "scripts" / "resolve_data_root.bat", scripts / "resolve_data_root.bat")
    for name in ("check_standard_user.ps1", "stop_stale_campusface.ps1"):
        (scripts / name).write_text("exit 0\n", encoding="ascii")
    for name in ("apply_pro_r2_config.py", "apply_camera_hd_v5_config.py", "apply_v27_performance_config.py",
                 "apply_v291_realtime_hotfix.py", "check_v28_media_runtime.py", "postgres_guard.py",
                 "check_postgres.py", "check_ready.py"):
        (scripts / name).write_text("raise SystemExit(0)\n", encoding="ascii")
    (harness / "run_module.py").write_text(
        "import os\nprint('BACKEND_STARTED')\n"
        "if os.environ.get('BTMH_OPEN_BROWSER') == '1': print('FRONTEND_OPENED')\n"
        "print('BACKEND_MODE:' + os.environ['BTMH_ENV'])\n"
        "print('BACKEND_DATA_ROOT:' + os.environ['CAMPUSFACE_DATA_ROOT'])\n", encoding="ascii")
    (package / "__init__.py").write_text("", encoding="ascii")
    module = (ROOT / "module_app" / "mediamtx_runtime.py").read_text(encoding="utf-8")
    if present:
        bundle = data_root / "runtime" / "mediamtx"
        bundle.mkdir(parents=True)
        executable = b"inert supported test fixture; never executed"
        (bundle / "mediamtx.exe").write_bytes(executable)
        archive = bundle / runtime.ARCHIVE_NAME
        with zipfile.ZipFile(archive, "w") as payload:
            payload.writestr("mediamtx.exe", executable)
        module = module.replace(runtime.ARCHIVE_SHA256, hashlib.sha256(archive.read_bytes()).hexdigest())
    (package / "mediamtx_runtime.py").write_text(module, encoding="utf-8")
    env = os.environ.copy()
    env.update(CAMPUSFACE_DATA_ROOT=str(data_root), PYTHONUTF8="1")
    if inherited_mode is None:
        env.pop("BTMH_ENV", None)
    else:
        env["BTMH_ENV"] = inherited_mode
    for name in ("BTMH_MEDIAMTX_BIN", "BTMH_MEDIAMTX_BINARY", "BTMH_DEV_PYTHON", "PG_SETUP_RC", "PG_RC"):
        env.pop(name, None)
    launcher = "START_CAMPUSFACE_DEV.bat" if mode == "development" else "START_CAMPUSFACE.bat"
    caller = tmp_path / "unrelated terminal directory"
    caller.mkdir()
    proc = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(harness / launcher)],
                          cwd=caller, env=env, capture_output=True, text=True, timeout=45)
    assert proc.returncode == expected, proc.stdout + proc.stderr
    assert ("BACKEND_STARTED" in proc.stdout) == (expected == 0)
    assert ("FRONTEND_OPENED" in proc.stdout) == (expected == 0)
    assert proc.stdout.count(f"[MODE] {mode.upper()}") == 1
    assert sentinel.read_text(encoding="ascii") == "existing runtime data must be preserved"
    if expected == 0:
        assert f"BACKEND_MODE:{mode}" in proc.stdout
        assert f"BACKEND_DATA_ROOT:{data_root}" in proc.stdout
    if mode == "development":
        assert "[WARN] Native MediaMTX unavailable: MEDIAMTX_NOT_INSTALLED" in proc.stdout
        assert "[INFO] Development fallback transport enabled" in proc.stdout
        assert "Production requires" not in proc.stdout
    if not present:
        assert "MEDIAMTX_NOT_INSTALLED" in proc.stdout
        assert ("[WARN] Native MediaMTX unavailable" if mode == "development" else "[ERROR]") in proc.stdout
    else:
        assert "Native WebRTC remains the primary transport" in proc.stdout


def test_vscode_modes_and_easy_install_are_explicit():
    tasks = json.loads((ROOT.parents[1] / ".vscode" / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    development = next(task for task in tasks if task["label"] == "BTMH: Start Development")
    production = next(task for task in tasks if task["label"] == "BTMH: Start Windows")
    assert development["type"] == "process"
    assert development["command"] == "cmd.exe"
    assert development["args"] == ["/d", "/c", "START_CAMPUSFACE_DEV.bat"]
    assert development["options"]["cwd"] == "${workspaceFolder}/PROJECT/BTMH_SYSTEM"
    assert development["options"]["env"]["BTMH_ENV"] == "development"
    assert production["options"]["env"]["BTMH_ENV"] == "production"
    installer = (ROOT / "INSTALL_CURRENT_PC_WINDOWS.bat").read_text(encoding="utf-8")
    assert 'set "BTMH_ENV=production"' in installer
    assert "ensure_mediamtx_v5410.ps1" in installer
    launcher = (ROOT / "START_CAMPUSFACE.bat").read_text(encoding="utf-8")
    assert 'if /i "%BTMH_ENV%"=="development" if defined BTMH_DEV_PYTHON' in launcher
