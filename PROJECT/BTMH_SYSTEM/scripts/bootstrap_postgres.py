from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--super-password', required=True)
    parser.add_argument('--app-password', required=True)
    parser.add_argument('--host', default=os.getenv('CAMPUSFACE_POSTGRES_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.getenv('CAMPUSFACE_POSTGRES_PORT', '55432')))
    parser.add_argument('--database', default=os.getenv('CAMPUSFACE_POSTGRES_DB', 'campusface'))
    parser.add_argument('--app-user', default=os.getenv('CAMPUSFACE_POSTGRES_USER', 'campusface_app'))
    parser.add_argument('--reset-super-password', action='store_true')
    args = parser.parse_args()

    os.environ['CAMPUSFACE_DB_MODE'] = 'postgres'
    os.environ['CAMPUSFACE_POSTGRES_HOST'] = args.host
    os.environ['CAMPUSFACE_POSTGRES_PORT'] = str(args.port)
    os.environ['CAMPUSFACE_POSTGRES_DB'] = args.database
    os.environ['CAMPUSFACE_POSTGRES_USER'] = args.app_user
    os.environ['CAMPUSFACE_POSTGRES_SSLMODE'] = 'disable'

    import psycopg
    from psycopg import sql

    admin = psycopg.connect(
        host=args.host, port=args.port, dbname='postgres', user='postgres',
        password=args.super_password, sslmode='disable', autocommit=True,
        connect_timeout=8,
    )
    try:
        with admin.cursor() as cur:
            if args.reset_super_password:
                cur.execute(sql.SQL('ALTER ROLE postgres WITH LOGIN PASSWORD {}').format(sql.Literal(args.super_password)))
            cur.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (args.app_user,))
            if cur.fetchone():
                cur.execute(sql.SQL('ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(sql.Identifier(args.app_user), sql.Literal(args.app_password)))
            else:
                cur.execute(sql.SQL('CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(sql.Identifier(args.app_user), sql.Literal(args.app_password)))
            cur.execute('SELECT 1 FROM pg_database WHERE datname=%s', (args.database,))
            if not cur.fetchone():
                cur.execute(sql.SQL('CREATE DATABASE {} OWNER {} ENCODING \'UTF8\'').format(sql.Identifier(args.database), sql.Identifier(args.app_user)))
            else:
                cur.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(sql.Identifier(args.database), sql.Identifier(args.app_user)))
    finally:
        admin.close()

    from module_app.config import PG_SECRET_PATH
    from module_app.secret_store import save_secret
    save_secret(PG_SECRET_PATH, args.app_password, machine_scope=False)

    os.environ['CAMPUSFACE_POSTGRES_PASSWORD'] = args.app_password
    from module_app.db import init_db, db_status
    from module_app.production_ops import ensure_production_schema
    init_db()
    ensure_production_schema()
    print('[OK] PostgreSQL bootstrap complete:', db_status())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
