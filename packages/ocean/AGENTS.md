# OCEAN simulated-operator personas

Persona roster for `services/agent-worker`, which simulates coordinator behavior against
live ticket and outreach queues. `src/personas.py::load_personas` parses the fenced YAML
block below; `services/agent-worker/Dockerfile` copies this file to `/app/AGENTS.md`.

This file was lost in the OCEAN absorption into pulse and reconstructed from the values
pinned by `services/agent-worker/tests/test_personas.py` (task 4.14, DNA-781). It is
data, not agent instructions — synthetic personas only, no PHI.

```yaml
personas:
  - id: coordinator_alice
    role: Senior Care Coordinator
    claim_delay_seconds: [15, 90]
    outreach_approve_rate: 0.85
    call_answer_rate: 0.80
    missed_call_retry_count: 1
    retry_delay_seconds: 120
  - id: coordinator_bob
    role: Care Coordinator
    claim_delay_seconds: [60, 300]
    outreach_approve_rate: 0.60
    call_answer_rate: 0.60
    missed_call_retry_count: 0
  - id: ops_lead_carol
    role: Operations Lead
    human_escalation_responder: true
```
