from pathlib import Path
import ast

CORE = Path(__file__).resolve().parents[1]
PROJECT = CORE.parents[1]


def test_v33_supervisor_is_syntax_valid_and_direct_start():
    path = CORE / "scripts" / "postgres_guard.py"
    text = path.read_text(encoding="utf-8")
    ast.parse(text)
    assert "START_TIMEOUT_SECONDS = 30" in text
    assert "subprocess.Popen" in text
    assert '"postgres.exe"' in text
    assert "capture_output=capture" not in text
    assert "start_postgres_direct" in text
    assert 'choices=("ensure", "status", "stop")' in text


def test_v33_customer_package_contract():
    assert (PROJECT / "00_READ_ME_FIRST.txt").exists()
    assert (PROJECT / "INSTALL_AND_START_NEW_PC.bat").exists()
    assert (PROJECT / "01_INSTALL_NEW_PC" / "OFFLINE_CACHE" / "README.txt").exists()
    assert (PROJECT / "03_TOOLS_DIAGNOSTIC" / "FULL_SYSTEM_DIAGNOSTIC.bat").exists()
    version = (PROJECT / "VERSION.txt").read_text(encoding="utf-8")
    assert "V3.3.0-windows-stable" in version


def test_v33_setup_no_pgctl_start_wait_path():
    setup = (CORE / "scripts" / "setup_embedded_postgres.ps1").read_text(encoding="utf-8", errors="ignore").lower()
    assert "pg_ctl.exe') -d" not in setup
    assert "pgctl start" not in setup
    assert "starting via v3.3 bounded supervisor" in setup


def test_v33_installer_has_offline_split_folders():
    base = PROJECT / "01_INSTALL_NEW_PC" / "OFFLINE_CACHE"
    for name in ("01_Python", "02_VC_Runtime", "03_PostgreSQL", "04_Python_Wheels", "05_AI_Models"):
        assert (base / name / "README.txt").exists()
