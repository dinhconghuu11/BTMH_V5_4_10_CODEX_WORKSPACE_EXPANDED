from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
setup = (ROOT / 'scripts' / 'setup_embedded_postgres.ps1').read_text(encoding='utf-8')
ensure = (ROOT / 'scripts' / 'ensure_postgres_running.ps1').read_text(encoding='utf-8')
bootstrap = (ROOT / 'scripts' / 'bootstrap_postgres.py').read_text(encoding='utf-8')
config = (ROOT / 'module_app' / 'config.py').read_text(encoding='utf-8')
installer = (ROOT / 'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8')

assert '1.13.0-postgresql-production-installer' in config
assert 'C:\\ProgramData\\CampusFace' not in config or 'CampusFace' in config

# V1.13 must not depend on editing postgresql.conf: that was the repeated Windows ACL failure.
assert "WriteAllText($conf" not in setup
assert 'Add-Content -Path $conf' not in setup
assert "Join-Path $PgData 'postgresql.conf'" not in setup

# Host/port isolation is supplied directly to postgres for both setup and runtime starts.
assert 'return "-h 127.0.0.1 -p $Port"' in setup
assert '& $pgctl start -D $PgData -l $log -o $opts -W' in setup
assert '& $pgctl start -D $PgData -l $runtimeLog -o $opts -W' in ensure
assert "register -N $ServiceName -D $PgData -S auto -U 'NT AUTHORITY\\NetworkService' -o $opts" in setup

# Service failure must not fail customer installation by itself.
assert 'if(Try-ServiceMode)' in setup

assert 'CampusFacePostgreSQLFallback' in setup
assert 'Register-ScheduledTask' in setup
assert "Start-PrivateProcess 'postgres-runtime.log'" in setup

# Port must be persisted before bootstrap imports DB config.
assert "Save-LaunchMode 'process'" in setup
assert setup.index("Save-LaunchMode 'process'") < setup.index('Bootstrap-Database $mode')
assert "os.environ['CAMPUSFACE_POSTGRES_PORT'] = str(args.port)" in bootstrap

# Bootstrap must not use ALTER SYSTEM, which writes postgresql.auto.conf.
assert 'ALTER SYSTEM SET' not in bootstrap

# Customer-facing installation remains one-shot/repairable.
assert 'SETUP_POSTGRESQL_WINDOWS.bat' in installer
assert 'check_ready.py' in installer
print('[OK] V1.13.0 PostgreSQL production installer contract')
