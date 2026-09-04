# 5. AI-Assisted Operations

## Purpose

AI-Assisted Operations introduces machine intelligence into the operational workflow while preserving **human clinical authority and regulatory safety**.

In OCEAN, AI is a **copilot** for care operations, not an autonomous decision-maker.

Core principle:

> **AI recommends. Humans decide. Systems record.**

This ensures:

- HIPAA-aligned safeguards
- clinician oversight
- explainable workflows
- auditability of AI outputs
## Roles of AI in the System

AI should perform three operational roles:

1. Summarization
2. Recommendation
3. Draft generation
AI should **not** execute clinical actions autonomously.

## 1) Alert Summarization

Care alerts often contain fragmented context (signals, missed measurements, patient messages, historical context). AI can summarize this into a nurse-readable brief.

Example input:

```text
Patient: John Doe
Signals:
- Missing glucose reading (today)
- High glucose reading (yesterday)
- Message: "Feeling dizzy"
```

Example output:

```text
Summary:
Patient missed today's glucose reading after elevated reading yesterday.
Patient reported dizziness via message.
Recommend nurse follow-up call.
```

## 2) Workflow Recommendations

AI can suggest next actions based on operational context.

Example:

```text
Context:
Alert: Missing glucose readings
Patient history: medication confusion last week
```

Recommendation:

```text
Suggested actions:
- Call patient to verify device usage
- Review insulin instructions
```

Recommendations appear in Slack as decision support, not automation.

## 3) Drafting Patient Communications

AI may draft SMS/portal messages, but a human must review and approve before sending.

Example draft:

```text
Hi John — we noticed a missing glucose reading today.
Could you please check your device and send a reading when possible?
If you're having trouble, we're happy to help.
```

## Safety Requirements

### Human-in-the-loop

Require human approval for:

- patient communication
- clinical workflow actions (e.g., closing an alert)
- escalations and clinical decisions
### Transparency

AI outputs should include:

- brief reasoning summary
- source signals used
- confidence indicator
Example:

```text
AI confidence: Medium
Signals used:
- Missing glucose reading
- Previous elevated reading
- Patient message
```

### Audit logging

All AI activity must generate events:

```text
ai.summary.generated
ai.recommendation.generated
ai.response.drafted
ai.output.approved
ai.output.rejected
```

These events support regulatory auditing, model monitoring, and safety review.

## Context Retrieval (RAG)

To reduce hallucinations, AI should use **structured context retrieval**.

Primary source: the **Operational Data Graph** (Section 3), plus curated policy/protocol documents.

Example retrieval bundle:

```text
Patient context:
- last 5 alerts
- recent interactions
- open tasks
- relevant clinic protocol reference
```

## Knowledge Base Integration

The AI layer should retrieve relevant documents to support decision support:

- clinical care protocols
- patient communication guidelines
- device troubleshooting instructions
- operational playbooks
These may be stored in Snowflake and/or indexed in a vector store.

## Learning from Outcomes

AI improves when outcomes are recorded.

```text
AI recommendation → human action → outcome recorded
```

Example:

```text
Recommendation: call patient
Outcome: device battery failure identified
```

Over time, this supports reduced false positives and better triage suggestions.

## AI Architecture (Practical)

```text
Operational Data Graph
  ↓
Context retrieval
  ↓
LLM inference API
  ↓
AI assist service
  ↓
Slack interface
```

The AI assist service handles prompt construction, context retrieval, output formatting, and audit logging.

## Privacy and HIPAA Compliance

Key requirements:

- encrypted data transport
- secure model endpoints
- restricted PHI access
- audit logs for AI outputs and approvals
- role-based access controls
Minimize PHI exposure in prompts wherever possible.

## Operational AI Boundaries

AI must never:

- prescribe medication
- make autonomous care decisions
- send patient communications without approval
- modify patient records without human review
AI is limited to decision support and workflow assistance.

## Benefits

When implemented correctly, AI reduces cognitive load, speeds triage, improves documentation, and helps drive down false positives — while keeping clinical authority with the care team.
