from pathlib import Path

from scripts.check_ready import find_external_frontend_dependencies


def test_frontend_has_no_hardcoded_external_runtime_dependencies():
    root = Path(__file__).resolve().parents[1]
    assert find_external_frontend_dependencies(root / "frontend") == []
