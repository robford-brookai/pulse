# OCEAN Document Suite — Diagnostics
 
Three tailored evaluations, one per document. Each diagnostic is calibrated to the document's purpose, audience, and genre — not measured against a universal standard.
 
---
 
# Diagnostic 1: Leadership Proposal
 
## Modified Evaluation Criteria
 
This document is an **internal strategic proposal** for executives and team leads. It must persuade decision-makers to endorse a direction and set the tone for a public roadmap. It is not a research paper, a technical specification, or a project plan.
 
The diagnostic evaluates against seven dimensions recalibrated for this genre:
 
1. **Thesis clarity** — Can the reader state the proposal's ask in one sentence after reading?
2. **Audience alignment** — Does every section serve executives and team leads? Is anything present that only engineers would value?
3. **Argument architecture** — Does the document build from problem → insight → solution → plan → risk → ask? Does each section make the next section feel inevitable?
4. **Evidence and credibility** — Are claims sourced, qualified, or honestly framed as gaps? Does the author demonstrate operational understanding, not just architectural ambition?
5. **Signal-to-noise ratio** — Is every paragraph doing persuasive or informational work? Could anything be cut without weakening the case?
6. **Persuasive trajectory** — Does the document create momentum? Does the reader feel more convinced at the end than the beginning?
7. **Voice and authority** — Does the author sound like someone who has done the work and owns the direction? Or does it read like a committee document?
---
 
## One-Sentence Verdict
 
The proposal is a well-structured strategic case that earns its length — but it hasn't yet earned its numbers.
 
## Intended vs. Actual Effect
 
| | Intended | Actual |
|---|---|---|
| Audience | Executives, team leads | Executives, team leads (correct) |
| Takeaway | "This is the right direction" | "This is a credible direction, pending evidence" |
| Action | Endorse and align | Likely to ask "how do we know the 70% number is real?" |
 
## Diagnostic by Dimension
 
### 1. Argument Architecture — STRONG
 
The document moves problem → transformation goal → architectural insight → system overview → pilot → phased roadmap → team/tech → safety → governance → metrics → risks → closing. This is textbook proposal structure. Each section earns the next: the problem makes the insight feel necessary, the insight makes the architecture feel logical, the pilot makes the roadmap feel grounded. The before/after statement ("alerts → operational chaos" to "signals → tasks → actions → outcomes → learning") is well-placed as a bridge between problem and solution. The Stripe/Airbnb/Uber/Amazon comparison legitimizes the category without overselling.
 
**One weakness:** The "What OCEAN Looks Like" section (system flow diagram + five principles) sits between the architectural insight and the pilot. For a leadership audience, the system flow diagram is the least useful section — it's an engineering artifact. The five principles are good; the ASCII diagram could be cut or moved to an appendix without loss.
 
### 2. Thesis Clarity — STRONG
 
The thesis is clear and stated multiple times without feeling repetitive: Brook needs an event-driven operational layer that wraps existing tools, starts with the care alert loop, and builds toward a learning system. The bottom line restates it cleanly. The reader can articulate the ask after reading the first three sections.
 
### 3. Audience Alignment — STRONG
 
This is the biggest improvement over the original single document. Every section speaks to decision-makers. No JSON payloads, no Postgres column names, no CI/CD pipelines. The engineering insight bot example in Phase 3 is at exactly the right altitude — concrete enough to be vivid, abstract enough that a non-engineer follows it. The governance and risk sections are pitched at the right level of detail.
 
**One residual misalignment:** The `signal.received → alert.created → task.created → task.claimed → call.completed → alert.resolved` event chain in the pilot section is borderline. It's useful for showing the completeness of the instrumentation, but it's the most "engineering" artifact in the document. Consider whether the current/future workflow comparison already makes the point without the event chain.
 
### 4. Evidence and Credibility — FUNCTIONAL (but blocking)
 
The document is honest about its evidence gaps — the `<!-- EVIDENCE NEEDED -->` comments and the "What we cannot currently measure" framing are genuinely good rhetorical moves. Framing unmeasured metrics as the problem itself is more persuasive than unsourced estimates.
 
However, the HTML comments are still visible in the rendered document. This is a publishing hygiene issue, not a structural one, but it undermines authority — it tells the reader the document is a draft.
 
