# Runbook: Demo 3 — the live kanban round trip (`twenty-projection`, task 7.1)

Per the roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints),
this closes Phase 3's `twenty-projection` change. Unlike Demos 1 and 2 this one is **live** — it
needs a reachable dev Twenty instance and a running `pulse_ledger.api_server`, so `task check`
holds only the smoke-parse contract (`tests/test_demo3_live_kanban_drag.py`); a human runs the
script itself attended (WORKFLOW.md `live_execution`).

Script: `scripts/demo/demo3_live_kanban_drag.py`.

## What it shows

Nine assertions, in order:

1. **UID round-trip** — the live `patientProgram` object and its `lifecycleStatus` field carry the
   `universalIdentifier` values `uid-map.json` minted.
2. **Board shape** — the lifecycle board exists, is KANBAN, and groups on the `lifecycleStatus`
   field.
3. **Column parity** — the board's groups are exactly the catalog's `enrollment` states.
4. **Seed counts** — every record in the committed projection is present in the workspace.
5. **As-of stamps** — every seeded board record carries non-null status as-of stamps.
6. **One webhook** — exactly one webhook is registered, scoped to the one mapped operation.
7. **A legal drag commits**, driven through Twenty's own REST API — the same write a UI drag
   issues.
8. **A replay probe** proves, against the real committed event, that `effective_at` is the
   record's own `updatedAt` stamp (never the wall clock) and that a redelivery of the drag's
   idempotency key produces no second event.
9. **An illegal drag** returns 200 `rejected` with exactly one new rejection note bound to the
   card, and the state of record is unchanged.

See the script's module docstring for why steps 7–8 read the commit's properties off a
purpose-built replay probe rather than the delivery's own response (Twenty's own webhook usually
wins the race, so the self-delivery's response is almost always `echo_of_record` and proves
nothing on its own).

## Prerequisites

- A reachable dev Twenty instance (v2.30.0+) already seeded by `task twenty:seed TARGET=dev`, with
  `twenty-kanban-webhook-ingress`'s webhook route live.
- A running `pulse_ledger.api_server` pointed at the same dev ledger Twenty was seeded from.
- This repo's Python environment synced: `uv sync --all-packages`.
- Credentials in the environment, never printed and never in code:
  - `PULSE_TWENTY_DEV_URL` / `PULSE_TWENTY_DEV_TOKEN` (resolved by
    `pulse_core.twenty_deploy.resolve_target`, the same pair every credentialed Twenty target
    uses).
  - `PULSE_LEDGER_API_URL` / `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET`.

## Running it

```bash
task demo:3
```

equivalent to:

```bash
uv run python scripts/demo/demo3_live_kanban_drag.py --target dev
```

`--card-index` (default `0`) selects which seeded `pending_start` card to drag, by index into the
sorted-by-id list — never by name. If someone drags the selected card by hand between runs, or the
workspace is re-seeded (which resets the card but not the ledger), the card and the ledger's
genesis state diverge and the legal leg fails with the catalog's own rejection receipt; rerun with
a different `--card-index`.

```bash
uv run python scripts/demo/demo3_live_kanban_drag.py --help
```

## Reading the output

Each of the nine numbered steps prints what it read or committed, followed by the assertion it
proves. A successful run ends with:

```
=== Demo 3: all nine live assertions passed ===
```

and exits `0`. A failed assertion prints `FAILED: <what went wrong>` to stderr and the script
exits `1` — the receipt for either outcome is the script's own stdout/stderr.

## Troubleshooting

- **Step 1 (`UID round-trip`) fails** — the workspace was not built from the committed artifact
  (`task twenty:deploy TARGET=dev`), or `uid-map.json` is stale; re-run `task twenty:validate`
  first.
- **Step 6 (`one webhook`) fails with more than one registered** — a previous manual test or a
  stale environment left an extra webhook registered; remove it by hand before rerunning.
- **Step 7 or 9 fails with the catalog's rejection reason on what should be a legal drag** — the
  selected card and the ledger have diverged (see `--card-index` above); pick a different index or
  re-seed both the workspace and the ledger together.
- **A connection error to Twenty or the ledger API** — check the four environment variables above
  are exported and point at the same dev environment.

## Not part of `task check`

This script needs a live dev Twenty instance and a running ledger API, so it is intentionally
excluded from `task check` and CI, and from `task demo:3`'s reach from `check`.
`tests/test_demo3_live_kanban_drag.py` covers what does not need either: the script parses, its
argument surface behaves, and `--help` exits cleanly with no live network.
