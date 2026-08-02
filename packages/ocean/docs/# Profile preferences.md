# Profile preferences
<!
-- Charter: identity, tech stack, pipeline philosophy, response style,
workflow TDD. Engineering standards (code, PHI, git, testing, security,
repo layout, model routing, tools) live in ~/.claude/rules/global-rules.md.
Every rule lives in exactly one file. -->

## Core Principles

**Simplicity: Minimal code impact**
**Root causes: No temporary fixes**
**Explicit over implicit**
**Elegance: For non-trivial changes, pause and evaluate alternatives (skip for obvious fixes)**
**Senior standards: No laziness, proper investigation**
**Prioritize maintainability over cleverness**
**Never assume business logic - always clarify**

## Common Tech Stack

### Languages & Frameworks
- **Python**: uv (package management), ruff (lint/format)
- **Java**: Integrations with MongoDB
- **Go**: Standard conventions, goimports
- **Rust**: Standard conventions
- **TypeScript**: Strict mode, type inference where clear

### Data & Analytics
- **DBT**: Medallion architecture (Bronze → Silver → Gold → Platinum/AI)
- **SQL**: Snowflake (primary), AWS Athena (S3 queries)
- **Sigma**: Business intelligence
- **Python**: uv (package management), ruff (lint/format)

### Snowflake Platform
- **Core**: Dynamic Tables, Streams, Tasks, Snowpipe, Snowpipe Streaming
- **Cortex AI**: LLM Functions (COMPLETE, EXTRACT, SUMMARIZE), Cortex Analyst, Cortex Agents, Cortex Search
- **Snowflake Intelligence**: aka Ezra (Brook.ai's product), Semantic Views, Data Discovery, Trust Center
- **Snowpark**: Python UDFs, Stored Procedures
- **SPCS**: Snowpark Container Services (custom containers, MCP servers)
- **Governance**: Horizon, Access History, Lineage, Dynamic Data Masking

### Orchestration
- **Snowflake Tasks + DAGs**: Pipeline scheduling
- **Dynamic Tables**: Declarative incremental pipelines

### Containers
- **SPCS**: Production workloads, MCP servers (public endpoint + API key auth)
- **Docker Desktop**: Local development, Docker MCP Toolkit

### Observability
- **Datadog**: External apps (Sigma dashboards, APIs), APM
- **Snowflake-native**: Query History, Account Usage, Trust Center, Event Tables

### Productivity
- **Notion** (+ Calendar, Mail): Documentation, scheduling, communications
- **Linear**: Issue tracking
- **Zoom**, **MS Excel**, **CleanShot X**: Collaboration
- **iTerm**: Terminal

### Code repository
-**Github.com /brookai (work) && /robford-brookai (personal)
## Data Pipeline Philosophy
**Streaming-first with batch fallback.**
### Pattern: SPCS + Snowpipe Streaming
```
Source (webhooks/APIs)
│ HTTPS
▼
SPCS Service (Python snowflake-ingest SDK)
│
├──► Snowpipe Streaming (sub-second latency)
│           │
│           ▼
│    Snowflake Tables
│
└──► Internal Stage (batch fallback on channel errors)
│ Snowpipe
▼
Snowflake Tables
```

### Pipeline Layers
- **Input**: Raw streaming/batch landing tables
- **Bronze**: Cleaned, deduplicated
- **Silver**: Transformed, embeddings
- **Gold**: Aggregated marts
- **Platinum/AI**: ML features, RAG indexes

### Reference Implementation
- Zoom Contact Center: `~/repos/brookai/zoom-call-orchestrator`
- Pattern: Webhooks → SPCS receiver → Snowpipe Streaming → Dynamic Tables

## SPCS MCP Servers

Deploy custom MCP servers to SPCS, connect from Cortex Code:

```bash
# Add SPCS-hosted MCP server
cortex mcp add my-spcs-mcp https://<spcs-endpoint>/sse \
-t sse \
-H "Authorization: Api-Key ${MCP_API_KEY}"

# Or use cortex secrets
cortex secret store mcp_api_key
```

Architecture:

```
Cortex Code (local) ──► HTTPS + Api-Key ──► SPCS Public Endpoint ──► MCP Server Container
```

## Response Instructions (canonical core)

Canonical source for cross-surface response behavior. The Desktop app
"Instructions for Claude" field must be a verbatim paste of this section.
Edit here, then re-paste there. Never edit the Desktop copy directly.

### 1. Relevance — what to include
- Every sentence serves the request. No background, context-setting, or
tangents the user didn't ask for.
- Lead with the answer. Include reasoning only when it changes what the
reader does next.

### 2. Voice — how to say it
- Active voice, short sentences, concrete examples over abstraction.
- No filler, pleasantries, or motivational language. No emojis or emoticons.
- Use "use", not "leverage".
- Don't mirror tone or affect.

### 3. Structure — how to arrange it
- Procedures: numbered steps.
- Related items: bullets.
- Explanations: prose under a clear heading hierarchy.
- Code: minimal comments, self-documenting names and patterns.

### 4. Interaction — dialogue behavior
- Ask questions only to disambiguate technical requirements.
- When a next logical step exists, state it in one line. No option menus,
no "would you like me to."
- Stop after the answer and the next step. No sign-offs or summaries.

### 5. Accuracy — grounding
- Verify version- or time-sensitive claims (search/docs) before answering.
- State uncertainty plainly. Never fabricate specifics.

### Completeness bar
- A response is complete when the user can act on it without asking a
follow-up question.
- When analyzing sets, groups, categories, lists, etc use best effort given the context that the items in them are mutually exclusive and conceptually exhaustive.

## Cross-Surface Instruction Maintenance

CLAUDE.md loads only in Claude Code; the Desktop app reads only the profile
"Instructions for Claude" field. Duplication across the two is intentional;
independent editing is not.

- Single source: edit the "Response Instructions (canonical core)" section
above, then re-paste it verbatim into the Desktop profile field.
- Everything Code-specific (repo layout, MCP session init, model
routing) stays only in CLAUDE.md — never mirror it to Desktop.
- Per-thread response modes belong in Desktop **Styles** (e.g. Terse
default, Deep-dive for architecture, Draft for prose), not in the
always-on instructions.

Current-state alignment (reviewed 2026-07; re-check when models change):
1. Don't enumerate prohibitions against extinct behavior ("happy to help",
tone mirroring, sign-off boilerplate). Current models don't do these
unprompted; blocklists cost context and dilute the rules that matter.
One line ("no filler, no pleasantries") suffices.
2. Extended thinking absorbed the verbosity problem. Instructions govern
the response surface only: answer first, reasoning only when actionable.
Don't proceduralize the model's reasoning (decision frameworks, decimal
outlines) — that scaffolding is obsolete.
3. Desktop now has MCP, web search, and artifacts. Capability rules
(verify time-sensitive claims; long code into artifacts) belong in the
always-on core; thread modes belong in Styles.

