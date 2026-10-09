from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TABLES = [
    'students', 'face_templates', 'recognition_events', 'classroom_events', 'audit_events',
    'attendance_sessions', 'attendance_records', 'runtime_settings', 'system_users',
]


def main() -> int:
    parser = argparse.ArgumentParser(description='Migrate CampusFace SQLite data to local PostgreSQL')
    parser.add_argument('--sqlite', required=True)
    parser.add_argument('--old-key', default='')
    args = parser.parse_args()
    src_path = Path(args.sqlite).resolve()
    if not src_path.exists():
        raise SystemExit(f'SQLite not found: {src_path}')

    os.environ['CAMPUSFACE_DB_MODE'] = 'postgres'
    from module_app.config import KEY_PATH
    from module_app.db import connection, init_db
    from module_app.production_ops import ensure_production_schema

    init_db(); ensure_production_schema()
    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    try:
        existing = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with connection() as dst:
            # Delete child tables first so rerunning the migration is deterministic.
            for table in reversed(TABLES):
                if table in {'runtime_settings'} or table in existing:
                    try:
                        dst.execute(f'DELETE FROM {table}')
                    except Exception:
                        pass
            for table in TABLES:
                if table not in existing:
                    continue
                rows = src.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                if not rows:
                    continue
                cols = rows[0].keys()
                placeholders = ','.join(['?'] * len(cols))
                sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
                for row in rows:
                    dst.execute(sql, tuple(row[c] for c in cols))
                print(f'[OK] {table}: {len(rows)} rows')

            # Reset PostgreSQL sequences after preserving original IDs.
            for table in [t for t in TABLES if t != 'runtime_settings']:
                try:
                    dst.execute(
                        "SELECT setval(pg_get_serial_sequence(?, 'id')::regclass, COALESCE((SELECT MAX(id) FROM " + table + "), 1), COALESCE((SELECT MAX(id) FROM " + table + "), 0) > 0)",
                        (table,),
                    )
                except Exception:
                    pass
    finally:
        src.close()

    old_key = Path(args.old_key).resolve() if args.old_key else src_path.parent / 'face_templates.key'
    if old_key.exists():
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_key, KEY_PATH)
        print(f'[OK] Face template key copied: {KEY_PATH}')
    else:
        print('[WARN] No old face_templates.key found. Existing encrypted FaceID templates may not be readable.')
    print('[OK] SQLite -> PostgreSQL migration completed. Original SQLite was not deleted.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
