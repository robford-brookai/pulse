# Runbook: Demo 2 (partial) — s13-schedules + s14-identity

Per the roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints),
this is the demo receipt for two shipped Phase 2 changes: `s13-schedules` (DNA-837) and
`s14-identity` (DNA-849). It is "partial" — it covers what those two changes shipped, not the
whole of Phase 2. Every command below runs against fixtures only, offline, on a fresh checkout —
no Docker, no LocalStack, no Postgres, no credentials, no live network.

## What it shows

1. **Identity resolution** (`identity.matcher.resolve`, s14-identity) — an exact-identifier match,
   a composite mint, a two-candidate quarantine, and the `identifier_conflict` split, with each
   decision's rule id printed as evidence.
2. **Month-open** (`schedules.cli month-open --dry-run`, s13-schedules) — the would-declare set for
   a normal month, then the zero-enrollment fixture's hard-failure invariant (nonzero exit).
3. **Consent sweep** (`schedules.cli consent-sweep --dry-run`, s13-schedules) — corrections in both
   directions against a drift export, with Customer.io winning every conflict (D9) and malformed
   rows counted rather than dropped.

## Prerequisites

- This repo's Python environment synced: `uv sync --all-packages` (or `task check` will already
  have done this once).
- Nothing else. No Docker, no network — every command below is `uv run ...` against files already
  committed to this repo.

## 1. Identity resolution (s14-identity, DNA-849)

`identity.matcher.resolve` is a pure function — no ledger writes, no I/O of its own (design
decision 1 in `packages/identity/src/identity/matcher.py`) — so it runs directly against the
package's own synthetic fixtures (`packages/identity/tests/fixtures/`). Three of the four
scenarios below load a fixture file by name; the fourth (`identifier_conflict`) has no fixture
file — `packages/identity/tests/fixtures/*.json` has no `identifier_conflict` case — so it
reproduces the same synthetic referral/persons `test_matcher.py`'s
`test_identifiers_resolving_to_two_people_quarantine_rather_than_pick_one` already exercises.
`scripts/demo/demo2_identity_matcher.py` drives all four through the published `resolve()` entry
point and prints each decision's rule id as evidence — the closest thing to a CLI this package
has, since `identity.service.main` needs a live ledger and command API (see the module's own
`# pragma: no cover` note) and pytest alone does not print evidence, only pass/fail.

```bash
uv run python scripts/demo/demo2_identity_matcher.py
```

Expected output:

```
=== Demo 2 (partial): identity resolution (s14-identity, DNA-849) ===

[1/4] exact-identifier match short-circuits the composite tier
{"case": "exact_identifier_hit", "decision": "match", "rule_id": "identifier_exact", "matched_fields": ["identifier_system", "identifier_value"], "candidate_count": 1, "person_id": "person-identifier-owner"}

[2/4] composite mint — unknown identifier, zero composite candidates
{"case": "mint_unknown_everything", "decision": "mint", "rule_id": "composite_none", "matched_fields": ["last_name", "dob", "sex", "first_initial"], "candidate_count": 0}

[3/4] two-candidate quarantine — composite tier finds two candidates
{"case": "two_candidate_ambiguity", "decision": "ambiguous", "rule_id": "composite_ambiguous", "matched_fields": ["last_name", "dob", "sex", "first_initial"], "candidate_count": 2, "candidates": ["person-candidate-one", "person-candidate-two"]}

[4/4] identifier_conflict split — two identifiers, two different holders
{"case": "identifier_conflict_split", "decision": "ambiguous", "rule_id": "identifier_conflict", "matched_fields": ["identifier_system", "identifier_value"], "candidate_count": 2, "candidates": ["person-alpha", "person-beta"]}

=== Demo 2 (partial): all four identity assertions passed ===
```

Exit code `0`. The four `rule_id` values printed are the full published contract
(`docs/contracts/publishes.md`, "Identity matcher") minus `composite_unique` (a single-candidate
composite match — the boring case none of the four scenarios above needs to cover separately).
`identifier_conflict` and `composite_ambiguous` are the two that quarantine — see
`docs/runbooks/identity-quarantine.md` for the reviewer-facing side of what happens next to a
quarantined referral.

## 2. Month-open (s13-schedules, DNA-837)

`schedules.cli month-open --dry-run` builds the would-declare set with no ledger connection, no API
call, no socket (`run_month_open_dry_run_job`) — the offline-dry-run contract task 4.2 built.

### Normal month — would-declare set, exits 0

```bash
uv run python -m schedules.cli month-open --dry-run \
  --fixture packages/schedules/tests/fixtures/normal_month.json
```

Expected output (one JSON line; reformatted here for readability):

