# Design — producer-ingress-policy

## Context

See proposal.md — Why. Constraints that shape the design:

- The §4.4 rule (`design/migration/ocean-to-pulse-adaptation-plan.md`) is a classification test
  over producer schemas: "does the event's payload name a state that lives in the catalog? Then
  it routes through the ledger. The catalog is the boundary, mechanically checkable in CI against
  producer event schemas." Sanctioned command sources are already registered there (Twenty drag
  webhook D8, Customer.io consent ingress D9, identity-resolution service, warehouse verdict
  runner, attributed humans) — this change enforces the boundary, it does not build adapters.
- The consumer contract is pinned (`docs/contracts/publishes.md`,
  `openspec/specs/catalog-source/spec.md`): `catalog/state_catalog.yaml` at the repo head, semver
  `catalog_version`, and `pulse_core.generated` (`CATALOG_VERSION`, `SUBJECT_TYPES`,
  `TRANSITIONS`, `COMMAND_TYPES`). The gate reads these and nothing else.
- `packages/ocean` has no schema registry. Producer schemas are Python: the `ocean_events`
  library (`BaseEvent` subclasses; `types.py` Literal aliases such as `AlertStatus`,
  `TicketStatus`; `entities.py` Pydantic models) plus per-service event construction in
  `services/*/src` (string `event_type` values like `"alert.created"`, payload dicts).
- Name collisions are real and load-bearing: `AlertStatus` carries `open`/`resolved`,
  `TicketStatus` carries `open`/`in_progress`/`resolved`, enrollment-adjacent words like `active`
  appear in device and contract vocabularies too — while catalog subjects (`referral`, `consent`,
  `communication_consent`, `enrollment`, `billing_episode`, `device`, `contract`) overlap none of
  ocean's declared entity types (`alert`, `task`, `ticket`, `device_association`, …). A bare-word
  scan would be red on today's tree; the Demo 2 acceptance requires green today, red on a planted
  state-bearing emit (`design/delivery/pulse-program-roadmap.md`).
- `task check` is the CI contract: offline, fresh-clone-safe, no npm globals, no credentials.
  `tests/` is already in `TESTED_PATHS`, so a repo-level pytest is in `check` with no
  `Taskfile.yml` edit.

## Goals / Non-Goals

**Goals:**

- The §4.4 classification test, mechanical and deterministic: same tree, same findings, offline.
- Green on the current tree without grandfathering — via subject-scoped matching, not via seeding
  the suppression list.
- Failure output an ocean producer author can act on: file, element, subject/state, disposition.

**Non-Goals:**

- No producer conversions: the producer inventory and adapter work (adaptation plan Phase 2, V6)
  are their own changes; today's tree has nothing to convert.
- No runtime enforcement: the ledger's write path already validates commands at commit; this gate
  constrains what `packages/ocean` schemas may declare, at CI time only.
- No envelope-schema generation (the fifth generated surface, adaptation plan §4.2) — that is a
  separate catalog-consuming change.
- No JSON-schema or cross-language scanning: producer schemas in this repo are Python; other
  repos' producers are governed by their own repos' contracts.

## Decisions

1. **The classifier lives in `pulse_core.producer_policy`, a pure function over parsed source.**
   It consumes the catalog through `pulse_core.generated` — the pinned programmatic surface —
   which puts it beside the catalog machinery precedent (`catalog_gen`, `catalog_release`) with
   typecheck, lint, and coverage wiring for free. Signature shape: extract vocabulary from a set
   of Python files → classify against subjects/states → list of findings (file, element, subject,
   states). No I/O beyond reading the files it is handed.
   *Alternative rejected:* a script under `scripts/` — outside coverage and typecheck, and the
   glue convention there is workflow plumbing, not contract enforcement. *Also rejected:* a
   helper inside `tests/` — not importable by the pulse-core unit tests that pin classification
   semantics.
2. **Extraction is AST-based, over three vocabulary surfaces.** `ast.parse` per file, no imports
   of scanned code (a producer service importing its `.venv` at gate time would be both slow and
   fragile): (a) literal state vocabularies — `Literal[...]` aliases and annotations, `StrEnum`
   /enum classes, and frozen string-set constants; (b) entity/subject-type declarations — values
   of `entity_type`-shaped fields and `EntityType`-style Literal aliases; (c) event-type
   addressing — string constants assigned or passed as `event_type`, split on the first dot.
   *Alternative rejected:* importing the schemas and introspecting Pydantic models — requires
   every service's dependency closure at check time, breaking fresh-clone and the one-process
   rule the services' own suites already violate.
3. **A finding requires subject addressing; matching is subject-scoped.** An element flags only
   when it addresses a catalog subject: (a) an entity/subject-type value equal to a subject name;
   (b) an event-type whose prefix equals a subject name AND whose remaining segment (or an
   accompanying payload value in the same declaration) names one of that subject's declared
   catalog states — prefix alone is not addressing (*narrowed at G_MECE validation:* ocean's real
   `device.associated`/`device.disassociated` event types share the `device` prefix, but
   `associated` is not a device state — device's states are
   ordered/shipped/delivered/active/returned/lost — so bare-prefix matching would be red on
   today's tree, breaking this change's own green-today scenario; a planted `enrollment.active`
   stays red because `active` IS an enrollment state); or (c) a state vocabulary of two or more
   values forming a subset of exactly one subject's declared state set (subset test over
   `TRANSITIONS[subject]` keys). The two-value floor plus the subset rule is what keeps
   `AlertStatus` (`claimed`/`dismissed` are not catalog states → not a subset) and `TicketStatus`
   (`in_progress`/`waiting` → not a subset) green while `Literal["screened", "outreach",
   "converted"]` is red. Single bare words never flag on their own.
   *Alternative rejected:* bare state-name matching — red on today's tree, forcing a seeded
   suppression list, which is grandfathering by another name. *Also rejected:* subject-name
   proximity heuristics (flag `active` when the word `enrollment` appears nearby) —
   non-deterministic in effect, unexplainable in a failure message.
