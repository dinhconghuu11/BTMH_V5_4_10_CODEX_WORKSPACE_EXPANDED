# CampusFace V1.13.0 - PostgreSQL Production Installer

## Deployment hardening
- Removed all installer writes to `postgresql.conf`; private host/port are passed directly to PostgreSQL with `pg_ctl -o`.
- Avoids the repeated Windows `Access denied` failure on `C:\ProgramData\CampusFace\PostgreSQL\data\postgresql.conf`.
- Persists the selected PostgreSQL port before application bootstrap so non-default private ports work correctly.
- Uses `pg_ctl -W` plus an explicit TCP readiness probe when the port is supplied through command-line options.
- Keeps a private PostgreSQL 17 runtime under `C:\Program Files\CampusFace\PostgreSQL17` and private customer data under `C:\ProgramData\CampusFace`.
- Does not alter any existing `postgresql-x64-*` service or existing PostgreSQL data on the customer PC.
- Windows service mode remains preferred; service registration/start failure automatically falls back to a managed PostgreSQL process instead of failing installation.
- PostgreSQL application password remains stored with Windows DPAPI machine protection.

## Customer safety
- Existing CampusFace credentials/data are preserved on repair.
- Incomplete first-time clusters are moved aside rather than silently deleted.
- Logs are written to `C:\ProgramData\CampusFace\logs`.
