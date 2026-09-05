# Authoring a connector

How to add a new connector to this repo, in the order you will need it. Read the whole page once
before starting: the registration step (7) is where an otherwise finished connector goes invisible
to lint, typecheck, tests, and coverage, and it is easier to do while the package is empty.

The reference implementation is `packages/billing-connector` — every pattern below is lifted from
it, so when this page is ambiguous, that package is the answer. The contract this page implements
is `openspec/specs/connector-kit/spec.md`.

## 1. What a connector is here

A connector is a package that moves facts between one external system and the pulse ledger. It has
a fixed shape, and the shape is not negotiable:

- **One process, no HTTP surface.** It reads and it declares. Nothing calls into it.
- **Reads come off the bus or a row source; writes go through the command API.** A connector holds
  no ledger database connection string — no ledger DSN, no `pulse_ledger` import. This is enforced,
  not advised (see step 6).
- **Exactly one writer credential of its own.** The actor on every event it declares is derived
  from that credential, never from a payload (ADR-0003: attribution is authentication). Its
  configuration holds the credential's *name*; the environment holds the value. Also enforced.
- **Every run ends in a counted receipt.** Counts and keys only — never a payload value, a contact
  detail, or a monetary amount.
- **Idempotent by construction.** A rerun of the same input declares nothing twice: every
  submission comes back `replayed`, and the receipt says so.

Two directions, and most connectors are one of them:

| Direction | What it does | Kit surface | Reference |
| --- | --- | --- | --- |
| Inbound | Page an external source, validate rows, declare them | `RowSource`, `CursorStore`, `validate_page`, `submit_with_retry` | `packages/consent-ingress`, `packages/verdict-relay` |
| Outbound | Consume this connector's own SQS queue, act, write back | `consume`, `Deduper`, `submit_with_retry` | `packages/billing-connector`, `packages/twenty-projection` |

## 2. What to import

Everything shared lives in `pulse_core.connector`. Import from the package root, not the
submodules — the root is the supported surface and `__all__` is checked against it by
`packages/pulse-core/tests/test_connector_exports.py`.

```python
from pulse_core.connector import (
    # inbound: the read contract
    CursorStore,          # Protocol: load()/save() a durable cursor
    RowSource,            # Protocol: fetch(after=..., limit=...) -> raw rows
    LedgerCursorStore,    # the production CursorStore, via the ledger's writer-state API
    FixtureRowSource,     # the RowSource every test drives
    validate_page,        # catch-and-collect validation over one raw page
    required_string,      # per-column validators; raise RowValidationError naming the column
    required_timestamp,
    # outbound: the consume loop
    consume,              # receive/process/delete forever (or `iterations` times)
    consume_once,         # one pass, when you want to emit a receipt line per pass
    InMemoryDeduper,      # event-id dedupe
    # declaring: the retry pipeline and the receipt
    submit_with_retry,    # retries `transient` only; raises TransientExhaustedError
    Sleeper,              # the `sleep` callable's type: Callable[[float], None]
    Jitter,               # the `jitter` callable's type: Callable[[], float] in [0, 1]
    DeclareCounts,        # committed / replayed / rejected — the receipt's core
)
```

