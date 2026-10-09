"""Install unchanged production requirements only in an isolated QA venv."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".qa_production" / "offline-venv"
venv.EnvBuilder(with_pip=True).create(ENV)
PYTHON = ENV / "Scripts" / "python.exe"
command = [str(PYTHON), "-m", "pip", "install", "--no-index", "--disable-pip-version-check",
           "--find-links", str(ROOT / "vendor" / "wheels"),
           "-r", str(ROOT / "requirements-runtime.txt"), "-r", str(ROOT / "requirements-media.txt")]
raise SystemExit(subprocess.run(command, cwd=ROOT).returncode)
