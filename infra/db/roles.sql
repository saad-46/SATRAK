-- Database roles for SATRAK (ADR-0011). Run once per cluster as a superuser, then set passwords
-- out of band (never commit them). Names are fixed because migrations grant to `satrak_app`.
--
--   satrak_migrator  owns the schema and runs Alembic. Not used by the web application.
--   satrak_app       what the API and workers connect as: NOT the owner, NOT superuser, NOT
--                    BYPASSRLS, cannot run DDL. Subject to row-level security on every
--                    tenant-owned table.
--   satrak_admin     break-glass maintenance role with BYPASSRLS. Used only through
--                    app.db.privileged (every use is logged and audited); never by the API.
--
-- Local/CI example (the test suite expects satrak_app to exist; see apps/api/README.md):
--   psql -v ON_ERROR_STOP=1 -f infra/db/roles.sql
--   GRANT satrak_app TO <test owner>;   -- lets the suite SET ROLE satrak_app

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'satrak_migrator') THEN
        CREATE ROLE satrak_migrator LOGIN CREATEDB NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'satrak_app') THEN
        CREATE ROLE satrak_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'satrak_admin') THEN
        CREATE ROLE satrak_admin LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
    END IF;
END
$$;
