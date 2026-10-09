from __future__ import annotations

import argparse
import os
from pathlib import Path


def user_data_root() -> Path:
    explicit = os.environ.get("CAMPUSFACE_DATA_ROOT", "").strip()
    if explicit:
        return Path(os.path.expandvars(os.path.expanduser(explicit)))
    if os.name == "nt":
        return Path(os.path.expandvars(r"%LOCALAPPDATA%\CampusFace"))
    return Path.home() / ".campusface"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--bin', required=True)
    ap.add_argument('--data', default='')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--database', default='campusface')
    ap.add_argument('--user', default='campusface_app')
    args = ap.parse_args()

    root = user_data_root()
    cfg_dir = root / 'config'
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / 'module.env'
    existing = path.read_text(encoding='utf-8', errors='ignore').splitlines() if path.exists() else []
    pg_data = args.data or str(root / 'PostgreSQL' / 'data')

    desired = {
        'CAMPUSFACE_DATA_ROOT': str(root),
        'CAMPUSFACE_DB_MODE': 'postgres',
        'CAMPUSFACE_POSTGRES_HOST': args.host,
        'CAMPUSFACE_POSTGRES_PORT': str(args.port),
        'CAMPUSFACE_POSTGRES_DB': args.database,
        'CAMPUSFACE_POSTGRES_USER': args.user,
        'CAMPUSFACE_POSTGRES_SSLMODE': 'disable',
        'CAMPUSFACE_POSTGRES_BIN': args.bin,
        'CAMPUSFACE_POSTGRES_DATA': pg_data,
        'CAMPUSFACE_POSTGRES_LAUNCH_MODE': 'user-process',
    }
    seen: set[str] = set()
    out: list[str] = []
    for raw in existing:
        if '=' not in raw or raw.lstrip().startswith('#'):
            out.append(raw)
            continue
        key = raw.split('=', 1)[0].strip()
        if key in desired:
            out.append(f'{key}={desired[key]}')
            seen.add(key)
        else:
            out.append(raw)
    for key, value in desired.items():
        if key not in seen:
            out.append(f'{key}={value}')
    tmp = path.with_suffix('.env.tmp')
    tmp.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
    os.replace(tmp, path)
    print(f'[OK] CampusFace PostgreSQL configuration updated: {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