The cross-department examples (Care → Engineering, Engineering → Care, Care → Outcome) are specific enough to feel observed rather than invented. Good.
 
The 70% false positive rate remains the load-bearing number. If a skeptical executive challenges it, the proposal currently has no defense. The evidence brief provides the remedy, but until it's executed, this dimension remains the document's biggest vulnerability.
 
### 5. Voice and Authority — STRONG
 
The voice is consistent: pragmatic, direct, informed. "This is not a tools problem. It is a coordination problem." "The hardest part is not the technology." "OCEAN is not a speculative platform bet." These read as someone who has thought through the problem and is making a recommendation, not presenting options. The closing paragraph — "operational questions that once required hours of investigation become answerable instantly" — lands well because it's concrete, not aspirational.
 
### 6. Signal-to-Noise Ratio — STRONG
 
At ~1,864 words, the document is tight. No section feels redundant. The technology section is appropriately compressed (one paragraph). HIPAA/safety is three paragraphs. Governance is a half-page. The pre-mortem is the right length — long enough to show seriousness, short enough to not become the focus.
 
**One area of slight excess:** The OCEAN acronym breakdown adds ~5 lines that don't do much persuasive work. The reader doesn't need to know what the letters stand for to understand the proposal. Consider cutting or moving to a footnote.
 
### 7. Persuasive Trajectory — FUNCTIONAL
 
The document builds well through the first half (problem → insight → system → pilot). The phased roadmap is solid. But the second half (technology → HIPAA → governance → metrics → risks → bottom line) is a sequence of necessary-but-unexciting sections that flatten the momentum. The reader's energy peaks at the pilot section and then gradually dissipates through compliance and governance.
 
The "learning while building" insertion after Phase 6 helps. The stronger closing paragraph helps more. But the structural issue is that the most exciting content (the problem, the insight, the pilot, the engineering correlation example) is front-loaded, and the back half is procedural.
 
**Possible fix:** Move the pre-mortem (currently second-to-last) earlier — perhaps right after the phased roadmap. Risk awareness is persuasive; compliance sections are not. End on metrics → bottom line, not risks → bottom line.
 
## The Three Biggest Fixes
 
### 1. Fill the evidence gaps and remove HTML comments
 
What's wrong: The document's strongest rhetorical move (framing unmeasured gaps as the problem) coexists with draft-stage HTML comments that signal "not ready." The 70% false positive rate is still undefended.
 
What to do: Execute the evidence brief. Source the numbers or reframe the gaps. Remove all `<!-- -->` comments. This is the only blocking fix.
 
Expected effect: The document becomes publishable and defensible under questioning.
 
### 2. Reorder the back half for momentum
 
What's wrong: The document peaks at the pilot/roadmap and then flattens through compliance and governance sections.
 
What to do: Reorder to: Phased Roadmap → What Can Go Wrong → Technology and Team → Governance → HIPAA and Safety → How We Measure Success → Bottom Line. This puts the pre-mortem (persuasive) earlier and the compliance sections (necessary but dull) later, ending on measurement and vision.
 
Expected effect: The reader's engagement doesn't drop after the roadmap.
 
### 3. Cut or compress the system flow diagram
 
What's wrong: The ASCII system flow diagram is an engineering artifact in a leadership document. It's the one section where the audience alignment breaks.
 
What to do: Either cut it entirely (the five principles and the pilot section already communicate the architecture at the right altitude) or replace it with a one-sentence summary: "Events flow from department tools through a shared backbone into a queryable graph, surfaced via Slack, with AI assistance and analytics."
 
Expected effect: The document stays at leadership altitude throughout.
 
## What's Actually Working
 
The problem section is the best part of the document — "the problem is between the tools" is a memorable framing, the cross-department examples are vivid and specific, and the "what we cannot currently measure" list is more persuasive than sourced numbers would be. The pre-mortem section is the second strongest — ranking failure modes by likelihood shows operational maturity that builds trust. These two sections should be preserved exactly as written through any revision.
 
## Revision Priority
 