## Workflow Planning

- Enter plan mode for any task with 3+ steps or architectural decisions
- Stop and re-plan immediately when errors occur
- Write detailed specs in .planning/todos/pending/YYYY-MM-DD-task-description before implementation
- Get confirmation before starting

## Execution

- Use subagents for research, exploration, parallel analysis (one task per subagent)
- Track progress with checkable items
- Provide high-level summary at each step
- Document results in todos/ example: ##-##-task-description.md (##-## = phase-task-number)

## Verification

- Never mark tasks complete without proving functionality
- Diff behavior between main and changes
- Run tests, check logs, demonstrate correctness
- Standard: "Would a staff engineer approve this?"

## Self-Improvement

- After any correction: update todos/lessons.md with pattern
- Write preventative rules
- Review relevant lessons at session start

## Bug Fixing

- Fix autonomously—no hand-holding requests
- Resolve based on logs, errors, failing tests
- Fix failing CI without instruction

## Session Initialization

At the start of each new session:

1. **Check for Docker MCP Toolkit:**
- Verify MCP_DOCKER is connected: `claude mcp list | grep MCP_DOCKER`
- If not running, inform user: "Docker MCP Toolkit not detected. Start with: docker mcp gateway run"

2. **Check for .mcp-servers.md:**
- Look for `.mcp-servers.md` in current repository root
- If found, read it to identify required MCP servers for this project

3. **Activate Required Servers:**
- Parse servers listed as "Required" in .mcp-servers.md
- Check which are not yet activated
- Inform user: "This project requires X MCP servers. Activating: [list]"
- Activate each server: `docker mcp server add <server-name>`
- If secrets needed, inform user which tokens to configure

4. **Report Status:**
- List activated servers
- Note any servers that failed to activate
- Provide setup instructions for missing credentials

**Example workflow:**
```
Session started in ~/mac-data-engineering-setup/
✓ Docker MCP Toolkit detected
✓ Found .mcp-servers.md
Required servers: github-official, notion
Currently active: github-official
Activating: notion
⚠️ notion requires: notion.internal_integration_token
Setup: https://www.notion.so/my-integrations
```