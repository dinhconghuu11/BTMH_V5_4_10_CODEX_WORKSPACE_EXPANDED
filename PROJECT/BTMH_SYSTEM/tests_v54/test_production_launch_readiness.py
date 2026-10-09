"""Isolated launcher/readiness behavior; no customer DB, ports or hardware."""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP = ROOT / ".pytest_production_launch_20261009"


def isolated_directory(prefix):
    TEST_TEMP.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=TEST_TEMP)


def load_script(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProductionReadinessTests(unittest.TestCase):
    def run_readiness(self, *, environment="production", pad=True, ffmpeg=True,
                      db_mode="postgres", camera_mode="service", preview=False):
        ready = load_script("scripts/check_ready.py", "isolated_check_ready")
        with isolated_directory("btmh-ready-") as directory:
            root = Path(directory)
            yunet = root / "yunet.onnx"
            yunet.write_bytes(b"0" * 100001)
            sface = root / "sface.onnx"
            sface.write_bytes(b"0" * 1000001)
            calls = []
            config = types.ModuleType("module_app.config")
            values = dict(APP_VERSION="fixture", CAMERA_BACKEND="native",
                          CAMERA_SOURCE="rtsp://operator:FakeSecret@camera.invalid/101",
                          CAMERA_MODE=camera_mode, DATA_ROOT=root, PROFILE="MAX",
                          SFACE_MODEL=sface, DB_MODE=db_mode, POSTGRES_HOST="127.0.0.1",
                          POSTGRES_PORT=55442, POSTGRES_DB="fixture", YUNET_MODEL=yunet,
                          PAD_MODEL_V2=root / "pad.onnx")
            config.__dict__.update(values)
            fake = {name: types.ModuleType(name) for name in (
                "fastapi", "uvicorn", "cv2", "numpy", "cryptography", "mediapipe", "psycopg", "websockets")}
            fake["module_app.config"] = config
            fake["module_app.db"] = types.SimpleNamespace(
                init_db=lambda: calls.append("database-init"), db_status=lambda: {"mode": db_mode})
            fake["module_app.face_core"] = types.SimpleNamespace(CORE=types.SimpleNamespace(ensure=lambda: None))
            fake["module_app.passive_pad"] = types.SimpleNamespace(PAD=types.SimpleNamespace(
                status=lambda: {"ready": pad, "enabled": pad}))
            fake["module_app.rtsp_native_v545"] = types.SimpleNamespace(resolve_ffmpeg=lambda: "ffmpeg.exe" if ffmpeg else None)
            fake["module_app.camera"] = types.SimpleNamespace(CAMERA=types.SimpleNamespace(
                latest_observation_jpeg=lambda: None, latest_result=lambda: None))
            # Gateway validation has separate pinned-provenance integration tests.
            fake["module_app.mediamtx_runtime"] = types.SimpleNamespace(
                VERSION="1.21.1", require_mediamtx=lambda _: types.SimpleNamespace(binary=root / "mediamtx.exe"))
            output = io.StringIO()
            with patch.dict(sys.modules, fake), patch.dict(os.environ, {
                "BTMH_ENV": environment, "BTMH_UI_PREVIEW": "1" if preview else "0"}), \
                    patch.object(ready, "find_external_frontend_dependencies", return_value=[]), \
                    contextlib.redirect_stdout(output):
                result = ready.main()
            return result, output.getvalue(), calls

    def test_production_preflight_success_is_not_hardware_ready_claim(self):
        code, output, calls = self.run_readiness()
        self.assertEqual(code, 0, output)
        self.assertIn("Backend startup and socket binding still follow", output)
        self.assertIn("database-init", calls)
        self.assertNotIn("FakeSecret", output)
        self.assertNotIn("rtsp://", output)

    def test_missing_or_disabled_pad_blocks_production(self):
        code, output, _ = self.run_readiness(pad=False)
        self.assertEqual(code, 2)
        self.assertIn("[ERROR] Passive PAD is not ready", output)
        self.assertNotIn("Runtime preflight passed", output)

    def test_explicit_development_retains_visible_pad_fallback(self):
        code, output, _ = self.run_readiness(environment="development", pad=False)
        self.assertEqual(code, 0, output)
        self.assertIn("[WARN] Passive PAD", output)

    def test_missing_ffmpeg_blocks_production(self):
        code, output, _ = self.run_readiness(ffmpeg=False)
        self.assertEqual(code, 2)
        self.assertIn("[ERROR] FFmpeg runtime", output)

    def test_production_sqlite_rejected_without_initializing_wrong_database(self):
        code, output, calls = self.run_readiness(db_mode="sqlite")
        self.assertEqual(code, 2)
        self.assertIn("Production requires PostgreSQL", output)
        self.assertNotIn("database-init", calls)

    def test_non_service_camera_mode_blocks_production(self):
        code, output, _ = self.run_readiness(camera_mode="browser")
        self.assertEqual(code, 2)
        self.assertIn("background camera service mode", output)

    def test_ui_preview_never_passes_production_preflight(self):
        code, output, calls = self.run_readiness(preview=True)
        self.assertEqual(code, 2)
        self.assertIn("UI_PREVIEW is not a production runtime", output)
        self.assertEqual(calls, [])


class BackendStartupTests(unittest.TestCase):
    def run_backend(self, *, started, open_browser=True):
        runner = load_script("run_module.py", "isolated_run_module")
        calls = []

        class FakeServer:
            def __init__(self, config):
                self.started = False

            async def startup(self, sockets=None):
                calls.append("lifespan-and-bind")
                self.started = started

            def run(self):
                asyncio.run(self.startup())

        fake = {
            "uvicorn": types.SimpleNamespace(Server=FakeServer, Config=lambda *a, **k: k),
            "module_app.config": types.SimpleNamespace(HOST="0.0.0.0", PORT=8123),
            "webbrowser": types.SimpleNamespace(open=lambda url: calls.append(("browser", url)) or True),
        }
        output = io.StringIO()
        with patch.dict(sys.modules, fake), patch.dict(os.environ, {"BTMH_OPEN_BROWSER": "1" if open_browser else "0"}), \
                patch.object(runner, "_postgres_preflight", side_effect=lambda: calls.append("postgres-preflight")), \
                patch.object(runner, "_websocket_mode", return_value="auto"), contextlib.redirect_stdout(output):
            result = runner.main()
        return result, output.getvalue(), calls

    def test_browser_opens_only_after_lifespan_and_bind(self):
        code, output, calls = self.run_backend(started=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["postgres-preflight", "lifespan-and-bind", ("browser", "http://127.0.0.1:8123/")])
        self.assertIn("[WEB_READY]", output)

    def test_failed_startup_is_nonzero_without_browser_or_success_message(self):
        code, output, calls = self.run_backend(started=False)
        self.assertEqual(code, 3)
        self.assertNotIn("[WEB_READY]", output)
        self.assertEqual(calls, ["postgres-preflight", "lifespan-and-bind"])

    def test_direct_backend_run_does_not_launch_browser(self):
        code, output, calls = self.run_backend(started=True, open_browser=False)
        self.assertEqual(code, 0)
        self.assertIn("[WEB_READY]", output)
        self.assertEqual(calls, ["postgres-preflight", "lifespan-and-bind"])

    def test_ipv6_url_is_a_valid_browser_destination(self):
        runner = load_script("run_module.py", "isolated_run_module")
        self.assertEqual(runner._web_url("::1", 8100), "http://[::1]:8100/")

    def test_inherited_preview_is_rejected_before_postgres_preflight(self):
        runner = load_script("run_module.py", "isolated_run_module")
        with patch.dict(os.environ, {"BTMH_UI_PREVIEW": "1"}), \
                patch.object(runner, "_postgres_preflight", side_effect=AssertionError("production mutation")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main(), 7)
        self.assertIn("UI_PREVIEW cannot use", output.getvalue())


@unittest.skipUnless(os.name == "nt", "Windows batch integration")
class PostgresRepairLauncherTests(unittest.TestCase):
    def run_launcher(self, *, first_rc, second_rc=0, setup_rc=0):
        with isolated_directory("btmh-launch-") as directory:
            harness = Path(directory) / "launcher with spaces"
            scripts = harness / "scripts"
            scripts.mkdir(parents=True)
            data = Path(directory) / "isolated data"
            data.mkdir()
            sentinel = data / "retain.txt"
            sentinel.write_text("preserve", encoding="ascii")
            source = (ROOT / "START_CAMPUSFACE.bat").read_text(encoding="utf-8")
            source = source.replace('set "PY=%CAMPUSFACE_DATA_ROOT%\\runtime\\venv\\Scripts\\python.exe"',
                                    f'set "PY={sys.executable}"')
            source = "\r\n".join("rem pause suppressed" if line.strip() == "pause" else line
                                     for line in source.splitlines())
            (harness / "START_CAMPUSFACE.bat").write_bytes(source.encode("ascii"))
            shutil.copyfile(ROOT / "scripts" / "resolve_data_root.bat", scripts / "resolve_data_root.bat")
            for name in ("check_standard_user.ps1", "stop_stale_campusface.ps1"):
                (scripts / name).write_text("exit 0\n", encoding="ascii")
            for name in ("apply_pro_r2_config.py", "apply_camera_hd_v5_config.py", "apply_v27_performance_config.py",
                         "apply_v291_realtime_hotfix.py", "check_v28_media_runtime.py", "check_mediamtx_runtime.py",
                         "check_postgres.py", "check_ready.py"):
                (scripts / name).write_text("raise SystemExit(0)\n", encoding="ascii")
            (scripts / "postgres_guard.py").write_text(
                "import os\nfrom pathlib import Path\np=Path(os.environ['CAMPUSFACE_DATA_ROOT'])/'guard-count'\n"
                "n=int(p.read_text()) if p.exists() else 0\np.write_text(str(n+1))\n"
                f"raise SystemExit({first_rc} if n == 0 else {second_rc})\n", encoding="ascii")
            (harness / "SETUP_POSTGRESQL_WINDOWS.bat").write_text(
                f"@echo off\necho SETUP_EXECUTED\nexit /b {setup_rc}\n", encoding="ascii")
            (harness / "run_module.py").write_text("print('BACKEND_STARTED')\n", encoding="ascii")
            env = os.environ.copy()
            env.update(CAMPUSFACE_DATA_ROOT=str(data), PYTHONUTF8="1")
            for key in ("PG_RC", "PG_SETUP_RC", "BTMH_DEV_PYTHON"):
                env.pop(key, None)
            process = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                                      str(harness / "START_CAMPUSFACE.bat")], cwd=directory, env=env,
                                     capture_output=True, text=True, timeout=45)
            self.assertEqual(sentinel.read_text(encoding="ascii"), "preserve")
            return process

    def test_successful_repair_uses_current_retry_return_code(self):
        process = self.run_launcher(first_rc=1)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("SETUP_EXECUTED", process.stdout)
        self.assertIn("BACKEND_STARTED", process.stdout)
        self.assertNotIn("HE THONG DA KHOI DONG", process.stdout)

    def test_failed_setup_never_starts_backend(self):
        process = self.run_launcher(first_rc=1, setup_rc=4)
        self.assertEqual(process.returncode, 4, process.stdout + process.stderr)
        self.assertNotIn("BACKEND_STARTED", process.stdout)

    def test_failed_retry_never_starts_backend(self):
        process = self.run_launcher(first_rc=1, second_rc=4)
        self.assertEqual(process.returncode, 4, process.stdout + process.stderr)
        self.assertNotIn("BACKEND_STARTED", process.stdout)

    def test_inherited_preview_rejected_before_any_launcher_collaborator(self):
        env = os.environ.copy()
        env["BTMH_UI_PREVIEW"] = "1"
        process = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                                  str(ROOT / "START_CAMPUSFACE.bat")], cwd=ROOT, env=env,
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 7, process.stdout + process.stderr)
        self.assertIn("UI_PREVIEW cannot use", process.stdout)
        self.assertNotIn("[MODE]", process.stdout)


if __name__ == "__main__":
    unittest.main()
