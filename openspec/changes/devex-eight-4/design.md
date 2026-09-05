# Design: devex-eight-4

## Context

Audit 4 (`5177d05`): overall 6.0, connector 5.6; dimensions Getting Started 7, API 5, Errors 6,
Docs 7, Upgrade 6, Dev env 7, Community 4, Measurement 6. QA accepted with corrections and raised
C-X1: PR #403 shipped both headline defects while `devex_open_findings` read 0, because the gate's
connector coverage asserted that a task target exists rather than that it works.

## Goals / Non-Goals

**Goals**: return the connector golden path to green and make the gate's zero mean it. **Non-Goals**:
no rubric or protocol edits (frozen, CHECKSUMS); no attempt on the single-author Community
constraint; nothing from the audit's below-the-cut list.

## Decisions

1. **Every finding test renders or runs.** A finding is encoded as the behaviour its fix produces,
   exercised against a rendered tree, a probe run of the real target, or the repo's own output —
   never as the presence of a config line. #380's structural test closed a finding that was still
   open (devex-loop lesson); #403's defects survived a 45-test gate for the same reason.
2. **The combined run is the contract, and it rules out the audit's literal prescription.** The
   scorecard's fix 1 is "ship `templates/connector/tests/__init__.py.tmpl` and switch to
   `from tests.factories import ...`, copying `packages/billing-connector`". Verified in a scratch
   tree: that shape works for one package and fails for two. `packages/billing-connector/tests` is
   already a top-level `tests` package, so a second one collides inside pytest's plugin manager
   (`ValueError: Plugin already registered under a different name`) the moment both are in
   `TESTED_PATHS` — which is exactly what a new connector joins. The shape that works, measured at
   194 passed across billing-connector plus both rendered directions, is **no `tests/__init__.py`
   and a relative `from .factories import ...`**: under `--import-mode=importlib` pytest derives a
   unique dotted name from the path, and the relative import resolves inside it. The finding test
   therefore runs the rendered suites *together with* `packages/billing-connector/tests` and leaves
   the shape to the implementer; the copy-billing-connector reading fails it.
3. **The control is slow; its twin is not.** `scripts/devex/check.py` counts xfails in the default
   (non-slow) run, so the render-and-gate control cannot be the counted test. It is marked `slow`
   and xfailed, and a non-slow twin asserts the replacement itself: that
   `test_connector_scaffold_command_exists` is gone and the control is present. The control's
   marker comes off with task 1.2 (the second of the two reverts), not with wave 2, so
   `task test:all` never sees an XPASS between waves.
4. **The control runs the gate's constituents, not `task check`.** It executes inside
   `task test:all`; calling `task check` would recurse. It runs `ruff format --check`,
   `ruff check --no-fix` and the combined `pytest --import-mode=importlib` over the rendered tree.
   Typecheck is excluded: `pyright` is an npm global CI runners do not have
   (`docs/contracts/consumes.md`), and neither defect this control exists to catch is a type error.
5. **Probes are hermetic and never skip.** The lint-message probe overrides `LINT_PATHS` to a
   scratch directory holding one unformatted file, so the real target runs against nothing in the
   tree; where `task` or `openlore` is absent (CI installs uv and Python only) the test falls back
   to the tightest readable assertion rather than skipping, because a skipped test drops out of
   the open-finding count and would silently under-report it.
6. **The timing rows leave the tracked file; the audit rows stay in it.** Fix 7 is two halves of
   one property: a green gate leaves `git status` clean, and the rows it wrote are printed back as
   the gate's last screenful. `.planning/devex/loop.jsonl` cannot simply be gitignored — its
   `audit` rows are the tracked receipt `test_ledger_exists_with_a_baseline_row` reads, and that
   test runs in a fresh clone. So the timing rows move to their own ignored file and
   `scripts/devex/check.py`'s `read_timings()` follows them there. The finding test reads the
   destination path out of `scripts/devex/timing.py` and asserts git does not track it, so the
   assertion cannot be satisfied by renaming alone.