Do not write your own retry loop, cursor persistence, page validator, or dedupe. If the kit is
missing a primitive you need, it is missing because nothing shipped has needed it yet: build it
inside your connector, and propose extracting it once a second connector wants it. The kit is
extracted, never invented (`openspec/specs/connector-kit/spec.md`, "The kit is extracted, not
invented").

What each piece gives you:

- **`RowSource`** is a `Protocol` with one method, `fetch(*, after, limit)`, returning raw
  mappings. Production implements it against the real source; tests pass `FixtureRowSource` over
  recorded rows. Never fake the source below this seam.
- **`CursorStore`** is `load()`/`save()`. `LedgerCursorStore` persists through the ledger's
  writer-state facility scoped to your writer id, so a crashed run resumes without loss and rows
  already declared classify as replays.
- **`consume`** wraps `consume_once` in a loop with backoff. A message is deleted only after your
  handler returns without raising — a failure is left for the queue's visibility timeout and DLQ
  redrive, never swallowed. A malformed message is dropped rather than retried forever.
- **`submit_with_retry`** takes a `submit` callable and a `ref` string naming the submission (never
  its content). It retries only a `transient` classification, and raises
  `TransientExhaustedError` naming `ref` once the attempt budget is spent. Pin your
  `PulseCoreClient` to `max_attempts=1` and let this own the retry policy, so nothing retries
  twice. It also takes `sleep: Sleeper` and `jitter: Jitter` — inject `time.sleep` and
  `random.random` in production, and something deterministic in tests so the backoff schedule is
  pinned.
- **`DeclareCounts.record(classification)`** returns the next tally — it never mutates. Extend it
  with a frozen dataclass for your own dispositions, as
  `packages/billing-connector/src/billing_connector/receipts.py` does with `evaluated` and
  `deferred`.

## 3. How to scaffold

One command renders the package from `templates/connector/` and performs every registration in
step 7:

```bash
task connector:new NAME=my-connector
task install          # resolve the workspace with the new member
task check            # the rendered package ships one green test
```

`scripts/connector_new.py` is what the target runs; `--print-registrations` shows the diff it
will apply without writing anything.

Prior art: if `packages/ocean/services/` already has a directory whose name starts with `NAME`,
the command names that path before rendering and continues — Ocean may already have a connector
for this service, worth checking before you build a second one.

The tree it renders:

```text
packages/my-connector/
├── pyproject.toml                 # name, workspace deps, pytest + pyright config
├── src/my_connector/
│   ├── __init__.py
│   ├── config.py                  # credential NAME, endpoints, staleness — no secret values
│   ├── service.py                 # main(); wires config → client → kit loop
│   ├── receipts.py                # DeclareCounts + your own counts
│   └── py.typed
└── tests/
    ├── __init__.py
    ├── conftest.py                # the socket block — see step 5
    ├── factories.py               # fakes at the httpx boundary
    └── test_config.py
```

`pyproject.toml` starts from the reference's: `requires-python = ">=3.10,<4.0"`,
`pulse-core = { workspace = true }` under `[tool.uv.sources]`, `[tool.hatch.build.targets.wheel]`
pointing at `src/my_connector`, `testpaths = ["tests"]`, and
`[tool.pyright] typeCheckingMode = "strict"`. Declare `pytest-socket` in the dev group.

Then `task install` to resolve the workspace with the new member.

## 4. How to configure

One frozen dataclass, one `from_env()` classmethod, and one rule: **the configuration holds the
credential's name, never its value.**

```python
#: This connector's own writer credential *name* — the variable its token lives in. A constant,
#: not read from the environment: what varies by deploy is the value, never which variable holds it.
TOKEN_ENV_VAR = "MY_CONNECTOR_TOKEN"  # noqa: S105 — an env var name, not a secret
QUEUE_URL_ENV_VAR = "MY_CONNECTOR_QUEUE_URL"
LEDGER_BASE_URL_ENV_VAR = "MY_CONNECTOR_LEDGER_BASE_URL"


@dataclass(frozen=True)
class Config:
    credential_name: str
    queue_url: str
    ledger_base_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        ...
```

Rules the gate and the reviewer both check:

- `credential_name` is a module constant, not itself sourced from the environment. The one place
  that needs the token reads `os.environ[config.credential_name]`; no secret value is constructed,
  stored, defaulted, or logged anywhere in the package.
- `from_env()` still requires the credential variable to be *set*, and fails naming it — without
  reading what it is set to.
- `ledger_base_url` is the command API's base URL. An HTTP endpoint. Never a connection string.
- **Report every missing variable at once.** A `from_env()` that raises on the first missing name
  makes the author run the process once per variable. Collect them and name them all in one error.
- **Name the variable on an invalid value too** — `MY_CONNECTOR_STALE_AFTER` must appear in the
  error when `MY_CONNECTOR_STALE_AFTER=banana`, or the author is left bisecting the environment.
- Anything the *external* system's own registry or catalog decides is not configuration. Read it
  from there, so widening it stays a reviewed edit rather than an environment variable.

## 5. How to test offline

No test in this repo touches a live network. Two mechanisms, both required.

**Block sockets for the whole package.** `--disable-socket` only guards invocations that remember
to pass it; a `conftest.py` hook guards every run that collects the package, including the combined
run from the repo root:

```python
"""Socket-blocked test posture: no live network in any my-connector test."""

from __future__ import annotations

from pytest_socket import disable_socket


def pytest_runtest_setup() -> None:
    disable_socket()
```

**Fake at the transport seam, not below it.** Every kit boundary takes an injectable seam, so
nothing needs monkeypatching:

- The command API: `PulseCoreClient(..., transport=httpx.MockTransport(handler))`.
- The queue: pass your own `sqs_client` fake to `consume` / `consume_once`; the real `boto3` client
  is imported lazily and only when you pass none.
- The source: `FixtureRowSource` over recorded rows.
- Time: `submit_with_retry` takes `sleep` and `jitter` callables — pin them and the backoff
  schedule is deterministic.

Write these tests first. The ones that pay for themselves immediately: a rerun of a fully-declared
batch counts every submission `replayed` and creates no new event; a redelivered queue message
applies once and the second delivery is deleted as a dedupe hit; a page with one malformed row
counts a `RowError` naming its offset and column, logs no payload value, and processes the rest;
`from_env()` with an empty environment names every missing variable.

Run them:

```bash
uv run pytest packages/my-connector/tests
task test          # the combined run, with coverage
task typecheck     # mypy on TYPED_PATHS, pyright per package
task lint          # `task fmt` applies what this only reports
```

## 6. What is enforced, before you get to CI

`packages/pulse-core/tests/test_connector_credential_gate.py` discovers your package
automatically: any package whose `src/` tree imports from `pulse_core.connector` is "under the
connector convention", and from then on three gates apply to it —

1. It holds **exactly one** credential name.
2. It holds **no ledger internals** — no `pulse_ledger` import, no DSN literal.
3. **No credential value reaches a log call**, including an inline `os.environ[...]` read inside
   one.

There is nothing to register for this. Import the kit and you are in scope, which is the point.

## 7. How to register the package — all nine sites

`task connector:new` applies every edit in this section for you. Read it anyway: a package that
exists but is not registered silently is not linted, not typechecked, not tested, and not covered,
and you will recognise a missed site when reviewing someone else's connector. Nine edits, two
files. Grep for a sibling connector's name to confirm none is missing:

```bash
grep -rn "billing-connector\|billing_connector" pyproject.toml Taskfile.yml
```

In `pyproject.toml`:

1. `[tool.uv.workspace]` `members` — add `"packages/my-connector"`.
2. `[tool.uv.sources]` — add `my-connector = { workspace = true }`.

In `Taskfile.yml`, the four path variables at the top:

3. `LINT_PATHS` — add `packages/my-connector` (the package root: `src` and `tests` both).
4. `TYPED_PATHS` — add `packages/my-connector/src` if mypy covers it; if the package is pyright-
   strict instead (the newer posture, and the one the reference uses), add a
   `uv run pyright -p packages/my-connector` line to the `typecheck` target rather than a
   `TYPED_PATHS` entry.
5. `TESTED_PATHS` — add `packages/my-connector/tests`.
6. `COV_PATHS` — add `--cov=packages/my-connector/src`.

And the two deployment stanzas:

7. `my-connector:image` — the buildx target for `packages/my-connector/Dockerfile`. Build context
   is the repo root, because the Dockerfile installs from sibling workspace paths, not from PyPI.
8. `my-connector:deploy` — the roll-to-`TAG`-on-`TARGET` target.

Both of those may land as commented stubs while the connector is dev-only; a stub that names the
image and the entrypoint is a registration, an absent stanza is a gap.

One more, adjacent and easy to forget: `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`
needs `"packages/my-connector/tests/**" = ["S101"]`, or every `assert` in your tests is a lint
error.

## 8. How to ship it

The change lifecycle is `WORKFLOW.md`'s, and a connector is an ordinary repo change inside it:

1. The connector's specs and tasks live in an OpenSpec change (`task spec:validate`,
   `task dispatch CHANGE=<id>`). Never edit `openspec/specs/` directly — write proposed spec
   deltas to `HANDOFF.md` and let the doc-updater apply them (`AGENTS.md`).
