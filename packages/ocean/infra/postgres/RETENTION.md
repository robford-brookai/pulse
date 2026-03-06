# Audit Log Retention Design

**Regulatory basis:** 45 C.F.R. § 164.312(b) — HIPAA Security Rule, Audit Controls standard.
Minimum retention: 6 years from the date of creation or the date when the record was last in effect.

---

## Phase 1 Approach — Logical Retention with pg_partman Deferred

The `audit_log` table is created as a standard (non-partitioned) table in migration `0001_initial_schema.py`.
Monthly range partitioning via `pg_partman` is the target architecture but is deferred to Phase 3
(infrastructure hardening) to keep Phase 1 scope focused on schema and event flow.

### Regulatory compliance in Phase 1

1. **Retention enforced via `recorded_at` column** (`timestamptz NOT NULL DEFAULT now()`).
   No rows are ever deleted. The INSERT-only constraint is enforced at the database permission
   level (`REVOKE UPDATE, DELETE ON TABLE audit_log FROM PUBLIC`), satisfying the retention
   requirement: rows accumulate indefinitely and are never purged.

2. **Append-only at the database level.** The `ocean` application user holds INSERT privileges
   only on `audit_log`. UPDATE and DELETE are revoked from PUBLIC. This is verified at startup
   via integration test:
   ```sql
   UPDATE audit_log SET action_type='tampered' WHERE 1=1;
   -- Expected: ERROR: permission denied for table audit_log
   ```

3. **Verification query** (confirms no rows pre-date the 6-year window in a new deployment):
   ```sql
   SELECT COUNT(*) FROM audit_log WHERE recorded_at < NOW() - INTERVAL '6 years';
   -- Returns 0 for all new deployments; monitoring alerts if this becomes non-zero
   ```

---

## Production Path — Phase 3

Convert `audit_log` to monthly range partitioning using `pg_partman`:

1. Each partition covers one calendar month (`RANGE` on `recorded_at`).
2. Partitions older than 6 years are archived to cold storage (S3 via `pg_dump` per partition or
   `pg_partman` archive mode) **before** the partition is dropped.
3. Archives must be retrievable within 24 hours for audit purposes.
4. A monitoring query checks `recorded_at` range of the oldest active partition monthly.

Runbook location: `infra/postgres/runbooks/audit-log-archival.sh` (created in Phase 3).

---

## References

- 45 C.F.R. § 164.312(b) — Audit Controls
- 45 C.F.R. § 164.316(b)(2) — Documentation retention (6-year minimum)
- HHS guidance: https://www.hhs.gov/hipaa/for-professionals/security/guidance/index.html
- pg_partman: https://github.com/pgpartman/pg_partman
