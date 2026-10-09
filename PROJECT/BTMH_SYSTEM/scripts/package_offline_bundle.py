"""Build a clean ZIP or Inno staging directory after the offline audit passes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

from validate_portable_bundle import ROOT, audit, digest

FOLDERS = {"module_app", "frontend", "scripts", "vendor", "models", "config", "enterprise_camera_manager_v18_5", "vendor_py"}
EXCLUDED = {"__pycache__", ".pytest_cache", ".qa_preview_v550", ".git", "output"}
SENSITIVE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".key", ".log", ".cfacebak", ".pyc", ".pyo", ".dpapi", ".env", ".pem", ".pfx", ".p12", ".kdbx"}


def release_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if len(rel.parts) > 1 and rel.parts[0] not in FOLDERS:
            continue
        if any(part in EXCLUDED or part.startswith((".pytest", ".qa_", ".btmh", ".offline-audit-test-")) for part in rel.parts):
            continue
        if path.name in {"module.env", "offline-bundle-manifest.json", ".env"} or (path.name.startswith(".env.") and not path.name.endswith(".example")) or path.suffix.lower() in SENSITIVE_SUFFIXES:
            continue
        if len(rel.parts) == 1 and (path.name.startswith(("TEST_REPORT", "CHANGELOG", "run_ui_preview", "START_BTMH_UI_PREVIEW")) or path.suffix not in {".py", ".bat", ".txt", ".md", ".example", ""}):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("release contains a symbolic link or junction")
        yield path


def create_stage(root: Path, stage: Path, result: dict):
    # Never recursively remove an old stage: every build gets a fresh directory.
    if stage.exists():
        raise ValueError("output stage already exists; use a fresh output path")
    stage.mkdir(parents=True)
    manifest = {"schema": 1, "product": "BTMH", "version": "5.4.10", "dependency_resolution": result["dependency_resolution"], "files": []}
    for source in release_files(root):
        rel = source.relative_to(root)
        destination = stage / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest["files"].append({"path": rel.as_posix(), "size": destination.stat().st_size, "sha256": digest(destination)})
    (stage / "vendor/offline-bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--zip", dest="archive", type=Path)
    args = parser.parse_args()
    result = audit(ROOT)
    if result["issues"]:
        print("[BLOCKED] Payload audit failed; no installer or release ZIP was built.")
        for issue in result["issues"]:
            print("[BLOCKED] " + issue)
        return 2
    if args.archive and args.archive.exists():
        print("[BLOCKED] Output ZIP exists; use a fresh output path.")
        return 3
    create_stage(ROOT, args.stage.resolve(), result)
    if args.archive:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.archive, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for path in sorted(args.stage.rglob("*")):
                if path.is_file():
                    archive.write(path, args.stage.name + "/" + path.relative_to(args.stage).as_posix())
        args.archive.with_suffix(args.archive.suffix + ".sha256").write_text(digest(args.archive) + "\n", encoding="ascii")
        print("[OK] Offline ZIP created with integrity inventory; hardware acceptance remains separate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
