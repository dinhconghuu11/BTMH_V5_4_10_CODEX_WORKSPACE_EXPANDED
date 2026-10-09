# CampusFace V1.14.0 - User-Managed PostgreSQL

## Installer architecture reset

V1.14 stops patching Windows ACL/service behavior from V1.12-V1.13.x.

- Mutable data moved from shared ProgramData to `%LOCALAPPDATA%\CampusFace`.
- PostgreSQL 17 remains the production database engine.
- PostgreSQL runs as a private process owned by the current Windows user.
- Removed dependency on PostgreSQL Windows Service, NetworkService, Scheduled Task, takeown, icacls and .NET SetAccessControl.
- Old `C:\ProgramData\CampusFace` remnants are not read by the V1.14 launcher.
- PostgreSQL remains bound to `127.0.0.1` on a private port.
- PostgreSQL application password is protected with per-user Windows DPAPI.
- Python runtime/venv, PostgreSQL runtime, models, logs, config and database data are all writable without Administrator elevation.
- Re-running setup repairs the same per-user installation and preserves a valid database.

## Recognition/classroom functionality

No intentional changes to the passive FaceID, anti-spoof, classroom AI, student management or history UI in this installer release.
