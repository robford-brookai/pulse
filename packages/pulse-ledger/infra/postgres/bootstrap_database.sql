-- One-time database bootstrap for pulse-ledger — run once per environment by an operator
-- holding RDS superuser (or rds_superuser) privileges, BEFORE the first `task ledger:migrate`.
-- Idempotent: safe to re-run (see the tie-in grant at the bottom).
--
-- Usage (see docs/runbooks/pulse-command-api-deploy.md for the full procedure):
--
--   psql "$RDS_ADMIN_DSN" \
--     -v migrator_password="$PULSE_LEDGER_MIGRATOR_PASSWORD" \
--     -v app_password="$PULSE_LEDGER_APP_PASSWORD" \
--     -f packages/pulse-ledger/infra/postgres/bootstrap_database.sql
--
-- Both passwords come from psql variables, never a literal in this file or in shell history —
-- `-v name=value` is a separate argv entry, so the value never appears in the SQL text psql logs
-- or echoes back.
--
-- Two roles, and why there are two (runtime-readiness D14/D15 posture, applied to the database
-- layer): a migrator that can change the schema, and an app role that cannot.
--
--   pulse_ledger_migrator  LOGIN, CREATEROLE, owns the database. Runs `alembic upgrade head`
--                          (`task ledger:migrate`). CREATEROLE is what lets migration 0001 create
--                          the NOLOGIN group role `pulse_ledger_service` the first time it runs
--                          (infra/postgres/versions/0001_ledger_schema.py:191-201); owning the
--                          database is what lets it `CREATE SCHEMA ledger`.
--   pulse_ledger_app       LOGIN, owns nothing. The command API's runtime credential
--                          (DATABASE_URL). It never runs DDL and is never granted CREATEROLE —
--                          the privilege split is enforced by Postgres, not by convention.
--
-- The split only closes after the FIRST migration run: `pulse_ledger_service` does not exist
-- until migration 0001 creates it, so the final block below — `GRANT pulse_ledger_service TO
-- pulse_ledger_app` — is a no-op the first time this script runs (before any migration) and
-- takes effect the first time it runs *after* one. Re-running this whole script post-migration
-- is the documented way to tie the grant in; it is not a separate script because everything
-- above it is already safe to repeat.
--
-- After this grant, `pulse_ledger_app` can SELECT/INSERT on `ledger.events` (via its membership
-- in `pulse_ledger_service`) and physically cannot UPDATE or DELETE it, cannot DDL anything in
-- `ledger`, and cannot CREATE SCHEMA — verified against a throwaway cluster while authoring this
-- file (INSERT succeeds, UPDATE/CREATE TABLE/CREATE SCHEMA all raise permission denied).

\set ON_ERROR_STOP on

-- `format(..., %L)` quotes the password safely; `\gexec` runs the row it produces. Both role
-- creations use this shape rather than a bare `CREATE ROLE ... PASSWORD :'x'` because psql does
-- NOT perform `:'var'` substitution inside a dollar-quoted (`DO $$ ... $$`) block, so the
-- idempotent guard has to live in the `WHERE NOT EXISTS` clause of the driving SELECT instead of
-- a PL/pgSQL IF.
SELECT format('CREATE ROLE pulse_ledger_migrator LOGIN CREATEROLE PASSWORD %L', :'migrator_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pulse_ledger_migrator') \gexec

SELECT format('CREATE ROLE pulse_ledger_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pulse_ledger_app') \gexec

SELECT 'CREATE DATABASE pulse_ledger OWNER pulse_ledger_migrator'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'pulse_ledger') \gexec

-- No public access to the database at all; the app role gets exactly CONNECT, nothing more.
REVOKE ALL ON DATABASE pulse_ledger FROM PUBLIC;
GRANT CONNECT ON DATABASE pulse_ledger TO pulse_ledger_app;

\connect pulse_ledger

-- The `public` schema's default "anyone can CREATE" grant is Postgres's own footgun (CVE-2018 era
-- default); revoke it so neither role can accidentally create objects outside `ledger`.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- The tie-in: only fires once `pulse_ledger_service` exists (migration 0001 has run). Direct
-- `GRANT` inside a `DO` block, no `EXECUTE` needed — the same idiom migration 0001 already uses
-- for `CREATE ROLE ... NOLOGIN` inside its own `IF NOT EXISTS` guard.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'pulse_ledger_service') THEN
        GRANT pulse_ledger_service TO pulse_ledger_app;
    END IF;
END
$$;
