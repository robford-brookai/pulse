# PULSE

[![Release](https://img.shields.io/github/v/release/robford-brookai/pulse)](https://img.shields.io/github/v/release/robford-brookai/pulse)
[![Build status](https://img.shields.io/github/actions/workflow/status/robford-brookai/pulse/main.yml?branch=main)](https://github.com/robford-brookai/pulse/actions/workflows/main.yml?query=branch%3Amain)
[![Commit activity](https://img.shields.io/github/commit-activity/m/robford-brookai/pulse)](https://img.shields.io/github/commit-activity/m/robford-brookai/pulse)
[![License](https://img.shields.io/github/license/robford-brookai/pulse)](https://img.shields.io/github/license/robford-brookai/pulse)

Patient unified ledger of state and events.

## What PULSE is

PULSE is Brook's system of record for patient care state. It gives every Brook system one place
to declare a fact — an enrollment, a referral, a billing episode changing state — and one place
to read the current answer back, instead of each system re-deriving its own. Every declared fact
lands in an append-only ledger (nothing is edited or deleted; a correction is a new entry that
reverses the old one), validated on the way in against a versioned state catalog, and replayed out
to the rest of Brook over an event bus.

Full detail on why PULSE exists and how the pieces fit together is in the
[repository README](https://github.com/robford-brookai/pulse#readme).

## Getting started

Two commands take a fresh clone to a green build:

```bash
task install   # uv sync --all-packages: virtualenv plus every workspace package
task check     # lint, typecheck, tests, the Twenty app suite, a strict docs build
```

`task check` is the same gate CI runs — green locally means green in CI. Run `task` on its own
to list every command, grouped by area in the order you reach them as you work.

Building a connector — a package that moves facts between an external system and the ledger?
Start at [Authoring a connector](connectors/authoring.md) instead of reading this site
end to end; it names the scaffold command, the registration steps, and the reference
implementation to copy from.

## Finding your way around

The nav on this site follows the order you'd reach each concern, not the repo's directory
layout:

- **Architecture** — the target design: event envelope, state catalog, Snowflake landing,
  Twenty data model, and the clinic rules engine.
- **Modules** — generated API reference for `pulse_core` and the connector kit.
- **Runbooks** — one page per operational procedure: month-open, consent-sweep,
  identity-quarantine, and the numbered demos, in the order a shift would run them.
- **Connectors** — the authoring guide: how to add a new connector, in the order you need it.
- **Process** — how the ADE workflow and the DevEx audit operate, independent of any one change.
- **Contracts** — what this repo publishes and consumes across repo boundaries.
- **Reference** — CI and scaffold lessons, MCP server notes, and the ADR log.

If a page isn't linked from here, it's either linked from one of those sections or it's missing
from `mkdocs.yml`'s nav — the docs build fails strictly rather than silently dropping it.
