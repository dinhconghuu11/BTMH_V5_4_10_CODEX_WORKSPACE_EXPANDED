# CampusFace V1.12.3 - Embedded PostgreSQL

- Replaces the fragile EDB silent-server install path with a CampusFace-managed PostgreSQL binary runtime.
- Never modifies an existing `postgresql-x64-*` Windows service.
- Uses dedicated runtime `C:\Program Files\CampusFace\PostgreSQL17`.
- Uses dedicated cluster `C:\ProgramData\CampusFace\PostgreSQL\data`.
- Registers only `CampusFacePostgreSQL` on local-only port `55432`.
- Can reuse/copy PostgreSQL 17 binaries already present on the PC without touching that installation's data/service.
- Can consume a bundled EDB binary ZIP for fully offline customer deployment.
- First-install recovery preserves valid customer clusters; no destructive reset is performed after a production credential exists.
- Adds install transcript at `C:\ProgramData\CampusFace\logs\postgres-install.log`.
- Removes the invalid `--serviceaccount campusface_pg` installer dependency that caused V1.12.0/V1.12.1 service-creation failures on some Windows PCs.