```json
{
  "dry_run": true,
  "invariant_breach": null,
  "would_declare": [
    {
      "command": {
        "subject_key": "enr-active-1:2026-08-01",
        "command_type": "open_billing_episode",
        "subject_type": "billing_episode",
        "month": "2026-08-01"
      },
      "effective_at": "2026-08-01T00:00:00+00:00"
    },
    {
      "command": {
        "subject_key": "enr-hold-1:2026-08-01",
        "command_type": "open_billing_episode",
        "subject_type": "billing_episode",
        "month": "2026-08-01"
      },
      "effective_at": "2026-08-01T00:00:00+00:00"
    }
  ]
}
```

Exit code `0`. `normal_month.json` carries three enrollments — `active`, `on_hold`, `ended` — and
the would-declare set has exactly two entries: the `ended` enrollment is correctly excluded.

### Zero-enrollment — hard-failure invariant, exits nonzero

```bash
uv run python -m schedules.cli month-open --dry-run \
  --fixture packages/schedules/tests/fixtures/zero_enrollment.json
```

Expected output:

```json
{"dry_run": true, "invariant_breach": "zero_enrollment", "would_declare": []}
```

Exit code `1` — the same hard-failure invariant a real run applies (`ZeroEnrollmentError`,
"Zero-enrollment failure" in `docs/runbooks/month-open.md`): a billing month with no enrollments
enumerated at all always fails, regardless of what states a run requests, because enumerating
nothing is far more likely to be a broken read than an operationally empty month.

## 3. Consent sweep (s13-schedules, DNA-837)

`schedules.cli consent-sweep --dry-run` parses the export, diffs it against an optional ledger-state
fixture, and prints the would-declare set — no ledger connection, no API call, no socket
(`run_consent_sweep_dry_run_job`). None of `packages/schedules/tests/fixtures/consent_sweep/`'s
existing exports combines a correction in both directions with a malformed row in one file (each
isolates one behavior for its own unit test), so this demo adds one small fixture pair alongside
them, in the package's own fixture directory and shape:

- `demo_drift_both_directions.csv` — four export rows: one opt-out drift, one opt-in drift, and two
  malformed rows (a bad boolean, a missing `subject_key`).
- `demo_drift_both_directions_ledger.json` — the ledger consent state the export diffs against.

```bash
uv run python -m schedules.cli consent-sweep --dry-run \
  --export-file packages/schedules/tests/fixtures/consent_sweep/demo_drift_both_directions.csv \
  --file-id demo2-consent-sweep \
  --export-as-of 2026-08-06 \
  --ledger-fixture packages/schedules/tests/fixtures/consent_sweep/demo_drift_both_directions_ledger.json
```

Expected output (one JSON line; reformatted here for readability):

```json
{
  "dry_run": true,
  "would_declare": [
    {
      "command": {
        "subject_key": "SUBJ-001:sms",
        "command_type": "record_communication_consent",
        "subject_type": "communication_consent",
        "channel": "sms",
        "to_state": "opted_out",
        "method": null,
        "evidence_ref": "demo2-consent-sweep:row:1"
      },
      "effective_at": "2026-08-06T00:00:00+00:00"
    },
    {
      "command": {
        "subject_key": "SUBJ-002:email",
        "command_type": "record_communication_consent",
        "subject_type": "communication_consent",
        "channel": "email",
        "to_state": "opted_in",
        "method": null,
        "evidence_ref": "demo2-consent-sweep:row:2"
      },
      "effective_at": "2026-08-06T00:00:00+00:00"
    }
  ],
  "unparseable": 2
}
```

Exit code `0`. Reading the evidence:

- `SUBJ-001` is not opted out in the ledger fixture (no row for it — absence means "not
  suppressed"); the export suppresses it (`suppressed: true`) — an **opt-out** correction
  (`to_state: "opted_out"`).
- `SUBJ-002` is already `opted_out` in the ledger fixture; the export does not suppress it
  (`suppressed: false`) — an **opt-in** correction (`to_state: "opted_in"`), overriding the
  ledger's prior state. This is D9's "Customer.io wins every conflict" made concrete: the export
  is authoritative even when it contradicts what the ledger already recorded.
- `unparseable: 2` — the bad-boolean row and the missing-`subject_key` row both failed to parse,
  and both are counted here rather than silently dropped (spec: "Malformed rows are counted and
  attached"). A dry run never fails on malformed rows — only `--dry-run`'s own always-zero exit
  contract applies (see `run_consent_sweep_dry_run_job`'s docstring); the full `DriftReceipt`
  (including `parse_errors`, row numbers, and detail) is what a live `consent-sweep` run's receipt
  would carry — see `docs/runbooks/consent-sweep.md`.

## Not part of `task check`

Everything above is offline and fast enough to stay in the default `task check` run — no exclusion
needed, unlike Demo 1 (which needs LocalStack). `tests/test_demo2_identity_matcher.py` exercises
the identity driver end to end (not just its argparse surface); the month-open and consent-sweep
commands are exercised by `packages/schedules/tests/test_cli.py` against their own fixtures, and by
hand against the fixtures named above whenever this runbook is next verified.
