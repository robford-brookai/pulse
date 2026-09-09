# Carry-over drafts, 2026-09-08

Drafts for the owner to send by hand. Nothing here has been sent. This file is written from two
PRs landing the same day (`docs-contract-decisions-2026-09-08` and
`docs-px-caution-and-environment-matrix-seed`) — if both merge, this section list is the union;
resolve the trivial merge conflict by keeping both sections.

## D6 sign-off requests (`rpc-object-model-assessment.md` §8.1, row `D6`)

D6 (BillingEpisode terminal boundary) was recorded resolved by Ford in the 2026-07-31 register
review, but the owner-confirmation checkboxes for Ethan and Tal are still unchecked. The
checkboxes stay unchecked in the doc — these are draft requests to get them checked, not the
edit itself.

### For Ethan

```text
Hi Ethan — closing the loop on D6 (BillingEpisode terminal boundary) from the 2026-07-31
register review. The resolution stands: PULSE ships `reported` as the v1 terminal state, with
`billed → reconciled` reserved behind config until a percent-of-collections contract requires
claim-outcome ingestion. As of 2026-09-08 we've confirmed no such contract exists or is
anticipated, so that's the only trigger that would reopen this. Can you reply here or on
DNA-897-style thread with a confirm, so I can check your box in §8.1 of
rpc-object-model-assessment.md?
```

### For Tal

```text
Hi Tal — same ask as Ethan's, for your D6 sign-off (BillingEpisode terminal boundary,
2026-07-31 register review). Resolution: PULSE stops at `reported`; `billed → reconciled` stays
reserved behind config, and reopens only if a percent-of-collections contract shows up — none
does today (2026-09-08). Can you confirm so I can check your box in §8.1 of
rpc-object-model-assessment.md?
```

## PX re-verify note (`survey-engine-ingress`, roadmap line ~184)

Draft for the owner to send to Max Pengilly (PX). Restates what pulse has already offered per
`docs/contracts/publishes.md:181-190`.

```text
Hi Max — following up on `survey-engine-ingress` timeline. Our roadmap still shows PX's
June–July delivery target, which has clearly passed (today is 2026-09-08). Two things:

1. Where does schema validation stand against the pulse, NPS, and CHF surveys? That's the gate
   on our side before we sequence the adapter build.
2. Can you give us a new delivery target now that validation is in progress (or say if it
   hasn't started)?

Reminder of what pulse already offers PX, so nothing here is a parallel build: the event
envelope and state catalog contracts (`design/platform/event-envelope-spec.md`,
`design/platform/state-catalog.md` — PX defines survey payloads against these, never a parallel
event schema), and the `s14-identity` deterministic matcher as a library read surface
(`pulse_ledger.identity`: `lookup_identifier`/`find_candidates`, digests only, never
demographics). Both are live today.

Let me know and I'll update the roadmap caution with a real date.
```
