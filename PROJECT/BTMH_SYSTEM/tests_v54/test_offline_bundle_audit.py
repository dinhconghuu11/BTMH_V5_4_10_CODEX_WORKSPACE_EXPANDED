"""Offline package rejection and staging tests; no real binary is executed."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_portable_bundle as bundle
import package_offline_bundle as package


class OfflineBundleAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix=".offline-audit-test-")
        self.root = Path(self.tmp.name)
        (self.root / "frontend").mkdir()
        (self.root / "frontend/index.html").write_text('<img src="logo.svg">', encoding="utf-8")
        (self.root / "frontend/logo.svg").write_text("<svg/>", encoding="utf-8")
        (self.root / "requirements-runtime.txt").write_text("imageio-ffmpeg==0.6.0\n", encoding="utf-8")
        (self.root / "requirements-media.txt").write_text("aiortc==1.15.0\n", encoding="utf-8")
        (self.root / "vendor/wheels").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def audit(self):
        return bundle.audit(self.root, resolve=False)

    def wheel(self, name="aiortc", version="1.15.0", tag="py3-none-any", extra=(), dependencies=()):
        path = self.root / "vendor/wheels" / f"{name}-{version}-{tag}.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{name}-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n" + "".join(f"Requires-Dist: {dependency}\n" for dependency in dependencies))
            archive.writestr(f"{name}-{version}.dist-info/WHEEL", f"Wheel-Version: 1.0\nTag: {tag}\n")
            archive.writestr(f"{name}-{version}.dist-info/licenses/LICENSE.txt", "Test fixture license, not a distributable package.")
            for key, data in extra:
                archive.writestr(key, data)
        return path

    def test_missing_payload_never_claims_bundle_complete(self):
        result = self.audit()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(len(result["artifacts"]), 6)
        self.assertIn("PINNED_WHEEL_MISSING: aiortc==1.15.0", result["issues"])
        self.assertEqual(result["hardware_acceptance"], "NOT_RUN")

    def test_many_unrelated_wheels_do_not_satisfy_pinned_packages(self):
        for n in range(12):
            self.wheel(name=f"fixture{n}")
        result = self.audit()
        self.assertIn("PINNED_WHEEL_MISSING: aiortc==1.15.0", result["issues"])

    def test_pinned_name_with_wrong_version_is_rejected(self):
        self.wheel(version="0.0.0")
        self.assertIn("PINNED_WHEEL_MISSING: aiortc==1.15.0", self.audit()["issues"])

    def test_non_windows_wheel_is_rejected(self):
        path = self.wheel(tag="cp312-cp312-manylinux_2_17_x86_64")
        self.assertIn(f"INVALID_WHEEL: {path.name}", self.audit()["issues"])

    def test_direct_remote_wheel_dependency_refuses_resolver_network(self):
        self.wheel(dependencies=["unsafe @ https://example.test/unsafe.whl"])
        with patch.object(bundle.subprocess, "run") as run:
            result = bundle.audit(self.root, resolve=True)
        run.assert_not_called()
        self.assertIn("OFFLINE_DEPENDENCY_CLOSURE_REFUSED: remote wheel dependency", result["issues"])

    def test_ffmpeg_wheel_requires_actual_x64_pe(self):
        self.wheel(name="imageio_ffmpeg", version="0.6.0", tag="py3-none-win_amd64", extra=[("imageio_ffmpeg/binaries/ffmpeg.exe", b"fixture never executed")])
        self.assertIn("FFMPEG_WINDOWS_X64_BINARY_MISSING", self.audit()["issues"])

    def test_zip_path_traversal_is_rejected(self):
        path = self.wheel(extra=[("../escape.py", b"not executed")])
        self.assertIn(f"INVALID_WHEEL: {path.name}", self.audit()["issues"])
        self.assertFalse((self.root.parent / "escape.py").exists())

    def test_remote_asset_blocks_offline_frontend(self):
        (self.root / "frontend/index.html").write_text('<script src="https://cdn.example.test/app.js"></script>', encoding="utf-8")
        self.assertIn("REMOTE_FRONTEND_ASSET: offline production must use local assets", self.audit()["issues"])

    def test_fastapi_static_mount_resolves_to_local_frontend(self):
        (self.root / "frontend/index.html").write_text('<img src="/static/logo.svg?v=5410">', encoding="utf-8")
        self.assertFalse(any(issue.startswith("FRONTEND_ASSET_MISSING") for issue in self.audit()["issues"]))

    def test_pg_sidecar_is_mandatory_even_before_archive_import(self):
        self.assertIn("POSTGRESQL_ACQUISITION_CHECKSUM_MISSING: vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip.sha256", self.audit()["issues"])

    def test_size_only_fake_model_is_not_accepted(self):
        (self.root / "models").mkdir()
        (self.root / "models/minifasnet_v2.onnx").write_bytes(b"fixture" * 15000)
        self.assertIn("UPSTREAM_HASH_MISMATCH_OR_UNKNOWN: models/minifasnet_v2.onnx", self.audit()["issues"])

    def test_clean_stage_excludes_runtime_secrets_fixtures_and_old_manifest(self):
        for relative in ("module.env", ".env", "config/.env.production", "data/customer.db", "backups/checkpoint.zip", ".pytest_runtime/customer.db", ".qa_production/offline-venv/secret", "config/customer.dpapi", "config/camera.env", "config/key.pem", "config/cert.pfx", "frontend/.qa_preview_v550/screenshot.png", "module_app/__pycache__/main.pyc", "vendor/offline-bundle-manifest.json"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"private fixture")
        (self.root / "module_app/main.py").write_text("# product source", encoding="utf-8")
        names = {p.relative_to(self.root).as_posix() for p in package.release_files(self.root)}
        self.assertIn("module_app/main.py", names)
        self.assertIn("frontend/logo.svg", names)
        self.assertFalse(any("customer" in name or "checkpoint" in name or "screenshot" in name or "manifest" in name or name.endswith((".env", ".pem", ".pfx")) for name in names))
        self.assertNotIn("config/.env.production", names)

    def test_safe_path_rejects_drive_and_parent_escape(self):
        for relative in ("../escape", "C:/escape", "/escape"):
            with self.assertRaises(ValueError):
                bundle.safe_path(self.root, relative)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell required")
    def test_pre_python_verifier_rejects_modified_payload_without_running_it(self):
        payload = self.root / "frontend/index.html"
        manifest = {"schema": 1, "product": "BTMH", "version": "5.4.10", "dependency_resolution": "PASS", "files": [{"path": "frontend/index.html", "size": payload.stat().st_size, "sha256": "0" * 64}]}
        (self.root / "vendor/offline-bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/verify_offline_bundle.ps1"), "-Root", str(self.root)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("OFFLINE_PAYLOAD_HASH_MISMATCH", result.stdout)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell required")
    def test_verifier_rejects_unlisted_wheel_before_binary_execution(self):
        required = ['vendor/python-3.12.10-amd64.exe', 'vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip', 'vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip.sha256', 'vendor/mediamtx/mediamtx_v1.21.1_windows_amd64.zip', 'models/face_detection_yunet_2023mar.onnx', 'models/face_recognition_sface_2021dec.onnx', 'models/minifasnet_v2.onnx', 'requirements-runtime.txt', 'requirements-media.txt', 'frontend/index.html', 'scripts/validate_portable_bundle.py']
        manifest = {"schema": 1, "product": "BTMH", "version": "5.4.10", "dependency_resolution": "PASS", "files": []}
        for relative in required:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(b"fixture never executable")
        for path in self.root.rglob("*"):
            if path.is_file():
                manifest["files"].append({"path": path.relative_to(self.root).as_posix(), "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        self.wheel()  # Deliberately added after the integrity inventory.
        (self.root / "vendor/offline-bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/verify_offline_bundle.ps1"), "-Root", str(self.root)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("OFFLINE_UNLISTED_PAYLOAD", result.stdout)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell required")
    def test_upgrade_guard_refuses_current_live_interpreter_without_killing_it(self):
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/assert_install_stopped.ps1"), "-InstallRoot", str(Path(sys.executable).parent), "-DataRoot", str(self.root)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 21, result.stdout + result.stderr)
        self.assertIn("ACTIVE_BTMH_RUNTIME", result.stdout)


if __name__ == "__main__":
    unittest.main()
