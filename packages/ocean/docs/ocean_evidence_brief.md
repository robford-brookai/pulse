
# OCEAN Evidence Brief
 
This document lists every unsourced claim in the OCEAN leadership proposal and technical reference, where to source each one, and how to frame it if the data doesn't exist.
 
The rule: every load-bearing number must be sourced or explicitly flagged as unmeasured. "We cannot currently measure X" is a stronger argument for instrumentation than an unsourced estimate.
 
---
 
## Critical Evidence (blocks the leadership proposal)
 
### 1. Care alert volume: ~200 alerts/day
 
**Where to source:** POCAR database or Snowflake. Query `alert.created` count by day, trailing 30 days.
 
**What to report:** Daily mean, median, and range. Break down by alert type if possible.
 
**If unavailable:** "POCAR generates a high volume of care alerts daily. We do not currently have a reliable count because alert volume is not tracked outside the source system — which is itself an argument for event capture."
 
---
 
### 2. False positive rate: ~70%
 
**Where to source:** POCAR `alert.dismissed` or equivalent status field. Cross-reference with Snowflake if dismissal data is exported.
 
**What to report:** Percentage of alerts dismissed without patient contact, trailing 90 days. Break down by alert type and clinic if data supports it.
 
**This is the single most important number in the proposal.** If it's accurate, it justifies the entire pilot. If it's an estimate, say so: "Based on care team interviews, approximately 70% of alerts are dismissed without patient contact. We cannot confirm this precisely because alert outcomes are not tracked — the pilot will establish the actual baseline."
 
**If unavailable:** Interview 3–5 care team members. Ask: "Of every 10 alerts you see, how many result in a patient call?" Document the responses with names and dates.
 
---
 
### 3. Mean time from alert to patient contact
 
**Where to source:** Join POCAR alert timestamps with ZCC call logs in Snowflake (if both are exported). Match on patient_id.
 
**What to report:** Median time from `alert.created` to `call.started`, if joinable.
 
**If unavailable (likely):** This is the strongest argument for the pilot. State it directly: "We cannot currently measure the time between an alert firing and a patient being contacted. There is no structured link between POCAR alerts and ZCC call records. The OCEAN pilot creates this link."
 
---
 
### 4. Support ticket volume: ~30/day
 
**Where to source:** PAP/ExDash ticket counts from Snowflake, or direct database query.
 
**What to report:** Daily mean, trailing 30 days.
 
**If unavailable:** Drop the number or qualify: "approximately X per day based on [source]."
 
---
 
### 5. Engineering issue volume: ~15/day
 
**Where to source:** Linear issue creation count, trailing 30 days.
 
**What to report:** Daily mean.
 
**If unavailable:** Pull from Linear API or dashboard.
 
---
 
## Important Evidence (strengthens the argument)
 
### 6. Cross-team coordination cost
 
**Where to source:** Slack search. Find examples of care team members creating Slack threads or DMs to request engineering investigation of alert patterns.
 
**What to report:** 2–3 concrete examples with dates. E.g., "On [date], [nurse] posted in #care-escalations about a spike in missing glucose readings. It took [X days] to determine this was caused by [mobile app release / Impilo API change]."
 
**If unavailable:** Interview care ops leads. Ask: "Can you describe a recent situation where you needed engineering help to understand an alert pattern? How did you get that help?"
 
---
 
### 7. Service bus / unified ticketing prior attempts
 
**Where to source:** Internal documentation, Slack history, or team interviews.
 
**What to report:** If Brook has evaluated or attempted unified ticketing, cite the experience and outcome. If not, state that the "Why Events" argument is based on industry pattern rather than internal history.
 
---
 
### 8. Nurse-hours spent on false positives per week
 
**Where to source:** Derive from (alert volume × false positive rate × average triage time per alert). Get average triage time from care team interviews.
 
**What to report:** Estimated weekly hours spent triaging alerts that result in no patient action.
 
**If unavailable:** Even a rough estimate is valuable: "If 70% of 200 daily alerts are false positives, and each takes ~2 minutes to review and dismiss, that is approximately 4.5 nurse-hours per day spent on alerts that produce no patient value."
 
---
 
### 9. Operational graph validation questions
 
**Where to source:** Interviews with care ops leads, engineering leads, and customer success leads.
 
**What to ask:** These three questions test whether the operational graph (Phase 2) will deliver value. If staff can answer them today, find out how long it takes and what it costs. If they can't, that's the evidence.
 
- "How do you determine which alert types produce the most false positives?"
- "When a product release causes a spike in care alerts, how do you connect those two events?"
- "Which clinics generate alert patterns that require engineering investigation?"
**What to report:** Current answer method and time cost, or explicit inability to answer. Both are useful.
 
---
 
### 10. A concrete learning loop story
 
**Where to source:** Interview 2–3 care team members.
 
**What to ask:** "Can you describe a time when you called a patient because of an alert and discovered something unexpected — a device malfunction, a medication issue, a non-obvious root cause?" The source documents give a hypothetical: a call prompted by a missing glucose alert reveals a device battery failure. Find a real version of this story.
 
**What to report:** One concrete narrative: the alert, the call, the unexpected discovery, and what happened next. This single example makes the learning loop tangible for leadership in a way that metrics alone don't. If the outcome was never recorded anywhere, say so — that's the argument for OCEAN.
 
---
 
## Baseline Metrics (required before Phase 1 ships)
 
These don't need to be in the proposal, but must be established before the first phase launches. Without baselines, you can't measure improvement.
 
| Metric | Source | Notes |
|---|---|---|
| Alert volume by type | POCAR / Snowflake | Daily count, by alert_type |
| Alert dismissal rate | POCAR | Percentage dismissed without action |
| Alert → call time | POCAR + ZCC (if joinable) | Likely unmeasurable pre-OCEAN |
| Call completion rate | ZCC | Percentage of calls answered |
| Triage time per alert | Care team interviews | Stopwatch study or self-report |
| Engineering incident count | Linear | Daily, trailing 30 days |
| Integration issue count | PAP/ExDash | Daily, trailing 30 days |
 
---
 
## How to Handle Missing Data in the Proposal
 
Three patterns, in order of preference:
 
**1. Source the number.** "POCAR generated an average of 214 alerts/day in February 2026 (source: Snowflake `care_alerts` table)."
 
**2. Qualify the estimate.** "Based on care team interviews, approximately 70% of alerts are dismissed without patient contact. The OCEAN pilot will establish the precise baseline."
 
**3. Frame the gap as the argument.** "We cannot currently measure the time between an alert firing and a patient being contacted. This unmeasured gap is the core operational problem OCEAN solves."
 
Pattern 3 is often more persuasive than pattern 1. An organization that can't measure its own care response time has a self-evident case for instrumentation.
 
---
 
## Action Items
 
1. Pull alert volume and dismissal data from POCAR/Snowflake (items 1, 2).
2. Attempt alert-to-call join in Snowflake (item 3). If it fails, document why.
3. Pull ticket and issue counts (items 4, 5).
4. Interview 3 care team members for cross-team coordination examples (item 6), triage time estimates (item 8), and a concrete learning loop story (item 10).
5. Interview care ops, engineering, and CS leads with the three operational graph validation questions (item 9).
6. Update the leadership proposal with sourced numbers or reframed gaps.
7. Remove all `<!-- EVIDENCE NEEDED -->` comments before publishing.