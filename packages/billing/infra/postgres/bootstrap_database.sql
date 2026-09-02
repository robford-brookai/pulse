-- One-time database bootstrap for the billing engine's own Postgres store — run once per
-- environment by an operator holding RDS superuser (or rds_superuser) privileges, BEFORE the
-- first `task billing:migrate`.
-- Idempotent: safe to re-run (see the tie-in grant at the bottom).
--
-- Usage (mirrors packages/pulse-ledger/infra/postgres/bootstrap_database.sql):
--
--   psql "$RDS_ADMIN_DSN" \
--     -v migrator_password="$BILLING_ENGINE_MIGRATOR_PASSWORD" \
--     -v app_password="$BILLING_ENGINE_APP_PASSWORD" \
--     -f packages/billing/infra/postgres/bootstrap_database.sql
--
-- Both passwords come from psql variables, never a literal in this file or in shell history —
-- `-v name=value` is a separate argv entry, so the value never appears in the SQL text psql logs
-- or echoes back.
--
-- Two roles, same split pulse-ledger's bootstrap uses and for the same reason (runtime-readiness
-- D14/D15 posture, applied to this store): a migrator that can change the schema, and an app
-- role that cannot. This database is deliberately its own — not the `pulse_ledger` database, not
-- the `ledger` schema (design.md decision 4: "its own credential, not the ledger schema") — so
-- the engine's fact/evaluation store can never become reachable through a ledger credential.
--
--   billing_engine_migrator  LOGIN, CREATEROLE, owns the database. Runs `alembic upgrade head`
--                            (`task billing:migrate`). CREATEROLE is what lets migration 0001
--                            create the NOLOGIN group role `billing_engine_service` the first
--                            time it runs; owning the database is what lets it `CREATE SCHEMA
--                            billing_engine`.
--   billing_engine_app       LOGIN, owns nothing. The engine service's runtime credential
--                            (DATABASE_URL). It never runs DDL and is never granted CREATEROLE —
--                            the privilege split is enforced by Postgres, not by convention.
--
-- The split only closes after the FIRST migration run: `billing_engine_service` does not exist
-- until migration 0001 creates it, so the final block below — `GRANT billing_engine_service TO
-- billing_engine_app` — is a no-op the first time this script runs (before any migration) and
-- takes effect the first time it runs *after* one. Re-running this whole script post-migration
-- is the documented way to tie the grant in.

\set ON_ERROR_STOP on

-- `format(..., %L)` quotes the password safely; `\gexec` runs the row it produces. psql does NOT
-- perform `:'var'` substitution inside a dollar-quoted (`DO $$ ... $$`) block, so the idempotent
-- guard lives in the `WHERE NOT EXISTS` clause of the driving SELECT — same shape pulse-ledger's
-- bootstrap uses.
SELECT format('CREATE ROLE billing_engine_migrator LOGIN CREATEROLE PASSWORD %L', :'migrator_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'billing_engine_migrator') \gexec

SELECT format('CREATE ROLE billing_engine_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'billing_engine_app') \gexec

SELECT 'CREATE DATABASE billing_engine OWNER billing_engine_migrator'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'billing_engine') \gexec

-- No public access to the database at all; the app role gets exactly CONNECT, nothing more.
REVOKE ALL ON DATABASE billing_engine FROM PUBLIC;
GRANT CONNECT ON DATABASE billing_engine TO billing_engine_app;

\connect billing_engine

-- The `public` schema's default "anyone can CREATE" grant is Postgres's own footgun (CVE-2018
-- era default); revoke it so neither role can accidentally create objects outside
-- `billing_engine`.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- The tie-in: only fires once `billing_engine_service` exists (migration 0001 has run).
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'billing_engine_service') THEN
        GRANT billing_engine_service TO billing_engine_app;
    END IF;
END
$$;
