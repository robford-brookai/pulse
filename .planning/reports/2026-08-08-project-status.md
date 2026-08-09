# pulse — project status, 2026-08-08

Ground truth: `openspec/changes/archive/`, PR history, and `design/delivery/pulse-program-roadmap.md`
(note: that doc's own header is dated 2026-08-04 and its Phase 2 table is one merge behind — this
report reflects the current archive state, which supersedes it).

## Headline

**Phase 2 — Ingress is complete. All 7 changes shipped and archived. v2.0 tags the close.**

All four sanctioned command sources are now live: kanban webhook, Customer.io ingress, identity
service, verdict relay. No OpenSpec change is currently open — `openspec/changes/` holds only
`archive/`, plus two gate-free, not-yet-started items (`bf0a-archaeology-access`, `synthea-seed`).

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 0 — Absorption | S0.1/S0.2 catalog spec + machinery | ✅ complete |
| 1 — Record | S1.1 ledger schema + command API | ✅ complete |
| 2 — Ingress | S2, S1.2–S1.4, catalog authority, kanban + Customer.io ingress, producer policy | ✅ **complete — 7/7 changes** |
| 3 — Projections | S3 (Twenty app, projections, survey ingress, reconciliation, rebuild drill, M1) | queued, not started |
| 4 — Retirement | S4 (dbt derived-state retirement, ODG read redirect) | queued, not started |

## Phase 2 — the 7 shipped changes

| Change | Tasks | PRs | Archived |
|---|---|---|---|
| `s12-verdict-relay` (DNA-827) | 8/8 | #106–113 | `archive/2026-08-05-s12-verdict-relay` |
| `s13-schedules` (DNA-837) | 11/11 | #117–133 | `archive/2026-08-06-s13-schedules` |
| `s14-identity` (DNA-849) | 11/11 | #118–141 | `archive/2026-08-06-s14-identity` |
| `catalog-authority` (DNA-862) | 8/8 | #150–163 | `archive/2026-08-07-catalog-authority` |
| `twenty-kanban-webhook-ingress` (DNA-872) | 9/9 | #149–167 | `archive/2026-08-08-twenty-kanban-webhook-ingress` |
| `producer-ingress-policy` (DNA-884) | 4/4 | #171–174 | `archive/2026-08-08-producer-ingress-policy` |
| `customerio-consent-ingress` (DNA-890–896) | 7/7 | #178–186 | `archive/2026-08-08-customerio-consent-ingress` |

Last close: `customerio-consent-ingress`, merged as `chore(openspec): archive
customerio-consent-ingress — Phase 2 complete` (d2fa42cf). Collect ran as a manual handoff harvest
(the automated scanner flaked twice — nothing lost); doc_update was a clean no-op; `task verify`
green.

## Open flags carried out of Phase 2 (not blocking, tracked for later)

- `catalog-authority` (DNA-862): program `entry_gate`/exclusivity fills owed by the billing team,
  ValueSet-binding widening, first-deploy Snowflake database name pin.
- `twenty-kanban-webhook-ingress` (DNA-872): board-vocabulary reconciliation, patient×program
  grain question.
- `customerio-consent-ingress`: event_time-not-in-payload and a cursor double-count bug were both
  fixed with regression tests in task 4.1 during execution — no open flag remains.

## What's next — Phase 3 (Projections)

Gate: Phase 2 exit (now cleared) + a Twenty dev instance from `environment-matrix`. Nothing in
this phase is proposed yet.

| Change | Delivers | Gate |
|---|---|---|
| `pulse-app-scaffold` | Twenty app package, objects, roles, catalog → SELECT-options codegen | D4 |
| `twenty-projection` | ledger-fed consumer, heal-back write closes D8 end-to-end | `pulse-app-scaffold` |
| `customerio-projection` | segment/attribute sync from ledger events | Phase 2 exit |
| `snowflake-projection` | STG_EVENTS ledger contract atop `OCEAN_RAW.EVENTS` | Phase 2 exit |
| `survey-engine-ingress` | PX survey responses as attributed ledger commands | Phase 2 exit + PX schema validation |
| `reconciliation-sweeps` | per-family referee sweeps generalizing S1.3's consent sweep | `snowflake-projection` |
| `projection-rebuild-drill` | ADR §4.6 rebuild drill — carries Demo 3 | `twenty-projection` |
| `m1-retire-patient-state` | ADR §6.2 cutover, `enrollment_status` read-only | `twenty-projection` |

Caution already on record: `survey-engine-ingress`'s PX dependency has a stated June–July delivery
target that has already passed — re-verify the timeline with Max Pengilly before sequencing
anything against it.

## Recommended immediate action

Refresh `design/delivery/pulse-program-roadmap.md` — its Phase 2 table still shows
`customerio-consent-ingress` as "cleared, proposable" rather than shipped, and its header date is
stale. A `doc_update`-style pass (or a small direct docs PR) should fold in the #186/close-commit
state before proposing the first Phase 3 change, so `orient()` and the next `opsx:propose` start
from a correct baseline.
