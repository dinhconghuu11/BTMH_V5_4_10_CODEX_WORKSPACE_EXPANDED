# CampusFace V1.12.4 - Customer-Safe

## Deployment hardening
- Repairs PostgreSQL ACLs before reading/writing `postgresql.conf`.
- Preflights the private PostgreSQL cluster before attempting Windows Service registration.
- Prefers `CampusFacePostgreSQL` under `NetworkService`, but automatically falls back to a user-managed `pg_ctl` process if Windows service policy/account startup fails.
- `START_CAMPUSFACE.bat` starts PostgreSQL automatically in either service or managed-process mode.
- Preserves customer database/credentials on repair; an existing production credential that cannot be validated is never automatically reset.
- Detects port conflicts and can select the next free localhost port.
- Does not stop/delete/modify existing `postgresql-x64-*` services.
- Adds Python 3.12 registry discovery and one-time private Python download/install fallback.
- Root remains clean: INSTALL, START, README, app.

## Known boundary
Windows-specific service behavior cannot be fully executed in the Linux build environment. The release therefore includes service-independent managed-process fallback. Final customer distribution should still be smoke-tested on clean Windows 10/11 VMs.