4. **The gate is a repo-level pytest, `tests/test_producer_ingress_policy.py`.** It walks
   `packages/ocean` source (`libs/*/src`, `services/*/src`, `scripts/`; excluding `tests/`,
   `docs/`, `.venv/`, caches — tests may legitimately name catalog states when they test this
   very boundary), runs the classifier against the real catalog, applies suppressions, and fails
   listing every unsuppressed finding with its disposition line. Precedent:
   `tests/test_ocean_bus_dependencies.py` and `tests/test_catalog_consumer_contract.py` are the
   same shape — repo-level contract checks over `packages/ocean` and the catalog. `tests/` is in
   `TESTED_PATHS`, so `task check` picks it up with zero Taskfile or workflow edits (and no cat4
   exposure).
   *Alternative rejected:* a new `task producer:gate` target — a second wiring point that `check`
   would have to name explicitly, for no isolation benefit.
5. **Suppressions live at `packages/ocean/producer-policy-suppressions.yaml`, empty at ship.**
   Each entry names the finding it suppresses (file, element, subject) and carries a mandatory
   `justification`. The gate fails on an entry with no justification and on an entry matching no
   current finding — stale suppressions die instead of accumulating. The file sits inside
   `packages/ocean` because it annotates ocean schemas and should travel (and page) with them in
   review.
   *Alternative rejected:* no suppression mechanism — the first legitimate future collision (a
   non-subject vocabulary that happens to form a subset) would force either weakening the
   matcher for everyone or carrying a hand-patched gate. *Also rejected:* suppression via inline
   source comments — spreads policy adjudication across the tree; a reviewer can't see the full
   exemption surface in one file.
6. **Fixtures are synthetic schema files, and the planted-emit proof runs against them.** The
   classifier's unit tests (pulse-core) parse fixture source strings — a planted
   referral-asserting schema, a non-subject fact, the collision shapes — so classification
   semantics are pinned without touching real producer code. The repo gate's red→green scenario
   plants a fixture file into a copied scan tree (tmp_path), never into `packages/ocean` itself.
   This is the Demo 2 mechanic, rehearsed in CI on every run.
7. **The failure message is part of the contract.** Every finding renders as
   `<file>:<element> asserts <subject> state(s) <states>` followed by the fixed disposition line:
   convert the emit to a command through the ledger write path (`pulse_core.submit_command`), or
   — for a name-collision false positive only — suppress with justification; pointer to the
   producer-policy doc. Spec'd ("A red gate names the §4.4 disposition") so the message cannot
   rot into an assert diff.

## Risks / Trade-offs

- **[The subset rule can miss a disguised assertion — a producer inventing one novel state name
  alongside real catalog states dodges the ≥2-subset test only if fewer than two values remain
  catalog states; a fully renamed vocabulary dodges it entirely]** → accepted: §4.4's test is
  "names a state that lives in the catalog" — a producer that renames states isn't naming
  catalog states, and the write-path validator still rejects any attempt to smuggle the result
  into the ledger. The gate enforces the naming boundary, not intent.
- **[AST extraction misses dynamically built vocabularies (f-strings, concatenation, config
  files)]** → accepted and bounded: ocean's real schemas are static Literals, enums, and string
  constants today; the classifier's extraction surfaces are spec'd behavior, so widening
  extraction later is an additive spec change, not a rewrite.
- **[False positives as ocean vocabulary grows — a future non-subject Literal could form a
  subset of some subject's states]** → the suppression path exists for exactly this, justification
  required, stale entries fail; the matcher stays strict rather than growing heuristics.
- **[Scanning `services/*/src` pulls in emit-site strings, not just schema declarations — noisier
  surface]** → the addressing rules (entity-type equality, event-type prefix) are exact-match,
  not fuzzy; noise shows up as findings only when a service literally addresses a catalog
  subject, which is precisely what must not happen.
- **[Catalog growth changes gate behavior — a new subject or state added in a future catalog
  release could turn an existing ocean vocabulary red]** → correct and intended: that is the
  §4.4 boundary moving, and the breaking-change ceremony on the catalog side plus this gate's
  failure naming the exact collision make the interaction visible in the same PR that widens the
  catalog.

## Migration Plan

Purely additive: classifier module → gate test + suppression file → docs. No producer code
changes; the current tree must pass the gate un-suppressed (the suppression file ships empty and
the gate's stale-entry rule keeps it empty until a real collision is adjudicated). Rollback is
`git revert` of the change's commits — removes the module, gate, suppression file, and docs
section; nothing downstream depends on them yet. Ingress changes that follow
(`twenty-kanban-webhook-ingress`, `customerio-consent-ingress`) are born under the gate, per the
roadmap's no-grandfathering rule.

## Open Questions

None. The one candidate — whether emit-site payload dict keys should also be scanned — is
resolved as in-scope only through the three extraction surfaces of decision 2; widening to
payload-key analysis is a future additive spec change if a real evasion shows up.
