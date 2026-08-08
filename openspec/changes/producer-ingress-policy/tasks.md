# Tasks — producer-ingress-policy

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps` names
task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network in
any test (`--disable-socket`): the classifier parses source text, the gate walks the committed
tree, and every gate must hold in a fresh clone. No PHI anywhere — inputs are committed source
code and the catalog; fixtures are synthetic schema files that never carry patient data.

---

## 1. Wave 0 — the classifier

- [ ] 1.1 Producer-policy classifier (`pulse_core.producer_policy`): AST-based vocabulary
      extraction over handed-in Python source — literal state vocabularies (`Literal` aliases and
      annotations, enum classes, frozen string-set constants), entity/subject-type declarations,
      and `event_type` string addressing (first dot-segment) — classified against the pinned
      contract surface `pulse_core.generated` (`SUBJECT_TYPES`, `TRANSITIONS`). A finding
      requires subject addressing (design decision 3, as narrowed at G_MECE): entity-type
      equality; an event-type whose subject prefix is joined by one of that subject's declared
      states in the remaining segment or accompanying payload (bare prefix never flags —
      `device.associated` stays green, a planted `enrollment.active` is red); or a ≥2-value
      state vocabulary forming a subset of exactly one subject's state set; bare single words
      never flag. Findings carry file, element, subject, states, and
      render with the fixed §4.4 disposition line (design decision 7). Pure function, no I/O
      beyond the files it is handed, no imports of scanned code. Tests (pulse-core, over
      synthetic fixture sources): a planted referral-asserting schema yields a finding naming
      file/element/subject/states (spec: "A state-asserting producer schema is flagged"); a
      non-subject fact schema yields none (spec: "A non-subject fact schema passes"); alert- and
      ticket-shaped collision vocabularies (`open`/`resolved`, `open`/`in_progress`) yield none
      (spec: "A bare-word name collision does not flag").
      `[model: opus | deps: — | lane: repo_change | wave: 0]`
      Model `opus`: the subject-scoped matching rule *is* the §4.4 boundary — too loose
      grandfathers state-asserting emits silently, too strict makes the gate red on legitimate
      vocabulary and forces suppression creep; both are retrofit-expensive across every future
      ingress change.

## 2. Wave 1/2 — suppressions and the gate

- [ ] 2.1 Suppression mechanism: load `packages/ocean/producer-policy-suppressions.yaml` (ships
      empty) into the classifier's filtering step — each entry names the finding it suppresses
      (file, element, subject) and carries a mandatory `justification`; filtering returns the
      surviving findings plus suppression errors for entries with no justification and entries
      matching no current finding. Tests (pulse-core, fixture findings + fixture suppression
      docs): a justified entry removes exactly the named finding while an unrelated finding
      survives (spec: "A justified suppression suppresses exactly the named finding"); a
      justification-less entry and a stale entry each produce an error naming the offending entry
      (spec: "A stale or unjustified suppression fails the gate").
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
      Depends on 1.1, not parallel: both edit `producer_policy.py`, so they serialize to avoid a
      same-wave merge conflict.
- [ ] 2.2 The repo-level gate `tests/test_producer_ingress_policy.py`: walk `packages/ocean`
      producer source (`libs/*/src`, `services/*/src`, `scripts/`; excluding `tests/`, `docs/`,
      `.venv/`, caches — sorted before iteration), run the classifier against the real catalog,
      apply suppressions, fail listing every unsuppressed finding and every suppression error.
      Runs under `task check` via the existing `TESTED_PATHS` entry for `tests/` — no
      `Taskfile.yml` or workflow edits. Tests: the committed tree passes with the shipped-empty
      suppression file, offline (spec: "The current tree passes the gate"); planting a
      referral-asserting fixture schema into a copied scan tree turns the gate red naming the
      planted schema and subject/state, removing it turns the gate green — the Demo 2 mechanic
      against `tmp_path`, never `packages/ocean` itself (spec: "A planted state-bearing emit
      turns the gate red, and removal turns it green").
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 2]`

## 3. Wave 3 — docs and the contract entry

- [ ] 3.1 Docs: producer-policy page in `packages/ocean/docs/` — the §4.4 rule (state-asserting
      emit → command through the ledger write path; non-subject fact → direct emit; the
      classification test), the sanctioned command sources from the adaptation plan §4.4, the
      what-to-do-when-red procedure, and the suppression rules (false positives only,
      justification required, stale entries fail, no grandfathering). Update
      `docs/contracts/consumes.md`: the gate consumes exactly the pinned catalog contract
      (`catalog/state_catalog.yaml` at repo head + `pulse_core.generated`) — no seed, no
      Snowflake rows, no generator internals. mkdocs nav entry if the page is published;
      placeholders as inline code, never link syntax; `mkdocs build -s` green. Test: the gate's
      failure output on a fixture finding carries the disposition line and a pointer that
      resolves to the committed producer-policy doc (spec: "A red gate names the §4.4
      disposition").
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 3]`
      `serial: openspec_main_specs` — doc-updater lane, contract docs.
