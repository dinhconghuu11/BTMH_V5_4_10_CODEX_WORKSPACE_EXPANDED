"""Opt-in test migration. Pass an explicit isolated profile; default is dry-run."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, help="Isolated tests/<name> profile")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--mapping", type=Path, help="Reviewed JSON array of store_id/zone_name/camera_ids")
    args = parser.parse_args()
    if not args.profile.startswith("tests/") or any(part in {".", "..", ""} for part in args.profile.replace("\\", "/").split("/")):
        parser.error("Use a named tests/<name> profile; operational roots are not accepted")
    from module_app.ui_preview import prepare_environment
    prepare_environment(profile=args.profile)
    from module_app.catalog_migration import dry_run, apply_mapping
    groups = json.loads(args.mapping.read_text(encoding="utf-8-sig")) if args.mapping else None
    result = apply_mapping(groups, test_database=True) if args.apply else dry_run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
