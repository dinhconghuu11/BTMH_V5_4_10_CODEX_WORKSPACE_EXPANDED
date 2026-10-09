# CampusFace V1.12.3 Embedded PostgreSQL - Test Report

## Changes validated
- Existing `postgresql-x64-*` services are not modified by the new deployment code.
- CampusFace uses a private PostgreSQL 17 runtime path and a dedicated `CampusFacePostgreSQL` service on `127.0.0.1:55432`.
- The setup can source PostgreSQL 17 binaries from a bundled EDB binary ZIP, copy binaries from an existing PostgreSQL 17 installation, or download the EDB binary ZIP once when Internet is available.
- Customer PostgreSQL data remains under `C:\ProgramData\CampusFace\PostgreSQL\data` and application credentials use Windows DPAPI.
- If a valid production credential already exists, setup refuses destructive reset.
- Installer diagnostics are written to `C:\ProgramData\CampusFace\logs\postgres-install.log`.

## Automated regression
33 project regression modules passed in SQLite maintenance/test mode, including the V1.12 PostgreSQL contract and the new V1.12.3 embedded PostgreSQL deployment contract.

## Environment limitation
The current build environment is Linux, so Windows Service registration and a real PostgreSQL Windows process could not be executed here. The release includes explicit service/port/log diagnostics and must still be smoke-tested on Windows before customer delivery.
