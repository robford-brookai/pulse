# Design: devex-eight-3

## Context

Audit 3 (`11622da`): overall 6.5, connector 6.7; dimensions Getting Started 6, API 7, Errors 5,
Docs 8, Upgrade 7, Dev env 7, Community 5, Measurement 7. QA accepted A with corrections and B
outright, and surfaced two repo findings: the `verify` fast-fail finding was recorded closed but is
not (R1), and `devex_open_findings=0` reads as "no defects" when it means "no encoded finding is
open" (R2).

## Goals / Non-Goals

**Goals**: lift Errors and Getting Started by two tiers each (they are the connector composite's
weak slices), and make the count's meaning explicit. **Non-Goals**: no rubric edits here; no
attempt to move Community beyond the per-area CODEOWNERS and defect template the audit named.

## Decisions

1. **Structural guard tests, behavioural twins slow.** The `verify` guard is asserted from the
   Taskfile (a `preconditions` entry naming CHANGE), because the behavioural probe runs the whole
   gate when the guard is missing. The probe stays as a `slow` test.
2. **Hermetic git in gates, not in the developer's config.** The scaffold helpers pass
   `-c commit.gpgsign=false` per call; we do not ask authors to change their global git config.
3. **A declare example is a real call.** The finding test requires a code-line call to
   `submit_with_retry(` in a service template, not a comment telling the author to add one.
4. **Timings go to the ledger, not stdout.** `task check` appends `{target, seconds, rc}` rows via
   the existing `.planning/devex/loop.jsonl`, keeping one record.
5. **Protocol lessons ship separately.** Task A's contended timings (2 to 4 times inflated) and
   the zero-count semantics are protocol changes and go through their own PR with a CHECKSUMS
   refreeze.
