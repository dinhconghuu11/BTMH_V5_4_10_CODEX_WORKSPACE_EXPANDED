# CampusFace V1.12.1

- Fix PostgreSQL first-install race: setup now waits for the local service/port before database bootstrap.
- Adds safe recovery for an incomplete first-time V1.12.0 PostgreSQL setup when no application credential has been created yet.
- Recovery temporarily enables localhost-only trust, resets the dedicated `postgres` credential, creates `campusface_app`, then restores the original `pg_hba.conf` and restarts PostgreSQL.
- If a production credential already exists, the installer refuses destructive reset and asks for service diagnostics instead.
