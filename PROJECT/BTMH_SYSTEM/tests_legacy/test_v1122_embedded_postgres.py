from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
setup=(ROOT/'SETUP_POSTGRESQL_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore')
ps=(ROOT/'scripts'/'setup_embedded_postgres.ps1').read_text(encoding='utf-8',errors='ignore')
config=(ROOT/'module_app'/'config.py').read_text(encoding='utf-8',errors='ignore')
prepare=(ROOT/'PREPARE_POSTGRESQL_OFFLINE_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore')
assert '1.12.4-customer-safe-postgresql-production-ready' in config
assert 'CampusFacePostgreSQL' in setup
assert '--serviceaccount campusface_pg' not in setup+ps
assert 'postgresql-17.11-3-windows-x64-binaries.zip' in ps and 'postgresql-17.11-3-windows-x64-binaries.zip' in prepare
assert "PostgreSQL17" in ps
assert "PostgreSQL\\data" in ps
assert "127.0.0.1" in ps and "55432" in setup
assert 'Find-SystemPg17Root' in ps
assert 'Copy-Runtime' in ps
assert 'NT AUTHORITY\\NetworkService' in ps
assert 'PG-DATA-001' in ps
assert 'postgres-install.log' in ps
print('[OK] V1.12.4 customer-safe PostgreSQL deployment contract')
