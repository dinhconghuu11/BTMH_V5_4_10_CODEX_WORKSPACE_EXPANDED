from pathlib import Path
import os, subprocess, sys, tempfile

ROOT = Path(__file__).resolve().parents[1]
config=(ROOT/'module_app'/'config.py').read_text(encoding='utf-8')
db=(ROOT/'module_app'/'db.py').read_text(encoding='utf-8')
ops=(ROOT/'module_app'/'production_ops.py').read_text(encoding='utf-8')
env=(ROOT/'module.env.example').read_text(encoding='utf-8')
req=(ROOT/'requirements-runtime.txt').read_text(encoding='utf-8')
setup=(ROOT/'SETUP_POSTGRESQL_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore')

assert '1.12.4-customer-safe-postgresql-production-ready' in config
assert 'CAMPUSFACE_DB_MODE", "postgres"' in config
assert '127.0.0.1' in config and '55432' in config
assert 'postgres_app_password.dpapi' in config
assert 'psycopg[binary]==3.3.5' in req
assert 'BIGSERIAL PRIMARY KEY' in db
assert 'BYTEA NOT NULL' in db
assert 'pg_dump' in ops and 'pg_restore' in ops
assert 'CAMPUSFACE_DATA_ROOT=%PROGRAMDATA%\\CampusFace' in env
assert 'CampusFacePostgreSQL' in setup and 'setup_embedded_postgres.ps1' in setup
assert '--serviceaccount campusface_pg' not in setup

# Runtime regression: explicit SQLite maintenance mode must still work for unit tests
# and one-time migration; production default remains PostgreSQL.
code = r'''
import os,sys,tempfile
from pathlib import Path
root=Path(os.environ['CF_ROOT']);sys.path.insert(0,str(root))
from module_app.db import init_db,execute,fetchone,db_status,utc_now
from module_app.production_ops import ensure_production_schema
init_db();ensure_production_schema()
now=utc_now()
sid=execute("INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,biometric_consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('PGT01','Test User','A','','','',now,'GRANTED',now,now,now))
assert sid>0
assert fetchone('SELECT student_code FROM students WHERE id=?',(sid,))['student_code']=='PGT01'
assert db_status()['mode']=='sqlite'
print('OK')
'''
with tempfile.TemporaryDirectory() as td:
    e=os.environ.copy();e['CF_ROOT']=str(ROOT);e['CAMPUSFACE_DB_MODE']='sqlite';e['CAMPUSFACE_DATA_ROOT']=td
    p=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=e,capture_output=True,text=True)
    assert p.returncode==0,(p.stdout,p.stderr)
    assert 'OK' in p.stdout

print('[OK] V1.12 PostgreSQL production contract')