2. Tests first, one task per commit.
3. `task check` before every commit — it is exactly what CI runs, so green locally is green in CI.
   `task pre-commit` runs the hooks; `task docs:build` catches a broken docs link, which
   `mkdocs build -s` treats as an error.
4. Push, open a **ready** PR (never a draft), and drive CI green yourself.
5. Merge is the human step. `task collect CHANGE=<id>` gathers handoffs; `task checkoff
   CHANGE=<id>` flips the merged tasks' boxes, which is what opens the next wave;
   `task verify CHANGE=<id>` runs the full gate including drift and spec validation (`CHANGE` is
   required — it fails fast rather than validating the wrong change).
6. On a fresh clone, `task lore:init` creates `.openlore/` before the first `task verify` or
   `task lore:drift` — it runs `openlore init --force`, so it's safe to re-run on a clone that
   already has one.

Two things that are not ordinary repo changes:

- **A cross-repo dependency** — a Snowflake object, an API, a released package — goes through
  `docs/contracts/consumes.md` and `docs/contracts/publishes.md`. Register your connector as a
  producer there: the domain it declares on, its writer credential's name, the paired commands, and
  a link to its runbook. A `patient-state` consumer needs to see your events attributed to your
  credential without reading your source.
- **Anything that touches production or is destructive** never runs from a worktree. Write the
  runbook (`docs/runbooks/`, and add it to the mkdocs nav), open the PR carrying it, and execute
  attended after a human merges it — that PR *is* the approval surface.
  [billing-connector](../runbooks/billing-connector.md) is the model: what the service is and is
  not, prerequisites with a PASS check each, numbered steps with PASS/FAIL per step, and how to
  read the receipt.

