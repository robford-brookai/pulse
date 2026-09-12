# Handoff Summary: idempotency-integrity

Collected 1 handoff(s).

## idempotency-integrity-3-2

## Design drift

None. The spec's scenarios hold as written, and the commit path's behaviour matches what this
package's tests assume.

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/idempotency-integrity/specs/`
2. Run `openspec validate idempotency-integrity` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
