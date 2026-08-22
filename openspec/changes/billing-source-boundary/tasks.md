# Tasks — billing-source-boundary

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). This change is
docs and tests only: no catalog bump, no migration, no production code — `task check` stays
green, offline and credential-free at every step. Synthetic data only; no PHI and no real
payer identifiers anywhere. Specs are owned by the doc-updater: write proposed spec changes to
`HANDOFF.md`, never edit `openspec/specs/`.

**Entry conditions.** None blocking (proposal §Entry conditions). Task 3.1 touches `AGENTS.md`
(standing serial lane `AGENTS.md` per `WORKFLOW.md` `routing.serial_lane_always`) and releases
alone in wave 2. `billing-state` is in flight; this change writes no delta on `verdict-declare`
or `coverage-state` and adds no test under `packages/verdict-relay/` — see the bijection map
for the two scenarios billing-state already covers.

**Task ↔ scenario bijection** (G_MECE `task_scenario_bijection_covered`):

| Delta spec scenario | Covered by |
|---|---|
| billing-computation-boundary / "No catalog subject carries a monetary field" | 2.1 |
| billing-computation-boundary / "A command asserting an amount is refused" | 2.2 |
| billing-computation-boundary / "A verdict moves state and records its provenance" | **existing** — `packages/verdict-relay/tests/test_declarer.py` (pairing commits `declare_transition` carrying `rule_version` + `lineage_ref`), shipped by billing-state task 2.1; design.md decision 4 |
| billing-computation-boundary / "Nothing downstream recomputes the verdict" | **existing** — `packages/verdict-relay/tests/test_run.py` + `packages/pulse-ledger/tests/test_fold.py` (fold moves state only on `to_state`-bearing events; no consumer evaluates rules), shipped by billing-state; design.md decision 4 |
| billing-computation-boundary / "Benefit detail stays in evidence" | 2.2 |
| billing-computation-boundary / "The contract answers the question directly" | 1.3 |
| producer-registry / "A registry entry names its seam and its actor" | 1.1 |
| producer-registry / "Deliberate exclusions are entries, not omissions" | 1.1 |
| producer-registry / "The legacy list points forward" | 1.2 |
| producer-registry / "A new writer credential without an entry fails review" | 3.1 |
| producer-registry / "The revenue model's entry states both directions and the amount-free rule" | 1.1 |

---

## 1. Wave 1 — the registry and the stated boundary

- [ ] 1.1 Author `docs/contracts/producer-registry.md` and its shape test. One markdown table,
      columns exactly `System | Direction | Seam | Credential / actor | Grain | Status |
      Notes`; `Direction` one of `declares in | consumes out | both`; `Status` one of
      `shipped | spec-only | planned | blocked | excluded-by-design`. Rows, at minimum:
      the Twenty kanban webhook (D8, `shipped`), Customer.io consent ingress (D9, ADR-0005,
      `shipped`), the identity-resolution service (`shipped`), the warehouse verdict relay
      (I3, `shipped`), human actors via attributed tooling (`shipped`), the cpt-om CPT revenue
      model (direction `both`; inbound seam command API under its own credential declaring
      `billing_eligibility` verdicts, outbound seam the published warehouse surfaces per
      `docs/contracts/publishes.md`; `spec-only`; Notes cite `billing-computation-boundary`
      and state that no monetary value crosses in), Billy (`planned`), POCAR (`planned`),
      the PAP standard connector (`spec-only`), and at least one `excluded-by-design` row
      with its reason stated in Notes. Add the page to `mkdocs.yml` nav next to the other
      contracts pages (placeholders as inline code, never link syntax — `mkdocs build -s`
      fails on broken links).
      Tests (new `tests/test_producer_registry.py`, the
      `tests/test_producer_ingress_policy.py` pattern): parse the table; assert the exact
      column set above; assert every `Status` and `Direction` cell is in its fixed vocabulary;
      assert ≥ 1 row has status `excluded-by-design` with a non-empty Notes cell; assert the
      cpt-om row has direction `both`, seam naming the command API, and Notes containing
      `billing-computation-boundary`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.2 Mark the legacy inventory superseded. Add a note at the top of
      `packages/ocean/docs/pt-data-infra-acq-status.md`: superseded as a governance surface by
      `docs/contracts/producer-registry.md`, retained as historical context on where patient
      facts lived pre-connector-architecture. Do not delete or rewrite the inventory itself.
      Tests (in `tests/test_producer_registry.py`): the legacy file contains the string
      `producer-registry.md` and the word `superseded` (case-insensitive) within its first 30
      lines.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
      Dep is the shared test module: 1.1 creates `tests/test_producer_registry.py`, this task
      appends to it — sequenced so two same-wave workers never collide on the file.

