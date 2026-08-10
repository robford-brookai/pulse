# Prompt for Claude Cowork — PULSE demo presenter artifact

Copy everything below the line into Cowork.

---

Build me an executable HTML artifact: a presenter console for a live engineering demo I am giving today (2026-08-10) over screen share. It guides me through the demo step by step with a talk track, timers, and copy-paste commands. Single self-contained page, dark-theme friendly, large type readable on a shared screen at 1080p.

## Context (for tone, not for display)

I am pitching PULSE (Patient Unified Ledger of State and Events) to six engineers as the event backbone for the brook.ai analytics platform, built on our existing Snowflake + AWS/Duplo data platform. Framing rules the artifact must respect: it is an event backbone, NOT a replacement user interface; it is NOT pilot-ready (2 of 5 phases shipped) — the pitch is "the hard bits already work elegantly." Audience: Andrew, Carin, Eric, Constantine, David, Max. Everything shown is synthetic data (Synthea) — no real patient data exists anywhere in the system.

## What the artifact is

A single-page presenter console with:

1. **A step sequencer** — Next/Back buttons and keyboard arrows moving through the demo beats listed below. Each beat shows: a big headline (what the audience should take away), my talk track (2–4 sentences, spoken register, visible only in a collapsible "presenter notes" panel), the exact shell command to run (in a copy-on-click code block), and the expected output (so I can confirm at a glance the live run matches).
2. **A running clock and per-beat suggested duration**, with a subtle over-time indicator. Total budget 20 minutes.
3. **A links rail** — always-visible sidebar with the reference links below, each opening in a new tab.
4. **A fallback panel per beat** — a "if the live run breaks" toggle showing the rehearsal receipt for that beat (I rehearsed green on 2026-08-09; receipts included below), so I can narrate from the receipt instead of debugging live.
5. No external network calls, no CDN — fully self-contained.

## Links rail (exact URLs)

- Repo: https://github.com/robford-brookai/pulse
- v2.0 release (Phase 2 — Ingress, 2026-08-08): https://github.com/robford-brookai/pulse/releases/tag/v2.0
- v1.5 release (Phase 1 — Ledger Core, 2026-08-04): https://github.com/robford-brookai/pulse/releases/tag/v1.5
- Discussion guide PR: https://github.com/robford-brookai/pulse/pull/192
- Linear issue: https://linear.app/brook-health/issue/DNA-900/pulse-data-priority
- Demo 1 runbook (in repo): docs/runbooks/demo1-ledger-core.md
- Kanban webhook runbook: docs/runbooks/twenty-webhook.md
- Identity/quarantine runbook: docs/runbooks/identity-quarantine.md

## Demo beats

**Beat 0 — Setup (before the meeting, not narrated).** Command: `docker compose -f packages/ocean/infra/docker-compose.yml up -d --wait` from the repo root. Note: stack may already be up from rehearsal — if `docker ps` shows infra-ledger-relay-1 healthy, skip.

**Beat 1 — The one-slide idea (2 min).** No command. Talk track: every system keeps its UI and its database; when something true happens it makes one API call; the ledger keeps everything append-only; analytics, screens, and webhooks are all projections. Today when dashboards disagree we hold a debate — after this, we hold a replay.

**Beat 2 — A legal event commits and lands on the queue (3 min).** Command: `uv run python scripts/demo/demo1_ledger_core.py` (runs all four assertions; beats 2–5 narrate its output as it scrolls). Expected line:
```
[1/4] legal command commits and lands on the queue
  committed event 7e602558-... (referral/... -> received)
  observed on http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ocean-event-store
```
Talk track: one call, validated, attributed, durable, and already on the AWS transport our platform runs on.

**Beat 3 — Governance that cannot drift (4 min).** Expected line:
```
[2/4] illegal command rejects with catalog reason + version
  rejected: illegal transition for 'referral': 'received' -> 'outreach'
  is not in the catalog adjacency (catalog 1.0.0)
```
Talk track: the state machine lives in one versioned YAML file, changed only by pull request; CI code-generates the enforcement. The rejection names the rule and the catalog version that killed it. There is no meeting where the code and the spec disagree.

**Beat 4 — Exactly-once over an at-least-once world (3 min).** Expected line:
```
[3/4] replay returns the original event id (exactly one event)
  original event 0efaf5f7-...; replay returned the same id; 1 event stored
```
Talk track: retries, timeouts, and double-clicks are where event systems corrupt. Same idempotency key twice, one event, original id back. Safe by construction, not by discipline.

**Beat 5 — Provable state under messy history (5 min, the closer).** Expected line:
```
[4/4] independent fold equals current_state (wraps the 5.1 harness)
  independent fold ('closed', 2026-08-01T00:42:22Z, ...) == current_state (referral/...)
```
Talk track: we run a deliberately ugly history — forward events, a backdated correction, a reversal — then recompute state from raw events, from scratch, and it must equal the stored answer. This is the property that ends dashboard arguments: anyone in this room can re-derive the number.

**Beat 6 — Held in reserve (only if asked "what about people?").** Two optional runs: `uv run python scripts/demo/demo2_kanban_drag.py` (a signed drag on the ops board becomes an attributed command; an invalid drag gets a rejection receipt written back onto the card) and `uv run python scripts/demo/demo2_identity_matcher.py` (ambiguous humans are never auto-merged — conflicts route to a quarantine queue). Talk track: elegant failure is the feature — the system says no, says why, and keeps the receipt.

**Beat 7 — The ask (3 min).** No command. Talk track: not asking for a pilot — we are two phases into five. Asking for three things: pressure-test the shape, name the first system to declare events natively, and tell me what proof makes this an easy yes for your team.

## Guardrails

- Do not invent additional claims, metrics, or links beyond what is in this prompt.
- Presenter notes are for me — write them in first person, spoken register, no corporate filler.
- If any expected-output block must be truncated for layout, keep the semantically loaded fragment (the rejection reason, the "1 event stored", the fold equality) intact.
