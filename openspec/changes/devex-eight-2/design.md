# Design: devex-eight-2

## Context

Audit 2 (`b26dee0`): overall 5.9, connector 5.8, QA accepted with corrections. Dimensions:
Getting Started 7, API ergonomics 6, Errors 6, Docs 6, Upgrade 5, Dev env 6, Community 3 (QA:
unresolved 3 to 5), Measurement 8. The connector composite is dominated by kit ergonomics (30) and
connector documentation (20), both at 6.

## Goals / Non-Goals

**Goals**: move the six dimensions that this repo controls toward 8 or 9, so the unweighted mean
clears 8.0 even with Community held at 4 by single authorship: (9+8+8+8+8+8+4+9)/8 = 7.75 is not
enough, so at least two of Getting Started, Docs, Errors and Measurement must reach 9.
**Non-Goals**: no rubric or protocol edits inside this change; no attempt to game Community.

## Decisions

1. **Findings first, again.** Wave 0 encodes the twelve findings as strict xfails before any fix
   lands, so the count is the metric and every fix PR flips exactly one test.
2. **Docs findings get deterministic gates, not judgement.** The front door, the guide links, the
   stale counts and the PR checklist are all greppable; cat8 owns the countable claims permanently.
3. **Prior-art collision is a warning, not a refusal.** `connector:new` prints where the legacy
   service lives and continues; refusing would block legitimate replacements.
4. **Inbound variant is a second worked example, not a flag.** The template grows a
   `direction/inbound/` overlay with its own service, receipts and test; the outbound one stays the
   default so existing golden tests hold.
5. **Kit changelog starts at the next version bump, deprecations live in the spec.** The spec
   edit goes through HANDOFF.md for the doc-updater per AGENTS.md; the test only checks the
   section exists.
6. **Audit briefs leave the reader-facing nav via `exclude_docs`, not by moving files.** The
   protocol files stay where CHECKSUMS expects them; mkdocs `exclude_docs` hides the three task
   briefs from the site, and `test_every_docs_page_is_in_nav` learns to honour `exclude_docs`.
   This is a protocol-adjacent change and ships as its own PR.

## Risks

- Audit variance: audit 3 may score differently for reasons unrelated to fixes. Mitigation: fixed
  weights, C's boomerang requires a merged PR behind any 3-point rise.
- Community held at 3 or 4 caps the mean. Mitigation stated in Goals; if audit 3 lands at 7.5 to
  7.9 overall with connector >= 8.0, report that plainly rather than stretch the rubric.