- [ ] 1.3 State the billing computation boundary where an integrator will look: new
      `docs/contracts/billing-boundary.md` (added to `mkdocs.yml` nav). Contents: PULSE
      records billing *qualification* (trinary verdict + `rule_version` + `lineage_ref`) and
      computes no monetary value — no rate, amount, CPT/HCPCS code as state, fee schedule, or
      optimization; those belong to the registered external revenue model (link the cpt-om
      registry row); clinics submit claims; the episode terminates at `reported` (D6), with
      `billed → reconciled` reserved behind config; money may appear in verdict evidence,
      never in state vocabulary or catalog fields; commands enter only via the command API and
      a top-level monetary field is refused. Name design.md open question 1
      (`Contract.terms.economics_model`) as explicitly undecided.
      Tests (new `tests/test_billing_boundary_doc.py`): the page exists; contains the strings
      `reported`, `rule_version`, `producer-registry.md`, and `qualification`; contains no
      occurrence of a dollar-amount literal (regex `\$[0-9]`) — the boundary page itself
      carries no rates; `mkdocs.yml` nav references both new contracts pages.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 2. Wave 1 — the amount-free tripwires

- [ ] 2.1 Catalog monetary deny-list test, new
      `packages/pulse-core/tests/test_catalog_amount_free.py`: load
      `catalog/state_catalog.yaml`; for every subject, collect every field name, state name,
      and transition-reason key the catalog defines; assert none contains, case-insensitive,
      any of: `rate`, `amount`, `price`, `revenue`, `copay`, `fee`, `charge`, `cost`, `cpt`,
      `hcpcs`, `usd`, `cents`, `dollar`. The deny-list is a module-level tuple in the test
      with a comment naming this change; a failure message names the offending subject and
      field. Assert the guard is live by construction: the test must fail (assert via a
      self-check on a synthetic catalog dict containing `allowed_amount`) before asserting the
      real catalog passes.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [ ] 2.2 Command-envelope refusal and evidence-pass test, new
      `packages/pulse-ledger/tests/test_billing_boundary.py`, offline against the real
      coercion path in `pulse_ledger.api`: (a) a `declare_transition`-shaped body for subject
      `billing_episode` carrying top-level `allowed_amount: 123.45` raises
      `UnknownDeclarationFieldError` naming `allowed_amount` — refused, not silently dropped;
      (b) the same for `rate_cents: 4500` on a `declare_verdict`-shaped body; (c) the
      complement: a `declare_verdict` body whose `payload` contains
      `{"copay": "35.00", "benefit_category": "QMB"}` coerces cleanly — evidence is opaque and
      the boundary is state-vs-evidence, not a keyword ban (billing-state decision 2, delta
      requirement "Money may appear in evidence, never in state"). Synthetic ids throughout.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

## 3. Wave 2 — the convention that keeps it true

- [ ] 3.1 Registry enforcement: the repo-resident-producer check and the `AGENTS.md` line.
      (a) Extend `tests/test_producer_registry.py`: a module-level mapping, spelled out in the
      test, from each repo-resident ingress surface to its required registry row —
      `packages/consent-ingress` → Customer.io consent ingress row,
      `packages/verdict-relay` → warehouse verdict relay row,
      `pulse_ledger.twenty` (webhook) → Twenty kanban webhook row,
      `packages/identity` → identity-resolution row; the test asserts each mapped package or
      module exists in the tree AND its row exists in the table, so adding an ingress package
      without a registry row fails CI by name.
      (b) One line in `AGENTS.md` under its review conventions: a change introducing a new
      writer credential or ingress package must add or update the matching
      `docs/contracts/producer-registry.md` row in the same change — absence is a finding, not
      a variant (delta requirement "An unregistered producer is a defect").
      Tests: (a) is itself the test; for (b), `tests/test_producer_registry.py` asserts
      `AGENTS.md` contains the string `producer-registry.md`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 2]`
      `serial: AGENTS.md` — touches the standing serial-lane file; releases alone.
