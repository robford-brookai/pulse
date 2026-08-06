# Runbook: identity-quarantine

Operator actions for the `quarantine_reviewer` role draining `ledger.review_queue`
(`design/delivery/pulse-runtime-readiness.md` §3.3, "Quarantine reviewer") — Slack severity: queue
depth and age are a monitored trend (§1's monitor set), not a page; this is reviewer workload, not
an incident. A row lands here whenever `identity.matcher.resolve` returns `Ambiguous`: two or more
candidate persons for one referral, and v1 never auto-chooses between them (`packages/identity`,
task 3.1) — the accepted cost is human workload, never a wrong merge in a HIPAA system. The queue
itself is `pulse_ledger.review` (`list_review_queue`, `count_pending`, `resolve_review`); the hold
that put the referral there is `identity.resolver.quarantine`.

## Reading an evidence record

Every queued row is a `ReviewItem` (`pulse_ledger.review.ReviewItem`):

| Field | Meaning |
| --- | --- |
| `review_id` | The queue row's own key — pass this to `resolve_review` to drain it. |
| `subject_type` / `subject_key` | The held subject: `"referral"` and the referral's pseudonymous key. Never a demographic value. |
| `hold_event_id` | The committed `resolution_hold` fact (`identity.resolver.HOLD_EVENT_TYPE`) that holds the referral in `received` with no `to_state`. |
| `candidates` | The two-or-more pseudonymous person keys the matcher found — **person keys only, no demographic field ever reaches this row** (task 4.2). |
| `pending` | `False` once a reviewer has drained it. |
| `resolved_at` / `resolution_event_id` | Set together when `resolve_review` names the command event that closed the row. |

The candidates are keys, not evidence. To see *why* the referral quarantined — which fields
matched, which rule id decided, how many candidates — read the `resolution_hold` fact named by
`hold_event_id`: its `evidence` carries `matched_fields` (names only), `rule_id` (one of
`identifier_conflict` or `composite_ambiguous` — the two rule ids that quarantine; see
`docs/contracts/publishes.md` for the full rule id list), and `candidate_count`. That evidence is
what a reviewer reconstructs the decision from — never by re-running the matcher, and never by
looking up a candidate's demographics outside the ledger's own tooling.

## Disposition commands per outcome

A reviewer resolves ambiguity by looking at the candidates through whatever tooling exposes
person records (outside this package's scope — this runbook covers the command side only), then
declares one of three outcomes through the ordinary command API
(`pulse_core.client.PulseCoreClient.submit_command`, never a direct table write). In every case,
the resolving command's returned `event_id` is the `resolution_event_id` passed to
`resolve_review` — that is what proves the queue row closed by an actual declared correction, not
a flag flip.

1. **One candidate is correct.** Declare `resolve_referral` (subject: the referral, `person_key`:
   the chosen candidate). If the referral carries identifiers that candidate does not already
   hold, declare `attach_identifier` for each, same as the automated `Match` path
   (`identity.resolver.act`). Then `resolve_review(review_id, reviewer_role="quarantine_reviewer",
   resolution_event_id=<resolve_referral's event_id>)`.
2. **None of the candidates are correct.** Declare `mint_person`, then `resolve_referral` to the
   new person, then `attach_identifier` for every referral identifier, in that order — the same
   sequencing the automated `Mint` path uses and for the same reason: the referral must never
   resolve to a person that does not exist yet. Resolve the review against the `resolve_referral`
   event.
3. **The candidates are the same person under two records.** This is not a referral-resolution
   decision — it is a data-quality correction to the person records themselves. See
   [merge-by-command](#merge-by-command-correction-path) below.

Every disposition command is an ordinary ledger command: it carries its own D16 idempotency key
and goes through the same `committed \| replayed \| rejected \| transient` classification as any
other write. A `rejected` disposition (for example, an identifier already held by a different
person) is not fixed by retrying the same command — resolve the underlying conflict first, the same
as any other rejected command.

## Merge-by-command correction path

When the candidates are duplicate records for one real person, the correction is `merge_person`
(`pulse_core.generated.MergePersonCommand`) — **S1.1's command, linked here, not rebuilt.** This
package declares no merge logic of its own; the reviewer submits:

```
MergePersonCommand(subject_key=<survivor_key>, survivor_key=<survivor_key>,
                    duplicate_key=<duplicate_key>, evidence_ref=<review_id>)
```

`evidence_ref` is how the merge stays traceable back to the review row that triggered it — pass
the `review_id` (or the review's own audit reference, if the tooling that generates one is in
place) so the ledger's record of the merge names the quarantine it resolved. After the merge
commits, declare `resolve_referral` against the survivor key (attaching any identifiers the
survivor does not already hold), and resolve the review against that `resolve_referral` event —
same as outcome 1 above, now that the duplicate is gone.

If more than two candidates were queued and only some are duplicates of each other, merge the
duplicates pairwise down to one survivor before resolving the referral — `merge_person` takes one
survivor and one duplicate per call.

## Re-run posture

Re-processing an already-quarantined referral is safe: `identity.resolver.quarantine` derives its
hold's idempotency key from the triggering event, so a redelivered event replays the same hold
fact rather than committing a second one, and `pulse_ledger.review.quarantine_subject` refuses a
second row for a subject already pending (`SubjectAlreadyPendingError`) — the existing review is
returned, not duplicated. Disposition commands carry the same replay guarantee: retrying a
disposition after a crash between the command and `resolve_review` reproduces the same event and
`resolve_review` closes the row exactly once (`AlreadyResolvedError` on a second attempt against an
already-resolved row is expected, not a bug).

## PHI posture

Queue rows, hold-fact evidence, and every disposition command carry pseudonymous person keys,
field names, and rule ids only — never a demographic value. A reviewer's own tooling for looking
up a candidate's underlying record (outside this package) is where PHI is legitimately viewed
under the ledger's own access controls; nothing in this runbook's command path, logging, or queue
schema should ever need to carry one. If any log line or queue row shows a demographic value,
treat it as a PHI incident: capture the record's timestamp and logger name, and escalate per the
security review process before sharing it anywhere.