## 9. Who to ask

**Owner: Rob Ford** ([@robford-brookai](https://github.com/robford-brookai)) — ask directly on
Slack; there is no dedicated channel yet. `CONTRIBUTING.md` is the current word on this.

Before asking, the answer is usually in one of these:

| Question | Where |
| --- | --- |
| What is the kit allowed to do? | `openspec/specs/connector-kit/spec.md` |
| What does a finished connector look like? | `packages/billing-connector` |
| What does the inbound read path look like? | `packages/consent-ingress`, `packages/verdict-relay` |
| Why did CI fail on something local passed? | `docs/ci-lessons.md` |
| How does a change get from proposal to main? | `WORKFLOW.md`, `AGENTS.md` |
| What is a connector's standard shape overall? | `openspec/specs/connectors/pulse-standard-connector-spec.md` |
| How do I operate one once it is deployed? | [billing-connector runbook](../runbooks/billing-connector.md) |
| What changed in the kit since I last synced? | `packages/pulse-core/CHANGELOG.md` |

## 10. How the kit changes

The kit reaches every connector on the next `uv sync` — nothing prompts you to go read anything.
Two places carry that signal, and checking both is part of pulling a kit upgrade, not optional
follow-up:

- **`packages/pulse-core/CHANGELOG.md`** — every change that touches `pulse_core.connector` gets
  an entry in the same PR that makes it, with a "Connector authors" line naming the concrete
  effect on your build. Read it top-down; it is short.
- **Deprecations** — a name the kit is retiring stays exported and working for one release, with
  the CHANGELOG entry naming the replacement. `openspec/specs/connector-kit/spec.md`'s
  `## Deprecations` section is the durable record of what's retiring and by when; the CHANGELOG
  entry is the point-in-time announcement.

If a kit release drops a name your connector imports without either of these naming it first,
that is a kit defect — file it against `connector-kit`, don't work around it silently.

## PHI

No PHI in logs, commits, test fixtures, error messages, or docs — synthetic data only. This lands
on connectors harder than anywhere else, because a connector's whole job is carrying real records
across a boundary:

- A row validator names the **column**, never the value. A timestamp column fed from a drifted
  source can hold anything, payload content included — which is why `required_timestamp` puts no
  value in its message.
- A receipt carries **counts and keys**. Not amounts, not contact details, not payloads.
- `submit_with_retry`'s `ref` names the submission, not its content.
- Flag any code path where a payload could reach a logger or leave the process, even when the
  inputs you have today are synthetic.
