-- Runs once on first container start (empty data dir). The postgis/postgis image
-- already ships the extension binaries; this guarantees the extensions are
-- enabled in the application database so a fresh clone is immediately spatial.
-- Alembic migration 0001 also enables these idempotently for non-Docker setups.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
