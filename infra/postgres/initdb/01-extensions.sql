-- Runs once, on first initialisation of an empty data volume.
-- Schema objects are owned by Alembic migrations; this file only enables the
-- extensions the migrations depend on (they need superuser to create).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Read-only role used by the natural-language event-log query tool (AIL-08).
-- LLM-generated SQL never runs with write privileges; grants on specific views
-- are issued by the migration that creates them.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pids_readonly') THEN
    CREATE ROLE pids_readonly NOLOGIN;
  END IF;
END
$$;
