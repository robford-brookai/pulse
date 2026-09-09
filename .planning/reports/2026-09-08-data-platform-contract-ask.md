# PR body (draft, owner reviews before opening) — data-platform branch `pulse-verdict-mart-publisher-contract`

Branch pushed to `Brookai/data-platform` at commit `79fcf6a`. **Not opened as a PR** — pulse
drafts, the owner reviews and opens it.

---

## Title

`docs: adopt publisher contract for STREAMLINE.OCEAN_MARTS.OCEAN_VERDICTS (ask from pulse)`

## What

Adds `management/models/billing/verdict/README.md`: a publisher contract for the
`STREAMLINE.OCEAN_MARTS.OCEAN_VERDICTS` mart, drafted by `pulse`'s `packages/verdict-relay` (the
mart's sole reader) and pushed here for data-platform to review and adopt. Pins:

- grain — one row per `(subject_id, verdict_type, run)`, append-only, never an update
- the eight contract columns and types, plus the negative constraint (no payer/member-id column,
  ever)
- `subject_id` for the two coverage verdict types as the patient × payer digest
  (`{patient_subject_key}:{first 16 hex of sha256(payer_identifier, lowercased, UTF-8)}`), derived
  by Billy at adjudication and carried through unchanged — no raw payer identifier reaches this
  mart at any stage
- the closed `verdict_type` vocabulary (`billing_eligibility`, `coverage_eligibility`,
  `benefits_verification`) and the `outcome` vocabulary that now decides ledger state
- `computed_at` monotonicity, the reader's cursor/pagination behavior, and what a contract
  violation does today (fails the row, fails the page, before any API call)
- where coverage detail (QMB status, benefit categories, copay) belongs — verdict payload and
  `lineage_ref`, never a new column

Chose a standalone doc (`README.md`, not a `schema.yml` model description) because
`management/models/billing/verdict/` has no `.sql` model in this repo yet — the model that
computes this mart today lives in `brookai/streamline`
(`dbt_project/models/ocean/marts/ocean_verdicts.sql`, merged `Brookai/streamline#20`, DNA-1252),
not here. Attaching `schema.yml` column tests to a model this repo doesn't have would fail dbt
parsing. `management/models/billing/schema.yml` is this repo's convention for column-level
`not_null`/`accepted_values`/`unique` tests once a model exists here — recommend porting this
contract into that form when/if the model itself moves or is rebuilt in this repo.

## Why

`docs/contracts/consumes.md` in `pulse` has carried this dependency with no publisher contract
of its own on the producing side — pulse's own test fixtures are the only pinned shape. ADR-0006
(`pulse`, merged 2026-09-08) states data-platform's dbt owns marts computed from business logic;
this is the first attempt at a real contract under that split, requested by the consuming repo
rather than authored blind on the producing side.

**Open question for data-platform to resolve, flagged rather than assumed:** the model that
actually computes `OCEAN_VERDICTS` today lives in `brookai/streamline`
(`dbt_project/models/ocean/marts/ocean_verdicts.sql`), not in `data-platform`. Searching this
repo's full history (`git log --all`) and every branch turns up no commit and no path under
`management/models/billing/verdict/` predating this PR, and no commit `ffe9770` anywhere in this
repo. Adopting this contract does not by itself move the model — that's a separate, larger
migration. Please confirm whether "adopt this contract" means committing to it for a model this
repo will build/own going forward, or whether the streamline model stays authoritative for now
and this doc is aspirational.

## Seed gate 3 — dbt spike files for the billing-connector fixture mart (asked 2026-09-02)

Separately, `docs/contracts/consumes.md` (verdict-reconcile / billing-connector task 4.1) asks
data-platform to land the dbt spike files that model the reconciliation window's comparison
fixture mart — a **different** mart (`gold_billing.verdict_billing_episode` /
`verdict_run_audit`, `billing_cpt_achieved.99454` / `billing_episode_qualified` verdict types)
from the production `OCEAN_VERDICTS` mart this PR's contract covers.

**No committed or pushed spike branch was found for this.** The candidate branch names checked
(`origin/dbt-billing-test-research`, `origin/dna-1136-spike-mongo-cdc-risingwave-snowflake`,
`origin/feature/DNA-143-APCM-billing`) contain no verdict/billing-connector fixture content on
any commit. However, the local `data-platform` clone used to draft this ask
(`/Users/Rob.Ford/Repos/brookai/data-platform`) currently holds **uncommitted, unpushed working-tree
files** that appear to be exactly this spike: `management/models/billing/verdict/_verdict__models.yml`,
`verdict_billing_episode.sql`, `verdict_run_audit.sql`, two tests under
`management/tests/billing/`, and a contract note at
`.planning/dna-1136-spike/verdict-mart-contract.md`. These were left by another
session/agent working in the same shared clone (last checked-out branch per reflog:
`dna-1136-spike-mongo-cdc-risingwave-snowflake`) — this PR-drafting task did not create, commit,
or push them, to avoid attributing or clobbering someone else's in-progress work. **Action for
the owner:** find who owns that spike work and have them commit and push it to a named branch (or
confirm it should be discarded) — until then, seed gate 3 stays blocked exactly as
`consumes.md` already states, and the sweep's fixture mart cannot be built.

## What pulse will do when this merges

- Update `docs/contracts/consumes.md`'s verdict-mart entry to point at the merged contract
  instead of "no publisher contract of its own yet."
- Once data-platform confirms the physical-location question above, update the "producing repo"
  citation in `consumes.md` accordingly (today it names `brookai/data-platform`,
  `management/models/billing/verdict/`, a path/commit this session could not verify exists — see
  the pulse PR opened alongside this ask for the interim correction).
- No change to `packages/verdict-relay` itself: the contract only formalizes the shape the
  reader's fixtures already pin; nothing here changes reader behavior.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01HFyVbRnGafcGN4ukLTdjaV
