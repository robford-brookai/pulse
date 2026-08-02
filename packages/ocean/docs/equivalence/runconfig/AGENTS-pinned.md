# Pinned persona roster for the 8.2 equivalence runs (DNA-774)

One eligible persona, every stochastic knob pinned, so the two transport runs
cannot diverge for persona reasons: a single persona removes the random claim
race (`compete_for_claim` orders candidates by `random.uniform` delay),
`outreach_approve_rate: 1.0` removes the post-LLM approve gate coin flip, and
`call_answer_rate: 1.0` with `missed_call_retry_count: 0` removes the unseeded
`random.random()` in call-simulator (constraint 2 of the 8.1 handoff).
Synthetic data only — no PHI.

```yaml
personas:
  - id: coordinator_pinned
    role: Care Coordinator
    claim_delay_seconds: [0, 0]
    outreach_approve_rate: 1.0
    call_answer_rate: 1.0
    missed_call_retry_count: 0
    retry_delay_seconds: 0
```
