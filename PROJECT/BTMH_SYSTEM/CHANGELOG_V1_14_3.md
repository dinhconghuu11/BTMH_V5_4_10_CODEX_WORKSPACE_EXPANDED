# CampusFace V1.14.3

- Fixes PostgreSQL bootstrap DDL password handling with psycopg 3.
- CREATE ROLE / ALTER ROLE password values are composed with psycopg.sql.Literal instead of parameter placeholders.
- Repairs an existing V1.14.2 per-user profile in-place at `%LOCALAPPDATA%\CampusFaceV1142`; no need to delete downloaded models, Python environment, or PostgreSQL cluster.
- Keeps user-managed PostgreSQL architecture: no Windows Service, no ProgramData ACL changes, no Administrator requirement.
