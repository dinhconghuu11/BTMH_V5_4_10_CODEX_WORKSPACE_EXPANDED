from pathlib import Path

from scripts.check_ready import find_external_frontend_dependencies


def test_sms_webhook_placeholder_does_not_count_as_frontend_dependency(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        '<input type="url" placeholder="https://sms-provider.example/api/send">',
        encoding="utf-8",
    )
    assert find_external_frontend_dependencies(frontend) == []


def test_actual_external_script_is_blocked(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        '<script src="https://cdn.example.test/app.js"></script>',
        encoding="utf-8",
    )
    result = find_external_frontend_dependencies(frontend)
    assert result and "cdn.example.test" in result[0]


def test_actual_external_stylesheet_is_blocked(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        '<link rel="stylesheet" href="https://fonts.example.test/style.css">',
        encoding="utf-8",
    )
    result = find_external_frontend_dependencies(frontend)
    assert result and "fonts.example.test" in result[0]


def test_external_css_asset_is_blocked(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text('<link rel="stylesheet" href="style.css">', encoding="utf-8")
    (frontend / "style.css").write_text('body{background:url("https://cdn.example.test/bg.jpg")}', encoding="utf-8")
    result = find_external_frontend_dependencies(frontend)
    assert result and "cdn.example.test" in result[0]


def test_external_fetch_is_blocked_but_url_regex_is_not(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "js").mkdir(parents=True)
    (frontend / "index.html").write_text('<script src="js/app.js"></script>', encoding="utf-8")
    (frontend / "js" / "app.js").write_text(
        "const re=/^https?:\\/\\//i; fetch('https://api.example.test/data')",
        encoding="utf-8",
    )
    result = find_external_frontend_dependencies(frontend)
    assert len(result) == 1
    assert "api.example.test" in result[0]


def test_packaged_frontend_has_no_hardcoded_external_runtime_dependency():
    root = Path(__file__).resolve().parents[1]
    assert find_external_frontend_dependencies(root / "frontend") == []
