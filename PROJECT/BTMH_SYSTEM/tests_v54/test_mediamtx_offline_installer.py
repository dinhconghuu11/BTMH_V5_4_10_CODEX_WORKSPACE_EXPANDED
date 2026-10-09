"""Exercise the offline PowerShell installer without Internet or executable code.

The success fixture changes the pin in an isolated *test copy* of the installer.
The shipped installer always retains the official release pin and has no bypass
parameter. An authentic pinned release ZIP is not required for these tests.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_mediamtx_offline.ps1"
PIN = "faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23"
ARCHIVE_NAME = "mediamtx_v1.21.1_windows_amd64.zip"
FAKE_EXE = b"Offline installer test fixture: never executable, never run."
POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt" or not POWERSHELL,
    reason="Offline installer integration requires Windows PowerShell.",
)


def make_archive(tmp_path: Path, extra=(), *, with_exe=True) -> Path:
    archive = tmp_path / "local-release.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        if with_exe:
            zip_file.writestr("mediamtx.exe", FAKE_EXE)
        zip_file.writestr("mediamtx.yml", b"# verified release configuration\n")
        for name, value in extra:
            zip_file.writestr(name, value)
    return archive


def fixture_installer(tmp_path: Path, archive: Path) -> Path:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    source = INSTALLER.read_text(encoding="utf-8")
    assert source.count(PIN) == 1
    script = tmp_path / "fixture-install-offline.ps1"
    script.write_text(source.replace(PIN, digest), encoding="utf-8")
    return script


def run_installer(script: Path, archive: Path, data_root: Path):
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-ZipPath",
            str(archive),
            "-DataRoot",
            str(data_root),
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=45,
    )


def assert_no_temporary_install(data_root: Path):
    runtime = data_root / "runtime"
    if runtime.exists():
        assert not list(runtime.glob(".mediamtx-stage-*"))
        assert not list(runtime.glob(".mediamtx-backup-*"))


def test_shipped_installer_has_fixed_official_pin_and_no_network_or_execution():
    source = INSTALLER.read_text(encoding="utf-8")
    assert PIN in source
    assert "'1.21.1'" in source
    assert "ExpectedSHA256" not in source.split(")", 1)[0]
    for forbidden in (
        "Invoke-WebRequest", "Invoke-RestMethod", "Start-BitsTransfer",
        "DownloadFile", "Start-Process", "--version", "System.Net",
    ):
        assert forbidden not in source
    ensure = (ROOT / "scripts" / "ensure_mediamtx_v5410.ps1").read_text(encoding="utf-8-sig")
    assert "install_mediamtx_offline.ps1" in ensure
    assert PIN in ensure


@WINDOWS_ONLY
def test_offline_installer_fixture_correct_hash_installs_without_running_binary(tmp_path):
    archive = make_archive(tmp_path)
    script = fixture_installer(tmp_path, archive)
    data_root = tmp_path / "CampusFace"
    result = run_installer(script, archive, data_root)
    assert result.returncode == 0, result.stdout + result.stderr
    installed = data_root / "runtime" / "mediamtx"
    assert (installed / "mediamtx.exe").read_bytes() == FAKE_EXE
    assert (installed / ARCHIVE_NAME).read_bytes() == archive.read_bytes()
    assert (installed / "VERSION.txt").read_text().strip() == "1.21.1"
    notice = (installed / "THIRD_PARTY_NOTICE.txt").read_text()
    assert "License: MIT" in notice
    assert "https://github.com/bluenviron/mediamtx" in notice
    receipt = json.loads((installed / "INSTALL_RECEIPT.json").read_text())
    assert receipt == {
        "version": "1.21.1",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "executable_sha256": hashlib.sha256(FAKE_EXE).hexdigest(),
    }
    assert "Binary was not executed" in result.stdout
    assert_no_temporary_install(data_root)


@WINDOWS_ONLY
def test_offline_installer_shipped_pin_rejects_wrong_hash_and_preserves_runtime(tmp_path):
    archive = make_archive(tmp_path)
    data_root = tmp_path / "CampusFace"
    installed = data_root / "runtime" / "mediamtx"
    installed.mkdir(parents=True)
    existing = installed / "mediamtx.exe"
    existing.write_bytes(b"existing runtime must remain untouched")
    result = run_installer(INSTALLER, archive, data_root)
    assert result.returncode != 0
    assert "SHA256_MISMATCH" in result.stdout + result.stderr
    assert existing.read_bytes() == b"existing runtime must remain untouched"
    assert not (installed / "VERSION.txt").exists()
    assert_no_temporary_install(data_root)


@WINDOWS_ONLY
def test_offline_installer_missing_file(tmp_path):
    data_root = tmp_path / "CampusFace"
    result = run_installer(INSTALLER, tmp_path / "missing.zip", data_root)
    assert result.returncode != 0
    assert "ZIP_NOT_FOUND" in result.stdout + result.stderr
    assert not data_root.exists()


@WINDOWS_ONLY
@pytest.mark.parametrize("name", ["../escaped.txt", "..\\escaped.txt", "/escaped.txt", "C:/escaped.txt", "file.txt:stream", "NUL.txt", "dir./file.txt"])
def test_offline_installer_rejects_unsafe_zip_paths(tmp_path, name):
    archive = make_archive(tmp_path, [(name, b"unsafe")])
    script = fixture_installer(tmp_path, archive)
    data_root = tmp_path / "CampusFace"
    result = run_installer(script, archive, data_root)
    assert result.returncode != 0
    assert "UNSAFE_ZIP_ENTRY" in result.stdout + result.stderr
    assert not (data_root / "runtime" / "mediamtx").exists()
    assert not (tmp_path / "escaped.txt").exists()
    assert_no_temporary_install(data_root)


@WINDOWS_ONLY
def test_offline_installer_rejects_case_insensitive_duplicate(tmp_path):
    archive = make_archive(tmp_path, [("MEDIAMTX.EXE", b"duplicate")])
    script = fixture_installer(tmp_path, archive)
    data_root = tmp_path / "CampusFace"
    result = run_installer(script, archive, data_root)
    assert result.returncode != 0
    assert "DUPLICATE_ZIP_ENTRY" in result.stdout + result.stderr
    assert_no_temporary_install(data_root)


@WINDOWS_ONLY
@pytest.mark.parametrize("attributes", [(0o120777 << 16), 0x400])
def test_offline_installer_rejects_symlink_and_reparse_entries(tmp_path, attributes):
    entry = zipfile.ZipInfo("unsafe-link")
    entry.create_system = 3
    entry.external_attr = attributes
    archive = make_archive(tmp_path, [(entry, b"../outside")])
    script = fixture_installer(tmp_path, archive)
    data_root = tmp_path / "CampusFace"
    result = run_installer(script, archive, data_root)
    assert result.returncode != 0
    assert "UNSAFE_ZIP_ENTRY" in result.stdout + result.stderr
    assert_no_temporary_install(data_root)


@WINDOWS_ONLY
def test_offline_installer_rejects_missing_exe(tmp_path):
    archive = make_archive(tmp_path, with_exe=False)
    script = fixture_installer(tmp_path, archive)
    data_root = tmp_path / "CampusFace"
    result = run_installer(script, archive, data_root)
    assert result.returncode != 0
    assert "MEDIAMTX_EXE_MISSING" in result.stdout + result.stderr
    assert_no_temporary_install(data_root)


@WINDOWS_ONLY
def test_offline_installer_errors_do_not_leak_archive_credentials(tmp_path):
    credential = "camera-owner:never-log-password"
    archive = make_archive(tmp_path, [("rtsp://" + credential + "@camera/stream", b"unsafe")])
    script = fixture_installer(tmp_path, archive)
    result = run_installer(script, archive, tmp_path / "CampusFace")
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "UNSAFE_ZIP_ENTRY" in output
    assert credential not in output
    assert "never-log-password" not in output


@WINDOWS_ONLY
def test_offline_installer_can_reinstall_from_its_retained_verified_archive(tmp_path):
    archive = make_archive(tmp_path)
    script = fixture_installer(tmp_path, archive)
    data_root = tmp_path / "CampusFace"
    first = run_installer(script, archive, data_root)
    assert first.returncode == 0, first.stdout + first.stderr
    retained = data_root / "runtime" / "mediamtx" / ARCHIVE_NAME
    second = run_installer(script, retained, data_root)
    assert second.returncode == 0, second.stdout + second.stderr
    assert retained.read_bytes() == archive.read_bytes()
    assert (retained.parent / "mediamtx.exe").read_bytes() == FAKE_EXE
    assert_no_temporary_install(data_root)