Targeted fixes, not a restructure. The architecture is sound. Execute the evidence brief (fix #1), reorder the back half (fix #2), and decide on the system flow diagram (fix #3). These are half-day edits, not a rewrite.
 
---
---
 
# Diagnostic 2: Technical Reference
 
## Modified Evaluation Criteria
 
This document is an **engineering implementation reference** for the ~5-engineer team that will build OCEAN. It must enable correct implementation decisions without requiring the reader to consult external sources. It is not a proposal, not a persuasive document, and not a tutorial.
 
The diagnostic evaluates against seven dimensions calibrated for reference documentation:
 
1. **Completeness** — Can an engineer implement each component using only this document (plus standard library/tool docs)? Are there gaps where the engineer would have to guess?
2. **Internal consistency** — Do schemas, event names, entity names, and technology choices stay consistent across sections? Do cross-references hold?
3. **Decision clarity** — When the document presents choices (e.g., Hasura vs. thin GraphQL service), does it state a recommendation or decision criteria? Or does it leave the engineer to decide without context?
4. **Navigability** — Can an engineer find the answer to a specific question quickly? Is the document organized by concern (events, objects, graph, control plane, etc.) or does it require reading the whole thing?
5. **Appropriate abstraction level** — Is the document at the right altitude for implementation? Too abstract = engineer has to invent details. Too concrete = document becomes brittle and outdated.
6. **Operational realism** — Does the document account for failure modes, edge cases, and production concerns? Or does it describe only the happy path?
7. **Signal-to-noise ratio** — Is every section doing reference work? Is anything present that belongs in the leadership proposal or a tutorial?
---
 
## One-Sentence Verdict
 
A well-organized reference that is strong on taxonomy and structure but underspecified on the components engineers will actually struggle with: the rule engine, the graph projection, and the connector contracts.
 
## Intended vs. Actual Effect
 
| | Intended | Actual |
|---|---|---|
| Audience | 5-engineer implementation team | Implementation team (correct) |
| Takeaway | "I know what to build and how the pieces connect" | "I know the data model and event taxonomy, but I'll need to figure out the rule engine and connectors myself" |
| Action | Start implementing Phase 1 | Start implementing event ingestion; schedule design sessions for control plane rules |
 
## Diagnostic by Dimension
 
### 1. Completeness — FUNCTIONAL
 
The document fully specifies: event taxonomy (all six domains, all event types, envelope standard), operational object model (all eight entities, attributes, relationships), graph structure (nodes, edges, materialization pattern), system flow, technology stack, repository structure, deployment progression, observability metrics, reliability patterns, and runbooks.
 
The document underspecifies three areas that will generate the most implementation questions:
 
**Rule engine.** Section 4 shows two example rules in pseudocode but doesn't specify: How are rules stored? How are they evaluated (event-at-a-time vs. windowed)? How are they versioned? How do you test a rule before deploying it? For v1, "Python rule engine" is the recommendation, but there's no contract — an engineer doesn't know whether to write an `if/elif` chain, a declarative rule DSL, or a table-driven evaluator.
 
**Connector contracts.** Section 6 lists sources (Impilo, POCAR, ZCC, etc.) but doesn't specify: What is the interface contract for a connector? What does a connector publish — raw events, normalized events, or both? What happens when a source webhook is down? The "isolated connector services" pattern is stated but not defined.
 
**Graph projection logic.** Section 3 shows three event→graph mappings but doesn't specify: What happens when events arrive out of order? What if an `alert.created` event arrives after the `task.created` event that references it? Are projections idempotent by default or does the engineer need to handle this per-entity?
 
### 2. Internal Consistency — STRONG
 
Event names are consistent across all sections. Entity names match between the object model, graph, and control plane. Technology choices are stated once in the baseline and referenced thereafter without contradiction. The `correlation_id` field appears in the envelope (Section 1) and is referenced in observability (Section 7) — good end-to-end traceability.
 
One minor inconsistency: Section 1 lists `ai.feedback.recorded` in the AI Operations event table, while Section 5 lists `ai.output.approved` and `ai.output.rejected` as separate events. Both appear in the Section 1 table as well, making `ai.feedback.recorded` potentially redundant or overlapping. The relationship between these three events should be clarified — is `ai.feedback.recorded` a parent category, or a separate event?
 
### 3. Navigability — STRONG
 
The document is organized by architectural concern (taxonomy → object model → graph → control plane → AI → blueprint → operations). An engineer looking for "how do I handle a Slack outage" can go directly to Section 7 Runbooks. An engineer looking for "what events does the care team generate" can go to Section 1. Cross-references are clean ("See Section 5 for safety boundaries").
 
### 4. Appropriate Abstraction Level — FUNCTIONAL
 
The event taxonomy and object model are at the right altitude — specific enough to implement, abstract enough to evolve. The production operations section (deployment, CI/CD, observability, reliability, runbooks) is at the right altitude for a team that knows how to operate services.
 
The control plane and connector sections are too abstract. They describe *what* the components do but not *how* they should be built. For a five-engineer team without a dedicated architect, the gap between "Python rule engine" and a working rule evaluation system is significant.
 
### 5. Operational Realism — STRONG
 
The runbooks section is concrete and specific (connector down, consumer lag, Slack outage, ZCC outage). The failure isolation section in the control plane is good. The reliability patterns (idempotency, DLQ, schema versioning) are the right patterns for this architecture. The cost management section for AI is practical. The "temporarily disable non-critical consumers to protect core care workflows" advice shows operational maturity.
 
### 6. Decision Clarity — FUNCTIONAL
 
Some decisions are clear: Redpanda over NATS (listed first, used in all examples), Postgres for operational data, Snowflake for analytics, Python/FastAPI for services.
 
Some decisions are deferred without criteria: "Hasura or thin GraphQL service" — when should you pick which? "pgvector, Weaviate, or Pinecone" for vector store — what factors should drive the choice? "Python or Node.js" for the Slack bot — why would you choose one over the other when the rest of the stack is Python?
 
For a five-engineer team, every deferred decision is a meeting. State a default and the conditions under which you'd deviate.
 
### 7. Signal-to-Noise Ratio — STRONG
 
At ~2,921 words, the document is dense with reference content. No section feels like filler. The de-duplication from the original is well-done — HIPAA stated once, AI safety canonical in Section 5, care loop not repeated across sections. The design priorities section (edit #6) is a useful decision framework that earns its space.
 
## The Three Biggest Fixes
 
### 1. Specify the connector contract
 
What's wrong: Engineers will start building connectors in Phase 1 without a shared interface pattern. Each engineer will invent their own structure.
 
What to do: Add a subsection to the implementation blueprint defining: connector interface (input: source webhook/poll → output: canonical event on backbone), error handling contract (retry policy, backfill mechanism, health endpoint), and a skeleton example for one connector (e.g., Impilo).
 
Expected effect: Phase 1 connectors are structurally consistent from day one.
 
### 2. Specify the rule engine contract for v1
 
What's wrong: "Python rule engine" is a technology choice, not a design. The control plane is the most complex service in the system and has the least specification.
 
What to do: Add a subsection specifying: how rules are represented (code, config, or DSL), how they're evaluated (event triggers → rule match → action), how they're tested (unit test pattern for a rule), and how they're deployed (with the service, or as separate config). Include one fully worked rule from event input to task output.
 
Expected effect: The control plane doesn't become a design-by-committee project during implementation.
 
### 3. State default technology choices and deviation criteria
 
What's wrong: "Hasura or thin service," "pgvector or Weaviate or Pinecone," "Python or Node.js" — each deferred choice costs meeting time.
 
What to do: For each either/or, state the default recommendation and one sentence on when to deviate. E.g., "Default: Hasura. Deviate if query patterns require custom resolvers that Hasura can't express, or if the team already has a GraphQL service pattern they prefer."
 
Expected effect: Engineers can start building without scheduling architecture reviews for decisions that don't matter yet.
 
## What's Actually Working
 
The event taxonomy (Section 1) is the strongest section — it's complete, consistent, well-exemplified, and immediately implementable. The end-to-end event flow example (signal.missing → alert.resolved) is the single best artifact in the document because it shows how the taxonomy works as a system, not just a catalog. The production operations section (Section 7) is unusually good for an architecture document — most teams don't write runbooks until they need them.
 
## Revision Priority
 
Targeted additions to three underspecified areas (connector contract, rule engine contract, technology defaults). No restructuring needed. The document's organization and de-duplication are sound. Estimated effort: one focused writing session per addition.
 
---
---
 
# Diagnostic 3: Evidence Brief
 
## Modified Evaluation Criteria
 
This document is a **research and data-gathering action plan** for the author (and possibly a data analyst or ops lead). It must enable someone to execute the evidence-gathering work without further instruction, and produce results that can be directly inserted into the leadership proposal.
 
The diagnostic evaluates against seven dimensions calibrated for this genre:
 
1. **Actionability** — Can someone execute each item without asking follow-up questions? Are the queries, interview questions, and data sources specific enough?
2. **Prioritization** — Is it clear which items are blocking vs. nice-to-have? Does the ordering match the urgency?
3. **Completeness** — Does the brief cover every unsourced claim in the leadership proposal? Are there claims in the proposal that the brief misses?
4. **Output specification** — For each item, is it clear what the deliverable looks like? Can the person doing the work know when they're done?
5. **Fallback quality** — When data isn't available, are the fallback framings actually usable in the proposal? Do they sound like polished prose or like placeholders?
6. **Integration guidance** — Does the brief explain how to insert the evidence into the proposal? Or does it leave a gap between "data gathered" and "proposal updated"?
7. **Scope discipline** — Does the brief stay focused on evidence for the proposal, or does it expand into general research that doesn't serve the document?
---
 
## One-Sentence Verdict
 
A well-prioritized evidence plan with strong fallback framings — but it underspecifies the interview protocol and doesn't close the loop on how gathered evidence maps back to specific locations in the proposal.
 
## Intended vs. Actual Effect
 
| | Intended | Actual |
|---|---|---|
| Audience | The author, possibly a data analyst or ops lead | Correct |
| Takeaway | "I know exactly what to gather and where to put it" | "I know what to gather, but I'll need to figure out the interviews and insertion points myself" |
| Action | Execute the 7 action items | Execute items 1–3 (data pulls) immediately; schedule interviews but need to plan the protocol |
 
## Diagnostic by Dimension
 
### 1. Prioritization — STRONG
 
The critical/important split is correct. Items 1–3 (alert volume, false positive rate, alert-to-call time) are correctly identified as blocking the leadership proposal. Items 4–5 (ticket and issue counts) are correctly positioned as important but not blocking. Items 6–10 are correctly positioned as argument-strengthening. The "single most important number" callout on the false positive rate is useful — it tells the person doing the work where to invest the most effort.
 
### 2. Fallback Quality — STRONG
 
This is the brief's best dimension. The fallback framings are not placeholders — they're polished prose ready for insertion. "We cannot currently measure the time between an alert firing and a patient being contacted. There is no structured link between POCAR alerts and ZCC call records. The OCEAN pilot creates this link." That's a better argument than a sourced number would be. The "How to Handle Missing Data" section with three ranked patterns (source → qualify → frame the gap) is a genuinely useful framework.
 
### 3. Completeness — STRONG
 
Cross-referencing the leadership proposal against the brief: every `<!-- EVIDENCE NEEDED -->` comment maps to a brief item. The cross-department examples (Care → Engineering, Engineering → Care, Care → Outcome) in the proposal are not flagged in the brief, but they read as observed patterns rather than data claims, so this is appropriate. The success metrics section is covered by the baseline metrics table.
 
One gap: the Stripe/Airbnb/Uber/Amazon comparison in the proposal is an unsourced architectural claim ("each built internal event-driven operational platforms"). The brief doesn't address this. It's not a data claim, but a skeptical executive could ask "where's the evidence that these companies built what you're describing?" Consider whether a footnote citation (blog posts, conference talks, published architecture descriptions) would strengthen the comparison.
 
### 4. Actionability — FUNCTIONAL
 
The data pull items (1–5) are highly actionable: specific data sources, specific queries, specific output formats. A data analyst could execute items 1–5 without further instruction.
 
The interview items (6, 8, 9, 10) are less actionable. They specify *what to ask* but not *how to conduct the interview*. For someone who hasn't done stakeholder interviews for a technical proposal before, the brief doesn't cover:
 
- How many people to interview (item 2 says "3–5 care team members" but items 9 and 10 don't specify)
- How to record and attribute responses (names? anonymized? quotes or summaries?)
- How long the interviews should take
- Whether to combine items 6, 8, 9, and 10 into a single interview guide or conduct them separately
This matters because the person executing the brief might be an engineer, not a researcher.
 
### 5. Output Specification — FUNCTIONAL
 
For data items, the output is well-specified: "Daily mean, median, and range. Break down by alert type if possible."
 
For interview items, the output is underspecified. Item 10 says "One concrete narrative: the alert, the call, the unexpected discovery, and what happened next." That's a good output description. But item 9 says "Current answer method and time cost, or explicit inability to answer" — this is vague. What format? A table? Quotes? A paragraph per question?
 
### 6. Integration Guidance — WEAK
 
The brief tells you what to gather but not where to put it. The action items say "Update the leadership proposal with sourced numbers or reframed gaps" but don't specify which evidence maps to which section of the proposal.
 
For example: Item 10 (learning loop story) — does this go in the pilot section? The Phase 6 description? The problem section? The bottom line? The brief doesn't say. An explicit mapping table (evidence item → proposal section → insertion point) would close this gap.
 
### 7. Scope Discipline — STRONG
 
The brief stays focused on evidence for the leadership proposal. It doesn't expand into general research, competitive analysis, or technical validation. The baseline metrics table acknowledges pre-Phase 1 measurement needs but correctly notes "these don't need to be in the proposal." Good discipline.
 
## The Three Biggest Fixes
 
### 1. Add an interview protocol
 
What's wrong: Four evidence items require interviews, but the brief doesn't specify how to conduct them. An engineer executing this brief will either skip the interviews or conduct them inefficiently.
 
What to do: Add a section: "Interview Protocol." Specify: combine items 6, 8, 9, and 10 into a single 20-minute interview guide. Interview 3 care team members and 2 engineering/CS leads. Record responses as attributed quotes (with permission) or anonymized summaries. Provide the exact question sequence.
 
Expected effect: The interviews happen, produce usable output, and take one afternoon instead of becoming a multi-week project.
 
### 2. Add an evidence-to-proposal mapping table
 
What's wrong: The brief produces evidence but doesn't tell the author where to insert it.
 
What to do: Add a table mapping each evidence item to its target location in the leadership proposal:
 
| Item | Proposal Section | Insertion Point |
|---|---|---|
| 1. Alert volume | The Problem | Replace `~200 care alerts/day` with sourced number |
| 2. False positive rate | The Problem | Replace `approximately 70%` with sourced number or qualified estimate |
| 3. Alert-to-call time | The Problem → "What we cannot currently measure" | Confirm the gap or replace with sourced metric |
| 6. Cross-team examples | The Problem → department examples | Replace or augment the three bullet examples |
| 10. Learning loop story | The Pilot or Phase 6 | Add as a concrete illustration |
 
Expected effect: The author can update the proposal immediately after gathering each item, rather than gathering all evidence and then figuring out where it goes.
 
### 3. Address the Stripe/Airbnb/Uber/Amazon claim
 
What's wrong: The leadership proposal makes an architectural comparison to major tech companies without citation. The evidence brief doesn't flag this.
 
What to do: Add item 11: "Strategic comparison citations." Where to source: published blog posts, conference talks, or architecture descriptions from Stripe (event-driven architecture), Uber (event sourcing), Airbnb (service orchestration), Amazon (internal platform evolution). What to report: 2–3 links or citations that support the claim. If unavailable, qualify: "Companies at similar coordination complexity have adopted event-driven operational platforms" without naming specific companies.
 
Expected effect: The comparison survives executive scrutiny.
 
## What's Actually Working
 
The "How to Handle Missing Data" framework (source → qualify → frame the gap) is the most valuable artifact in the document. It solves a problem most evidence-gathering plans ignore: what to do when the data doesn't exist. The fallback framings for items 2 and 3 are ready to paste into the proposal as-is. The prioritization hierarchy (critical vs. important) is correct and will prevent the author from spending time on items 4–5 when items 1–3 are unresolved.
 
## Revision Priority
 
Targeted additions: interview protocol (fix #1), mapping table (fix #2), and one new evidence item (fix #3). No restructuring needed. The document's prioritization and fallback framings are its strengths and should be preserved. Estimated effort: 30 minutes of writing.