"""Execute actual frontend media ownership/fallback behavior with Node adapters."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_browser_media_lifecycle():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for browser controller behavioral checks")
    result = subprocess.run(
        [node, "--test", str(ROOT / "tests_browser" / "media_lifecycle.test.cjs")],
        cwd=ROOT, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
