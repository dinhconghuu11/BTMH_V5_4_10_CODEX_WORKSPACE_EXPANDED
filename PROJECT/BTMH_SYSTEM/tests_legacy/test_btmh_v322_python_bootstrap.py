from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "01_INSTALL_NEW_PC" / "03_INSTALL_PYTHON.bat"


def test_python_bootstrap_reuses_existing_python312():
    text = SCRIPT.read_text(encoding="utf-8", errors="ignore").lower()
    assert "py -3.12" in text
    assert "find_python312.ps1" in text
    assert "-m venv" in text
    assert "installallusers=0" in text
    assert "/norestart" in text
    assert "python_install.log" in text
