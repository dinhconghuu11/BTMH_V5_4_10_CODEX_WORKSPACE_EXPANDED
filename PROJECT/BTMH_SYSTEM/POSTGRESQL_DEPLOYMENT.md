# PostgreSQL deployment for CampusFace V1.12

## Runtime topology

- Service name: `CampusFacePostgreSQL`
- Listen address: `127.0.0.1`
- Port: `55432`
- Database: `campusface`
- Application role: `campusface_app`
- PostgreSQL binaries: `C:\Program Files\CampusFace\PostgreSQL17\bin`
- Database cluster: `C:\ProgramData\CampusFace\PostgreSQL\data`
- App password secret: `C:\ProgramData\CampusFace\data\postgres_app_password.dpapi`

The app password is generated randomly during setup and protected by Windows DPAPI with machine scope. The installer does not write it to source files, module.env, README, or logs.

## Offline build

Run `PREPARE_PORTABLE_OFFLINE_WINDOWS.bat` on the build PC. It downloads the official PostgreSQL 17.11 x64 Windows installer and checks its fixed SHA-256 before the package is accepted as complete.

## Existing V1.11 data

Run `MIGRATE_SQLITE_TO_POSTGRES_WINDOWS.bat`. Migration is copy-only: the old SQLite database remains untouched until the operator decides to archive it.

## Backup

V1.12 database backup uses `pg_dump --format=custom`. Restore uses `pg_restore --clean --if-exists`. Face template encryption key is included in the CampusFace backup ZIP so restored encrypted embeddings remain usable. Treat backup ZIPs as sensitive data and keep them on encrypted storage/BitLocker.
