# Connector template — Tier 3 gap analysis (template mechanics)

**Programme**: connector-template (`pricing-engine` as the reference Pulse API connector)
**Tier**: 3 of 3 — the mechanics that turn one good example into a reusable template
**Lane**: analysis only. No source code, no tests, no `Taskfile.yml` edit, no `openspec/` change,
no branch, no commit, no pull request. This file is the entire output of the run.
**Repository**: `/Users/Rob.Ford/orca/workspaces/pulse/betta`, branch
`robford-brookai/billing-state-proposal`, at merge commit `2dea0d9d` ("Merge pull request #270 from
robford-brookai/connector-template-reports").
**Date of the reads behind every citation**: 2026-08-22.

`packages/pricing-engine/` **does not exist yet**. `ls packages/` returns exactly thirteen
directories — `archaeology`, `consent-ingress`, `identity`, `ocean`, `pulse-core`, `pulse-ledger`,
`schedules`, `synthea-seed`, `twenty-app`, `twenty-model`, `twenty-projection`, `verdict-relay` —
and no `pricing-engine`. Every recommendation below is therefore about what the template must carry
when that package is created, not about repairing something already written.

---

## What this report corrects in the PARTIAL file

`.planning/reports/2026-08-21-connector-template-tier-3-PARTIAL.md` was written by a halted run and
carried the header "NOT independently re-verified". Every load-bearing claim in it was re-checked
against the tree this run read. Results:

| PARTIAL claim | Verdict |
|---|---|
| `packages/ocean/services/mongodb-connector/tests/` does not exist | **Confirmed.** `ls` returns `No such file or directory`. The directory listing of `packages/ocean/services/mongodb-connector/` is exactly `Dockerfile`, `k8s`, `pyproject.toml`, `src` — no `tests`. It is additionally pinned as the *only* untested service by `tests/test_taskfile_test_coverage.py:68-77`, whose assertion is literally `assert untested == {"mongodb-connector"}` (`tests/test_taskfile_test_coverage.py:77`). |
| `mongodb-connector` is the only one of the seven emitting to the `patient-state` domain | **Confirmed.** Its publish domain defaults to `"patient-state"` at `packages/ocean/services/mongodb-connector/src/watcher.py:46` and `packages/ocean/services/mongodb-connector/src/watcher_manager.py:37`, and the publish call is `await self._publisher.publish(self._domain, event_dict, key=transformed["patient_id"])` at `packages/ocean/services/mongodb-connector/src/watcher.py:137`. No other service source file names `patient-state`. |
| The producer-policy gate is a hard-blocking pytest assertion inside `task check` | **Confirmed.** `tests/test_producer_ingress_policy.py:79-83` asserts `assert findings == [], render_report(findings)` and `assert errors == []`. `tests/` is the first entry of `TESTED_PATHS` at `Taskfile.yml:31`; `TESTED_PATHS` is consumed by `task test` at `Taskfile.yml:140`; `task check` calls `task test` unconditionally at `Taskfile.yml:393`. There is no warn-only mode. |
| `EventBridgePublisher._handle_failure` silently drops the envelope when no session maker was supplied | **Confirmed at the exact lines the PARTIAL cited.** `packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py:143-145` is `if session_maker is None:` / `log.error("dlq_unavailable_event_dropped", ...)` / `return`. |
| `packages/ocean/producer-policy-suppressions.yaml` contains `suppressions: []` | **Confirmed** (`packages/ocean/producer-policy-suppressions.yaml:14`). |
| `mongodb-connector` is 1157 lines across its source files | **Confirmed** by `find packages/ocean/services/mongodb-connector/src -name "*.py" | xargs wc -l` → `1157` total, across six files (`__init__.py`, `leader.py`, `main.py`, `resume_token.py`, `transformer.py`, `watcher_manager.py`, `watcher.py` — seven names, one of which is empty). |
| `mongodb-connector` uses `pg_try_advisory_lock` leader election and a `cdc_resume_tokens` table | **Confirmed.** `packages/ocean/services/mongodb-connector/src/leader.py:38` is `_ACQUIRE_SQL = text("SELECT pg_try_advisory_lock(:lock_id)")`; `packages/ocean/services/mongodb-connector/src/resume_token.py:20` is the `INSERT INTO cdc_resume_tokens (collection_name, resume_token, updated_at) ` upsert. |
| `impilo-connector` and `pocar-connector` each write an `audit_log` row per accepted webhook | **Confirmed.** `packages/ocean/services/impilo-connector/src/receiver.py:61` and `packages/ocean/services/pocar-connector/src/receiver.py:65` both open `"INSERT INTO audit_log "`. |

**One material correction.** The PARTIAL's framing — that `mongodb-connector` emitting to the
`patient-state` domain is what makes it the migration candidate — is misleading, and acting on it
would send an engineer down the wrong path. The producer-policy classifier **never reads the
EventBridge domain string at all**. `packages/pulse-core/src/pulse_core/producer_policy.py` extracts
three vocabulary surfaces from parsed source — literal state vocabularies, entity/subject-type
declarations, and `event_type` addressing — and a domain name is none of those. The archived design
states the addressing rule verbatim at
`openspec/changes/archive/2026-08-08-producer-ingress-policy/design.md:73-84`. `patient-state` is a
bus detail-type, defined as one of eleven `LIVE_DOMAINS` at
`packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py:55`, and it is not a catalog subject —
the eight catalog subjects are `referral`, `consent`, `communication_consent`, `enrollment`,
`billing_episode`, `device`, `contract`, `coverage` (`catalog/state_catalog.yaml:32`, `:44`, `:52`,
`:61`, `:68`, `:76`, `:85`, `:92`). `mongodb-connector` emits the event type
`patient.feature.changed`; `patient` is not a catalog subject (it is not in that list, and the only
registry subject is `person` at `catalog/state_catalog.yaml:104`), so the gate cannot and does not
flag it. The corrected classification appears in Item 3.3 below, and it changes the recommendation:
**the connector that actually carries a semantic catalog-subject assertion is `impilo-connector`,
not `mongodb-connector`.**

---

## Item 3.1 — A connector conformance suite

### Current state

**No shared, reusable test suite exists, in any form.** Four independent searches establish this:

1. **No pytest plugin.** Greps for `pytest11`, `[project.entry-points`, and `pytest_plugins`
   across every non-vendored file return zero hits. The only `plugins =` key in the tree is
   mypy's, at `pyproject.toml:96` (`plugins = ["pydantic.mypy"]`). No workspace package declares
   an entry point of any kind.
2. **No abstract base class and no cross-package parametrised suite.** No `class Base*Test`, no
   `*TestBase`, and no `abstractmethod` appears under any `tests/` tree. Test modules do import
   *production* code across package boundaries (for example
   `packages/verdict-relay/tests/test_run.py:23`, `from pulse_core.client import PulseCoreClient`)
   but never import test helpers across a boundary.
3. **No importable test-support module.** `packages/pulse-core/src/pulse_core/__init__.py` is one
   line — a docstring — and exports nothing (verified: the file's entire content is
   `"""PULSE client SDK: command submission, response classification, consume convention."""`).
   There is no `pulse_core.testing`, no `conftest_shared.py`, no `tests/support/` package.
4. **`tests/scaffold/` is not a candidate mechanism.** Those nine gate files
   (`tests/scaffold/cat1_*` through `cat9_*`) validate the repository's own structure — its
   workflow, its Taskfile, its docs build — not library behaviour, and they are collected only
   because `pyproject.toml:126` widens `python_files` to `["test_*.py", "cat[0-9]_*.py"]`.

**What exists instead is copy-paste that documents itself as copy-paste.** Seven package
`conftest.py` files are functionally identical fourteen-line socket blockers that define no
fixtures at all:

- `packages/verdict-relay/tests/conftest.py:13-14`
- `packages/schedules/tests/conftest.py:13-14`
- `packages/consent-ingress/tests/conftest.py:13-14`
- `packages/archaeology/tests/conftest.py:15-16`
- `packages/twenty-projection/tests/conftest.py:14-15`
- `packages/synthea-seed/tests/conftest.py:14-15`
- `packages/identity/tests/conftest.py:24-25`

Each body is exactly `def pytest_runtest_setup() -> None:` / `    disable_socket()`. The docstrings
name their own source: `packages/schedules/tests/conftest.py:5` reads "Same pattern as
verdict-relay's conftest."; `packages/consent-ingress/tests/conftest.py:5` reads "Same pattern as
verdict-relay and schedules." That is a five-deep admitted copy chain.

The same duplication runs through the fakes. A hand-rolled `ScriptedApi` over
`httpx.MockTransport` is independently reimplemented **six times**:
`packages/verdict-relay/tests/test_run.py:75`,
`packages/verdict-relay/tests/test_declarer.py:81`,
`packages/verdict-relay/tests/test_config.py:50`,
`packages/verdict-relay/tests/test_coverage_first_declare.py:65`,
`packages/verdict-relay/tests/test_fixture_corpus.py:76`, plus consent-ingress's own copy used at
`packages/consent-ingress/tests/test_declarer.py:442`. An in-memory cursor store is reimplemented
three times: `packages/verdict-relay/tests/test_run.py:98`,
`packages/verdict-relay/tests/test_fixture_corpus.py:104`,
`packages/verdict-relay/tests/test_mart_reader.py:53`.

**There is one glob-based distribution precedent, and it is in ocean, not in the pulse packages.**
`task test:services` (`Taskfile.yml:151-168`) iterates
`for dir in packages/ocean/services/*/tests; do uv run pytest "$dir" -q || failed=...; done`
(`Taskfile.yml:161-164`), so a new ocean service's tests join continuous integration **by
existing**. That property is pinned by a gate:
`tests/test_taskfile_test_coverage.py:45-56` asserts `test:services` is reached from `task test`
and that it still iterates the literal glob `packages/ocean/services/*/tests`
(`tests/test_taskfile_test_coverage.py:27`). The top-level pulse packages have the opposite
property: `TESTED_PATHS` at `Taskfile.yml:31` is a hand-maintained space-separated list of eleven
paths, and a package absent from it is silently skipped.

**Adding one new package requires manual registration in at least seven separate places**, each
verified:

| # | Registration point | Citation |
|---|---|---|
| 1 | `[tool.uv.workspace] members` | root `pyproject.toml`, thirteen entries |
| 2 | `[tool.uv.sources] <pkg> = { workspace = true }` | root `pyproject.toml` |
| 3 | `[tool.ruff.lint.per-file-ignores]` `"packages/<pkg>/tests/**"` with `S101` | asserted for existing packages by `tests/test_workspace_scaffold.py:89-96` |
| 4 | `LINT_PATHS` | `Taskfile.yml:19` |
| 5 | `TYPED_PATHS` | `Taskfile.yml:25` |
| 6 | `TESTED_PATHS` and `COV_PATHS` | `Taskfile.yml:31` and `Taskfile.yml:44` |
| 7 | a `pyright -p` line in the `typecheck` target | `Taskfile.yml:120-133` |

Plus the package's own `conftest.py` and its own `pytest-socket>=0.7.0` dev dependency, since
neither is inherited: `pytest-socket` is **not** a root dev dependency (the root `dev` group at
`pyproject.toml:26-52` lists `pytest`, `pytest-cov`, `pre-commit`, `tox-uv`, `deptry`, `mypy`,
`ruff`, `pyyaml`, `types-pyyaml`, `tomli`, `mkdocs`, `mkdocs-material`, `mkdocstrings[python]`,
`boto3-stubs[events]`, `httpx` — and no `pytest-socket`), and is instead declared nine times, once
per package, for example `packages/verdict-relay/pyproject.toml:26` and
`packages/pulse-core/pyproject.toml:17`.

**Critically, no gate catches an unregistered package.** `tests/test_workspace_scaffold.py:25-28`
defines `_PACKAGES` as a hardcoded two-entry dict — `{"packages/pulse-ledger": "pulse_ledger",
"packages/pulse-core": "pulse_core"}` — not a glob. Its own module docstring
(`tests/test_workspace_scaffold.py:3-5`) states the exact hazard: "A package can exist on disk while
every quality gate silently skips it — lint, typecheck, tests, and coverage each have their own path
list in `Taskfile.yml`, and membership in `[tool.uv.workspace]` implies none of them." The remedy
chosen was a per-package gate file, and `tests/test_twenty_projection_scaffold.py` is the second
instance of that pattern (`tests/test_twenty_projection_scaffold.py:62-65` asserts the projection
package's presence in `LINT_PATHS`, `TESTED_PATHS`, and `COV_PATHS`). So `packages/pricing-engine`
would need an eighth artefact: its own `tests/test_pricing_engine_scaffold.py`.

**The behaviours a suite should assert, each grounded in an existing requirement or test:**

| # | Behaviour to assert | Grounding requirement | Existing test that already proves it, once |
|---|---|---|---|
| 1 | A repeated idempotency key returns the original event id marked replayed, and never writes a second event | `openspec/specs/command-api/spec.md:37-40` ("Every command SHALL carry an idempotency key of the form `{writer_id}:{sha256(subject, command_type, payload, logical_time)}` … A replay SHALL return the original commit result (with the prior event id) and SHALL never produce a second event (D16).") and scenario `:42-47` | `packages/pulse-core/tests/test_client.py:53`; `packages/verdict-relay/tests/test_declarer.py:131` |
| 2 | A replay counts as an idempotent hit and never re-declares | `openspec/specs/verdict-declare/spec.md:81-85` | `packages/verdict-relay/tests/test_declarer.py:131` and `:142` |
| 3 | A `rejected` classification is counted, logged with the ledger's reason and catalog version, and **never retried** | `openspec/specs/verdict-declare/spec.md:87-92` ("the row counts as rejected, the log carries the ledger's reason, no retry occurs, and the run continues") | `packages/pulse-core/tests/test_client.py:162`; `packages/verdict-relay/tests/test_declarer.py:152` |
| 4 | A `transient` classification retries with backoff up to the connector's declared attempt budget, then fails naming the row | `openspec/specs/verdict-declare/spec.md:94-98` | `packages/verdict-relay/tests/test_declarer.py:179` and `:193` |
| 5 | Retry-after-transient recovers within the attempt budget, and no sleep occurs after the final attempt | Implicit in the same requirement | `packages/pulse-core/tests/test_client.py:190` and `:238` |
| 6 | A command body carrying `actor_type`, `actor_id`, `actor_authority`, or `producer` is rejected — even when the value agrees with the credential | `openspec/specs/command-api/spec.md:61-63` (verbatim: "A command body SHALL NOT carry `actor_type`, `actor_id`, `actor_authority`, or `producer` at all, even when the value agrees with the credential.") and scenario `:65-69` | `packages/pulse-ledger/src/pulse_ledger/auth.py:216-219` is the enforcement; no connector-side test asserts a connector never sends them |
| 7 | Validation that can fail before the wire does fail before the wire — zero API calls | `openspec/specs/verdict-declare/spec.md:32-37` and `:51-55` | `packages/verdict-relay/tests/test_config.py:210` |
| 8 | A cursor resume replays its last uncommitted page and re-reads nothing already committed | `openspec/specs/ledger-read/spec.md:41-48`; `openspec/specs/customerio-consent-ingress/spec.md:62` | `packages/verdict-relay/tests/test_mart_reader.py:162`; `packages/consent-ingress/tests/test_declarer.py:459` — **two independent implementations of one requirement** |
| 9 | A persisted cursor is JSON-native and round-trips byte-identically | `packages/pulse-core/src/pulse_core/cursor.py:3-9` | `packages/pulse-core/tests/test_cursor.py:12` |
| 10 | A synthetic canary value planted in a non-contract field never appears in any log line, receipt, or error the run produced | `openspec/specs/customerio-consent-ingress/spec.md:88` ("Requirement: Receipts and logs carry no contact values"), scenario `:94` | `packages/consent-ingress/tests/test_declarer.py:416` |
| 11 | Every network boundary is faked, and a real socket call fails the test | `openspec/specs/customerio-consent-ingress/spec.md:101` ("Requirement: Every Snowflake read is fixture-faked in tests"), scenario `:107` ("The test suite runs with no live network") | `packages/verdict-relay/tests/test_verdict_relay_package.py:21` (`test_sockets_are_blocked`, importing `SocketBlockedError` from `pytest_socket`) |
| 12 | A missing credential environment variable fails startup naming the variable, never a configured value | `openspec/specs/verdict-declare/spec.md:10-14` (D15: "credential name in configuration, value from the environment, never in code or fixtures") | `packages/verdict-relay/tests/test_production.py:56` and `:65` |

**How no-PHI logging is proved mechanically today.** The believed test exists. It is
`packages/consent-ingress/tests/test_declarer.py:416`,
`test_run_receipt_and_log_lines_never_carry_a_contact_value`. Its technique, read in full:

- A synthetic canary is defined at `packages/consent-ingress/tests/test_declarer.py:420`:
  `contact_value = "not-a-real-address@example.test"`. It is synthetic and non-routable by
  construction (`.test` is a reserved top-level domain), so the test itself carries no protected
  health information.
- The canary is planted in a **non-contract column** (`contact_email`) on two rows — one malformed
  and one valid — at `packages/consent-ingress/tests/test_declarer.py:429` and `:436`. Planting it
  on the malformed row is the load-bearing half: error paths are where payload values leak.
- Capture is stdlib `caplog`, scoped to one named logger:
  `with caplog.at_level(logging.INFO, logger="consent_ingress.declarer"):` at
  `packages/consent-ingress/tests/test_declarer.py:443`.
- Four surfaces are asserted, not one
  (`packages/consent-ingress/tests/test_declarer.py:450-456`): the receipt summary line, every
  `row_errors[].detail`, every `row_errors[].column`, and every captured log record's
  `getMessage()`.
- **The anti-vacuity guard** is `assert caplog.records` at
  `packages/consent-ingress/tests/test_declarer.py:454`, commented "the run did produce log lines,
  not merely a silent receipt". Without it the test passes trivially when nothing logs.

**Does it generalise?** Partly, and the part that does not is the reason a suite is needed. The
`caplog` form is portable but requires each connector to hardcode its own logger-name string, so it
can only ever be a parametrised fixture, never a copied file. There is a **second, stronger and
incompatible** technique in the same repository: `packages/verdict-relay/tests/test_run.py:152-160`
defines a `log_stream` fixture that installs the service's **real JSON formatter**
(`configure_logging(stream)`) over an `io.StringIO`, then scans the rendered output against an
eleven-name deny list `DEMOGRAPHIC_MARKERS` (`packages/verdict-relay/tests/test_run.py:245-257`)
with its own anti-vacuity guard `assert "episode-" in output`
(`packages/verdict-relay/tests/test_run.py:272`). That form catches a leak the `caplog` form cannot
— a formatter that serialises a field `record.getMessage()` never renders — but it is bound to
`verdict_relay.run.configure_logging` and cannot move without a shared logging-configuration
contract. A conformance suite must therefore parametrise over
`(logger_name, configure_logging_callable, canary_value, anti_vacuity_token)`.

There is a **third** shape in ocean: a shared PHI vocabulary constant exported from library code and
imported by tests. `packages/ocean/libs/ocean-events/src/ocean_events/base.py:11-…` defines
`_PHI_FIELD_NAMES: frozenset[str]` (a denylist beginning `patient_name`, `first_name`, `last_name`,
`full_name`, `date_of_birth`, `dob`, `birth_date`, `mrn`, …) and enforces it twice — at class
definition time, raising `TypeError` for a PHI-named field
(`packages/ocean/libs/ocean-events/src/ocean_events/base.py:73-77`), and at instance creation, raising
`ValueError` for a PHI key in the payload dict
(`packages/ocean/libs/ocean-events/src/ocean_events/base.py:81-85`). **No equivalent guard exists on
the pulse side.** Every `PHI` reference in `packages/pulse-ledger/src/` and
`packages/pulse-core/src/` is a docstring convention, not a check — for example
`packages/pulse-ledger/src/pulse_ledger/api.py:42`, `packages/pulse-ledger/src/pulse_ledger/commit.py:152`,
`packages/pulse-core/src/pulse_core/cursor.py:34`. A connector declaring through the command API
gets no structural PHI guard at all.

**The offline, credential-free constraint, and exactly what it forbids.** The rule is stated at
`CLAUDE.md:112` ("No live network in tests; CI has no secrets by default") and at
`design/delivery/pulse-s1-work-orders.md:5` ("No live network calls in any test suite"). It is
enforced by `pytest-socket`'s `disable_socket()` in the seven conftests listed above, and its
boundary is pinned in two places: `tests/scaffold/cat4_ci_contract.py:193-213`
(`test_check_target_is_ci_safe`) walks the `check` target transitively and asserts neither
`openspec` nor `openlore` appears, with the failure message "`task check` transitively runs
`{tool}`, which CI does not install; keep it in `verify` instead"; and `Taskfile.yml:210-211`
records "Never reached from `check` — the check contract stays credential-free". Real credentials
are quarantined in `.github/workflows/catalog-release.yml:40-43`
(`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_DATABASE`), a workflow
whose own header at `.github/workflows/catalog-release.yml:3` states "it is not CI and is never
reached from `task check`; main.yml stays credential-free".

What that forbids, concretely: **no LocalStack, no `moto`, no Docker container, no real Amazon
EventBridge or Amazon Simple Queue Service call, no Snowflake connection, no live pulse-ledger
process, and no outbound HTTP of any kind.** The single sanctioned seam is
`httpx.MockTransport` — used at `packages/verdict-relay/tests/test_run.py:93`,
`packages/verdict-relay/tests/test_declarer.py:105` and `:351`,
`packages/verdict-relay/tests/test_config.py:69`,
`packages/verdict-relay/tests/test_coverage_first_declare.py:81`,
`packages/verdict-relay/tests/test_fixture_corpus.py:99`,
`packages/verdict-relay/tests/test_ordering.py:99`, and
`packages/verdict-relay/tests/test_mart_reader.py:264` and `:292`. Neither `responses`, `respx`,
`moto`, nor `botocore.stub` appears anywhere in the repository. One carve-out exists and must be
copied: `packages/pulse-ledger/pyproject.toml:71` sets
`addopts = '-m "not integration" --allow-unix-socket'`, explained at
`packages/pulse-ledger/pyproject.toml:68-70` — Starlette's `TestClient` runs its anyio portal over
an `AF_UNIX` socketpair self-pipe, which a global `--disable-socket` would block along with real
network calls.

**And the thing a conformance suite would actually stop.** Retry policy is per-connector today,
with no shared specification, and the two in-repository implementations already differ on three
axes:

| Axis | `pulse_core` default | `verdict-relay` |
|---|---|---|
| Maximum attempts | `DEFAULT_MAX_ATTEMPTS = 4` (`packages/pulse-core/src/pulse_core/client.py:52`) | `DECLARE_MAX_ATTEMPTS = 5` (`packages/verdict-relay/src/verdict_relay/declarer.py:70`) |
| Delay ceiling | `DEFAULT_MAX_DELAY_SECONDS = 8.0` (`packages/pulse-core/src/pulse_core/client.py:54`) | `DEFAULT_MAX_DELAY_SECONDS = 30.0` (`packages/verdict-relay/src/verdict_relay/declarer.py:73`) |
| Jitter | **None.** `_backoff_delay` at `packages/pulse-core/src/pulse_core/client.py:223-226` is `base * (2 ** (attempt - 1))`, capped; the module imports no randomness source | **Full jitter.** `packages/verdict-relay/src/verdict_relay/declarer.py:289-291` is `ceiling = min(...)` then `return ceiling * self._jitter()`, defaulting to `random.random` at `packages/verdict-relay/src/verdict_relay/declarer.py:194` |
| Behaviour on exhaustion | **Returns** a `CommandResponse` still classified `TRANSIENT` (`packages/pulse-core/src/pulse_core/client.py:322-323`) | **Raises** `TransientExhaustedError` (`packages/verdict-relay/src/verdict_relay/declarer.py:287`) |

**Correction to the tier 1 framing carried into this work order.** The two values are *not* an
accidental disagreement. `packages/verdict-relay/src/verdict_relay/declarer.py:158` constructs the
shared client with `max_attempts=1`, documented at
`packages/verdict-relay/src/verdict_relay/declarer.py:145-147`: "The client is pinned to
`max_attempts=1` because retry policy belongs to the declarer (design decision 4) — a client that
also retried would multiply the attempt budget." So the layering is deliberate and the relay's
effective budget is exactly 5, matching its spec at `openspec/specs/verdict-declare/spec.md:78`
("retried with backoff up to 5 attempts"). The finding survives the correction and gets sharper:
**the 5 is specified for verdict-relay alone, and `consent-ingress` — the other connector — takes
the unspecified `pulse_core` defaults**, because
`packages/consent-ingress/src/consent_ingress/cli.py:222` constructs
`PulseCoreClient(base_url, writer_id=CUSTOMERIO_WRITER_ID, token=os.environ[CUSTOMERIO_TOKEN_ENV_VAR])`
with no `max_attempts` override and the module names no attempt constant of its own. Two
connectors, two retry policies, no shared requirement. Eleven will be eleven.

### Gap

There is no mechanism by which a connector can prove conformance, and therefore no way to review
one without reading every line. Every behaviour a reviewer would want to check is already tested
somewhere — but each is tested once, inside one package, against one connector's own hand-rolled
fakes, with no importable form. The absence compounds rather than staying flat: each new connector
adds a seventh, eighth, ninth copy of the socket-blocking conftest, another `ScriptedApi`, another
cursor-store fake, another retry policy chosen by whoever wrote it, and another chance that the
`rejected`-is-never-retried rule is quietly got wrong in a way nothing catches. And the distribution
problem is harder than the test-list problem, because some of the eleven source systems may not live
in this repository at all, which rules out every mechanism that depends on the monorepo's shared
working copy.

### Options

**Option A — a `pytest` plugin published as a workspace package (`packages/pulse-conformance/`).**
The package ships a `[project.entry-points.pytest11]` declaration so that merely installing it
registers its fixtures and its `pytest_runtest_setup` socket blocker; a connector's suite then
declares one fixture (a factory returning the connector's declarer, its logger name, and its
`configure_logging` callable) and gets the whole assertion battery for free.
*Cost*: a new workspace package (registration in all seven points listed above plus its own
scaffold gate), and a decision about how a connector outside this repository installs it.
*Gives up*: nothing structural in-repo. Out-of-repo it needs a distribution channel that does not
exist today — no private package index is configured anywhere (root `pyproject.toml` declares no
`[[tool.uv.index]]`), so the only credential-free option is a git-URL dependency such as
`pulse-conformance @ git+https://github.com/robford-brookai/pulse.git@<tag>#subdirectory=packages/pulse-conformance`,
which pins by tag and needs repository read access.
**Works out-of-repository: yes**, via that git-URL form, once someone decides it is acceptable.

**Option B — an importable abstract base class the connector subclasses.**
Ship `PulseConnectorConformance` from the same package; a connector writes
`class TestPricingEngineConformance(PulseConnectorConformance):` and overrides three abstract
factory methods.
*Cost*: lower than A — no entry point, no plugin machinery, just an ordinary import.
*Gives up*: the socket-blocking hook, which is a `pytest_runtest_setup` and cannot live on a class,
so each connector still copies its own `conftest.py` — the exact duplication with the longest
existing chain. Subclass-based suites also interact badly with `--import-mode=importlib`, which
`task test` uses at `Taskfile.yml:140`, and with pytest's collection of inherited tests when two
connectors are collected in one process.
**Works out-of-repository: yes**, with the same git-URL caveat.

**Option C — a parametrised suite taking a connector object as a fixture.**
One module in the shared package exposes `pytest_generate_tests` or a set of module-level tests
that consume a `connector_under_test` fixture the connector defines in its own `conftest.py`.
*Cost*: lowest of the three; it is roughly Option A minus the entry point.
*Gives up*: discoverability — the connector author must know to write
`pytest_plugins = ["pulse_conformance.suite"]` or to import the module explicitly, and a connector
that forgets simply runs no conformance tests and stays green. That silent-skip failure is the
same class as the unregistered-package hazard `tests/test_workspace_scaffold.py:3-5` already warns
about.
**Works out-of-repository: yes.**

**Option D — a copied test file kept in sync by a gate.**
The suite lives at a canonical path; each connector holds a byte-identical copy; a repository-level
gate (the shape of `tests/test_catalog_consumer_contract.py`) asserts every copy matches the
canonical file.
*Cost*: XS to build, and it needs no packaging decision at all.
*Gives up*: everything the moment a connector leaves this repository. **Works
out-of-repository: no** — the sync gate can only compare files inside one working copy, which is
disqualifying given that some of the eleven systems may not live here. It also cannot carry
fixtures or a socket hook, only assertions over an object the copied file must construct itself.

### Recommendation

**Option A, a `pytest11` plugin in a new `packages/pulse-conformance/` workspace package, with
Option C's parametrised suite as its internal shape.** The entry point is what makes conformance
the default rather than something a connector author must remember to opt into — and given that
Rob writes one connector and Brook's engineers write ten, "silently runs no conformance tests" is
the failure this tier exists to prevent. It is also the only option that can carry the
`pytest_runtest_setup` socket blocker, retiring the seven-way conftest copy chain. Option D is
disqualified on the out-of-repository requirement alone.

### Level of effort

**`XL`** — the in-repository build is a well-understood `L` (a new workspace package, seven
registration points, its own scaffold gate, and a first pass of twelve assertions ported from tests
that already exist), but it cannot be finished without a decision Rob has to make: how a connector
in a *different* repository installs `pulse-conformance`, given that no package index is configured
in this repository and the git-URL form implies granting repository read access to whoever builds
each of the ten connectors.

### Dependencies and risks

- **Must land first**: nothing. The suite can be built against `verdict-relay` and
  `consent-ingress` as its two first subjects before `pricing-engine` exists, which is the better
  order — a suite validated against two existing connectors is credible; one written speculatively
  against a connector that does not exist yet is not.
- **Harder than it looks (1)**: the twelve assertions are not uniformly portable. Numbers 1–7 are
  pure functions of the response classification and port cleanly. Number 8 (cursor resume) requires
  the connector to expose a `CursorStore`-shaped seam, which `verdict-relay` has
  (`packages/verdict-relay/src/verdict_relay/mart_reader.py:95-104`, the `CursorStore` protocol) and
  a connector without a cursor does not. Number 10 (PHI canary) needs the four-way parametrisation
  described above.
- **Harder than it looks (2)**: `packages/ocean/pyproject.toml` does **not** declare
  `pytest-socket` at all (its dev dependencies are `httpx`, `pytest>=9.0.2`,
  `pytest-asyncio>=1.3.0`), so all fourteen ocean service suites run with sockets open. If the
  conformance package is ever pointed at an ocean service, expect the offline assertion to fail on
  first contact — and that failure is correct.
- **Harder than it looks (3)**: `hypothesis>=6.100` is declared in exactly one package,
  `packages/verdict-relay/pyproject.toml:23`, and powers exactly one test
  (`packages/verdict-relay/tests/test_ordering.py:124`, the shuffled-batch monotonicity oracle).
  That property test is the single most reusable conformance artefact in the repository, and moving
  it into the shared package makes `hypothesis` a dependency of every connector.
- **If it could fail silently, doubt this first**: whether the plugin is actually *loaded* in each
  connector's run. An entry-point plugin that fails to register produces a green suite with zero
  conformance tests collected. The suite must therefore ship its own self-proof — the shape of
  `packages/verdict-relay/tests/test_verdict_relay_package.py:21`
  (`test_sockets_are_blocked`, which imports `SocketBlockedError` and proves the block is live) —
  and the repository gate should assert a minimum collected count, not merely a zero exit code.

---

## Item 3.2 — An explicit anti-patterns document

### Current state

**No anti-patterns document exists.** `find docs -name "*.md"` returns twenty-eight files: six
architecture decision records under `docs/adr/`, twelve runbooks under `docs/runbooks/`, two
contract files under `docs/contracts/`, two process documents under `docs/process/`,
`docs/ci-lessons.md`, `docs/mcp-servers.md`, `docs/modules.md`, `docs/index.md`, and two nested
README files. None is about connector anti-patterns. The one policy document that comes closest,
`packages/ocean/docs/producer-policy.md`, covers exactly one of the four candidates.

**The four candidate anti-patterns, with their enforcement point and their failure mode:**

**(1) Publishing catalog-subject state to the event bus instead of declaring through the command
API.**
*Documented*: `packages/ocean/docs/producer-policy.md:9-12`, the rule in two bullets — "If your
event asserts a PULSE-subject state transition: stop emitting it. Issue a command to the PULSE API
instead… If your event is a non-subject fact (a reading landed, a call completed, a document
arrived): keep emitting directly."
*Enforced*: `tests/test_producer_ingress_policy.py:79-83`, `assert findings == []` and
`assert errors == []`, reached by `task check` through `Taskfile.yml:31` → `:140` → `:393`.
*Fails*: **loudly, and hard.** A violating producer turns `task check` red — the same command
continuous integration runs. There is no warn-only mode; the classifier itself
(`packages/pulse-core/src/pulse_core/producer_policy.py`) never raises or exits, it returns
findings, and the test is the enforcement point.
*But the gate is syntactic, and its own designers wrote down where it is blind.*
`openspec/changes/archive/2026-08-08-producer-ingress-policy/design.md:130-134` records the accepted
risk verbatim: "a producer inventing one novel state name alongside real catalog states dodges the
≥2-subset test only if fewer than two values remain catalog states; a fully renamed vocabulary
dodges it entirely → accepted: §4.4's test is 'names a state that lives in the catalog' — a producer
that renames states isn't naming catalog states." A second accepted blind spot is at
`:135-138`: "AST extraction misses dynamically built vocabularies (f-strings, concatenation, config
files)." Both are real today — see the `impilo-connector` case in Item 3.3.

**(2) Writing rows directly into the pulse Postgres database.**
*Documented*: `openspec/specs/command-api/spec.md:10` — "The command API SHALL be the only writer to
the ledger." Restated at `:97` as the "single-writer guarantee".
*Enforced*: **nowhere.** There is no gate, no test, and no lint rule that detects a direct write to
the `ledger.*` schema from outside `packages/pulse-ledger/`. Searches for such a gate across
`tests/`, `tests/scaffold/`, and `.pre-commit-config.yaml` found none.
*Fails*: **silently.** A connector that opens its own connection to the pulse Postgres and inserts
into `ledger.events` gets a row with no idempotency key, no catalog validation, no outbox entry, and
no `rule_version` — and nothing anywhere goes red. **This is the highest-prominence entry for the
document, because it is the only one of the four with zero mechanical backstop.**
*Live precedent that makes the mistake plausible*: three of the seven existing connectors write
directly to a Postgres database today — `packages/ocean/services/impilo-connector/src/receiver.py:61`
and `packages/ocean/services/pocar-connector/src/receiver.py:65` each `INSERT INTO audit_log`, and
`packages/ocean/services/mongodb-connector/src/resume_token.py:20` upserts `cdc_resume_tokens`.
Those are *ocean's* Postgres, not pulse's, and are legitimate — but an engineer copying an ocean
connector will copy a direct-`INSERT` idiom and may not notice which database it points at.

**(3) Retrying a `rejected` command response.**
*Documented*: `openspec/specs/verdict-declare/spec.md:73-79`, verbatim — "**rejected** (illegal
transition) is counted and logged with the ledger's reason and version, **and never retried**";
scenario at `:87-92`.
*Enforced*: **structurally, but only for callers who use the software development kit.**
`packages/pulse-core/src/pulse_core/client.py:322` is
`if result.classification is not ResponseClassification.TRANSIENT or attempt >= self._max_attempts:`
— the loop exits on anything that is not `TRANSIENT`, so a `PulseCoreClient` user cannot retry a
rejection even by accident. The classification boundary is
`_REJECTED_STATUS = frozenset({401, 403, 422})` at
`packages/pulse-core/src/pulse_core/client.py:46` against
`_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})` at `:50`.
*Fails*: **loudly for a software-development-kit user (the retry simply cannot happen), silently for
anyone who reaches for raw `httpx`.** A connector that posts to `/commands` directly and retries on
any non-2xx will hammer a 422 four or five times, log four or five identical rejections, and — since
a rejection writes nothing — produce no visible corruption. Nothing catches it. There is also a
sharp edge worth naming in the document: `packages/pulse-core/src/pulse_core/client.py:322-323`
**returns** an exhausted-transient response rather than raising, so a caller that only inspects
`CommandResponse.is_success` (`packages/pulse-core/src/pulse_core/client.py:102-105`, true only for
`COMMITTED` and `REPLAYED`) without inspecting `.classification` silently drops the command.

**(4) Putting actor fields in a command request body.**
*Documented*: `openspec/specs/command-api/spec.md:61-63`, and the design rationale at `:71-74` —
"overwriting a body-supplied actor makes a misconfigured producer indistinguishable from a correct
one forever, because the ledger records the corrected value and the writer never learns. Rejection
is the only behaviour a writer can notice."
*Enforced*: `packages/pulse-ledger/src/pulse_ledger/auth.py:67` defines
`CREDENTIAL_DERIVED_FIELDS = ("actor_type", "actor_id", "actor_authority", "producer")`, and
`Writer.attribute` at `packages/pulse-ledger/src/pulse_ledger/auth.py:216-219` raises
`ActorSpoofError` for any of them, mapped to HTTP 403 at
`packages/pulse-ledger/src/pulse_ledger/api.py:589`.
*Fails*: **loudly, at runtime, server-side.** A connector that does this gets a 403 on its first
request, which `packages/pulse-core/src/pulse_core/client.py:46` classifies as `REJECTED` and never
retries. It is also structurally impossible through the software development kit:
`packages/pulse-core/src/pulse_core/client.py:_command_body` builds the wire body from the
generated `Command` fields only, and its docstring at
`packages/pulse-core/src/pulse_core/client.py:186-189` states "Attribution fields
(`actor_type`/`actor_id`/`actor_authority`/`producer`) are never part of this body". Lowest
prominence of the four.

**Prominence ordering, which is the actionable output of this analysis:**

| Rank | Anti-pattern | Mechanical backstop | Prominence in the document |
|---|---|---|---|
| 1 | Writing directly to the pulse Postgres database | **none** | Highest — the only one nothing catches |
| 2 | Retrying a `rejected` response with a raw HTTP client | none outside the software development kit | High — invisible when it happens |
| 3 | Emitting catalog-subject state to the bus | offline gate, hard-fails `task check`, but syntactic and self-documented as evadable | Medium — explain the gate *and* its two accepted blind spots |
| 4 | Actor fields in the request body | server-side 403; impossible via the software development kit | Lowest — one sentence and a pointer |

**Two further anti-patterns discovered the hard way that belong on the list, both found in the
repository rather than invented:**

**(5) Publishing without a dead-letter sink, which silently drops the event.**
`packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py:143-145`: when
`self._db_session_maker is None`, the publisher logs `dlq_unavailable_event_dropped` and returns.
The published contract admits it — `docs/contracts/consumes.md:86` reads "a publisher constructed
without a `db_session_maker` logs failures without durably queuing them". Two further silent-loss
paths sit beside it: the dead-letter write itself is wrapped in a bare `except`
(`packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py:181-182`, logging
`dlq_write_failed`), and the `failed_webhooks` table has no redrive — `retry_count` is written as
`0` at `packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py:177` and no code in the tree
ever increments or replays it.

**(6) Pointing an engineer at a symbol that does not exist.**
The producer-policy gate's fixed disposition line, which is spec'd as part of the contract
(`openspec/changes/archive/2026-08-08-producer-ingress-policy/design.md:145-151`), instructs the
reader to "Convert the emit to a command through the ledger write path
(`pulse_core.submit_command`)" — `packages/pulse-core/src/pulse_core/producer_policy.py:56-62`. The
same string appears in `packages/ocean/docs/producer-policy.md:11` and `:47`.
**`pulse_core.submit_command` is not importable.**
`packages/pulse-core/src/pulse_core/__init__.py` contains one docstring line and no exports; the
real symbol is `pulse_core.client.PulseCoreClient.submit_command`
(`packages/pulse-core/src/pulse_core/client.py:274`). An engineer whose gate just went red will
`from pulse_core import submit_command`, get an `ImportError`, and lose time. This is a
documentation defect the anti-patterns page should fix by naming the correct import in full.

**`docs/ci-lessons.md`, read in full (141 lines), contains no connector anti-patterns.** All
fourteen dated entries are about the agent development environment scaffold itself — the workflow
running `make check` in a go-task repository (`docs/ci-lessons.md:66-75`), `sed -i` portability
(`:113-118`), `gh api -f` sending strings where JSON null was required (`:29-41`), unsorted
`iterdir()` making golden output machine-dependent (`:130-136`), go-task rejecting flag-style
arguments (`:137-141`). Its own framing rule is at `docs/ci-lessons.md:6-7`: "A lesson that can be
expressed as a gate belongs in `tests/scaffold/`, not here. This file is for the residue." Nothing
in it transfers to a connector author.

**Where such a page could live, judged against `mkdocs.yml`.** The `nav:` block at
`mkdocs.yml:10-24` lists exactly four top-level entries — `Home: index.md`,
`Architecture: architecture.html`, `Modules: modules.md`, and a `Runbooks:` group of eleven
runbooks. It is stale in two ways worth knowing before choosing: the site identity is still the
template's (`site_name: repo-ade`, `repo_url: https://github.com/robford-brookai/repo-ade`,
`mkdocs.yml:1-2`), and two shipped runbooks are absent from the nav —
`docs/runbooks/verdict-relay.md` and `docs/runbooks/demo1-ledger-core.md` both exist on disk and
neither appears between `mkdocs.yml:15` and `:23`. `docs/adr/`, `docs/contracts/`, and
`docs/ci-lessons.md` are likewise unlisted. So a page under `docs/` is buildable and linkable but
needs a hand-edited nav entry to be *findable*, and the nav has already been shown to drift.

### Gap

Four anti-patterns exist as scattered enforcement — one offline gate, one server-side 403, one
structural property of a client class, and one requirement with no enforcement whatsoever — and no
single document names them together, ranks them by whether anything catches them, or tells a
connector author what to do instead. The ranking is the part that is entirely absent and the part
that matters most: an engineer reading a list of four rules has no way to know that three of them
have a backstop and the fourth does not, so effort gets spread evenly across risks that differ by an
order of magnitude.

### Options

**Option A — a section of `packages/pricing-engine/README.md`.**
Sits where the copying engineer already is, since the whole premise of this programme is that ten
people copy that package.
*Cost*: XS, no navigation edit, no build interaction.
*Gives up*: reachability from anywhere else — it is invisible to someone who lands on the
documentation site, and it duplicates rather than replaces
`packages/ocean/docs/producer-policy.md`, so anti-pattern (3) ends up stated in two places that can
drift apart.

**Option B — a page at `docs/connector-anti-patterns.md` plus a `mkdocs.yml` nav entry.**
One canonical location, reachable from the published site, and the natural home for a cross-cutting
policy that is not owned by any single package.
*Cost*: S — the page, one `nav:` line, and care that every placeholder is inline code rather than
link syntax, because `mkdocs build -s` treats a broken link as an error (the lesson recorded at
`docs/ci-lessons.md:83-88`) and `task docs:build` is inside `task check` at `Taskfile.yml:398`.
*Gives up*: proximity — a connector author copying `packages/pricing-engine/` will not see it
unless the package README links to it.

**Option C — a dedicated file inside the connector package,
`packages/pricing-engine/ANTI-PATTERNS.md`.**
*Cost*: XS.
*Gives up*: everything Option B gains, and it makes the file a per-connector artefact that will be
copied eleven times and diverge eleven ways — the precise failure this tier exists to prevent.

### Recommendation

**Option B, with a one-line pointer from `packages/pricing-engine/README.md`.** The document is
cross-cutting policy that outlives any one package, so it belongs in `docs/` where it can be cited
by a gate failure message and by every connector README; the pointer is what closes Option B's only
real weakness. While making the nav edit, add the two orphaned runbooks
(`docs/runbooks/verdict-relay.md`, `docs/runbooks/demo1-ledger-core.md`) so the nav stops drifting,
and fix the `pulse_core.submit_command` reference at
`packages/pulse-core/src/pulse_core/producer_policy.py:58` and
`packages/ocean/docs/producer-policy.md:11` to name
`pulse_core.client.PulseCoreClient.submit_command` in full.

### Level of effort

**`S`** — one new markdown file and one `mkdocs.yml` nav line, with every fact already located and
cited in this section so the writing is transcription rather than research; the
`pulse_core.submit_command` correction touches two files and one spec'd string, which is the only
part needing care.

### Dependencies and risks

- **Must land first**: nothing. The document can be written today against
  `verdict-relay` and `consent-ingress` as its worked examples, before `pricing-engine` exists.
- **Harder than it looks**: the disposition string at
  `packages/pulse-core/src/pulse_core/producer_policy.py:56-62` is **spec'd as part of the
  contract** — `openspec/changes/archive/2026-08-08-producer-ingress-policy/design.md:145-151`
  records decision 7, "The failure message is part of the contract… Spec'd ('A red gate names the
  §4.4 disposition') so the message cannot rot into an assert diff." Correcting the symbol name in
  it is a spec-touching change, which under `AGENTS.md` means writing the proposed change to
  `HANDOFF.md` for the doc-updater rather than editing a spec file directly. That single line is
  what could turn an `S` into an `M`.
- **Harder than it looks (2)**: `mkdocs build -s` runs inside `task check`
  (`Taskfile.yml:398`), so a mistyped relative link in the new page fails continuous integration.
  Keep every placeholder as inline code, never link syntax.
- **If it could fail silently, doubt this first**: the claim that nothing gates a direct write to
  the pulse Postgres database. That is an absence proved by search, and an absence is the weakest
  kind of finding. Before publishing the document, re-run a targeted search for any pre-commit
  hook, ruff rule, or `tests/` gate matching `ledger\.` schema writes outside
  `packages/pulse-ledger/`; if one is found, anti-pattern (2) drops from rank 1 to rank 4 and the
  whole ordering changes.

---

## Item 3.3 — A migration story for the seven existing bus-emitting connectors

### Current state

**No migration story exists in any form** — no document under `design/migration/` addresses the
seven connectors individually, and `packages/ocean/docs/producer-policy.md` gives a rule without
naming which connectors it applies to.

**What each of the seven does today.** Addressing for all seven resolves through
`packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py:139-141` (`_ADDRESSES`) and `:143-154`
(`address_for`): `source` is always the constant `EVENT_SOURCE`, and `detail-type` is exactly the
domain string handed to `publisher.publish`. An unknown domain raises `KeyError` before the bus is
touched (`packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py:150-154`). There is no
per-connector domain-selection logic beyond that literal.

| Connector | Reads | Emits → bus domain | Durable cursor | Direct Postgres writes | Tests | `src/` lines |
|---|---|---|---|---|---|---|
| `github-connector` | GitHub webhooks, HMAC-SHA256 `X-Hub-Signature-256` | `pr.opened` / `pr.merged` / `pr.closed`, `commit.pushed` → `signals` (`packages/ocean/services/github-connector/src/receiver.py:56`); heartbeat → `ops` (`packages/ocean/services/github-connector/src/heartbeat.py:40`) | none | none beyond the shared dead-letter table | 3 files, 525 lines | 249 |
| `hubspot-connector` | HubSpot batched webhooks, v3 signature with a 300-second replay window (`packages/ocean/services/hubspot-connector/src/receiver.py:20`, `MAX_TIMESTAMP_AGE_SECS = 300`) | `contact.created` / `contact.deleted` / `contact.updated` → `signals` (`packages/ocean/services/hubspot-connector/src/receiver.py:89`); heartbeat → `ops` (`packages/ocean/services/hubspot-connector/src/heartbeat.py:40`) | none | none beyond the shared dead-letter table | 3 files, 546 lines | 285 |
| `impilo-connector` | Webhooks authenticated by an `Impilo-API-Key` header **and** Simple Queue Service polling of a Simple Notification Service fan-out, selected by the presence of `SQS_QUEUE_URL` | `signal.received` / `patient.enrolled` / `signal.missing` → `signals`; seven order, kit, procurement, return, fulfillment and device types → `logistics` (`packages/ocean/services/impilo-connector/src/normalizer.py:16-41`); publish at `packages/ocean/services/impilo-connector/src/receiver.py:51` and `packages/ocean/services/impilo-connector/src/sqs_consumer.py:82`, both `detail_type=domain`; heartbeat → `ops` | delete-after-publish acknowledgement on the queue, not a persisted cursor | **`INSERT INTO audit_log` per accepted webhook** (`packages/ocean/services/impilo-connector/src/receiver.py:61`) | 4 files + `conftest.py`, 663 lines | 595 |
| `linear-connector` | Linear webhooks, HMAC-SHA256 `linear-signature`, gated on an `"ocean"` issue label | `ticket.create.requested` → `tickets` (`packages/ocean/services/linear-connector/src/receiver.py:67`); heartbeat → `ops` (`packages/ocean/services/linear-connector/src/heartbeat.py:49`) | none | none beyond the shared dead-letter table | 3 files, 470 lines | 252 |
| `mongodb-connector` | **MongoDB change streams (change data capture)** — no HTTP receiver; leader election by `pg_try_advisory_lock` (`packages/ocean/services/mongodb-connector/src/leader.py:38`) | `patient.feature.changed` → **`patient-state`** (`packages/ocean/services/mongodb-connector/src/watcher.py:46` and `:137`) | **yes** — resume tokens upserted into `cdc_resume_tokens` after each publish (`packages/ocean/services/mongodb-connector/src/resume_token.py:20`) | `cdc_resume_tokens` plus the shared dead-letter table | **none — the `tests/` directory does not exist** | 1157 |
| `pocar-connector` | POCAR webhooks, HMAC-SHA256 `X-Pocar-Signature` | `alert.created` → `alerts` (`packages/ocean/services/pocar-connector/src/receiver.py:54`); heartbeat → `ops` (`packages/ocean/services/pocar-connector/src/heartbeat.py:49`) | none | **`INSERT INTO audit_log` per accepted webhook** (`packages/ocean/services/pocar-connector/src/receiver.py:65`) | 3 files + `conftest.py`, 304 lines | 315 |
| `zcc-connector` | Zoom Contact Center webhooks, Zoom v0 signature; handles `endpoint.url_validation` inline | `call.started` / `call.connected` / `call.completed` / `call.missed` → `interactions` (`packages/ocean/services/zcc-connector/src/receiver.py:72`); heartbeat → `ops` (`packages/ocean/services/zcc-connector/src/heartbeat.py:49`) | none | none; hard-fails at startup when `DATABASE_URL` is absent | 4 files + `conftest.py`, 394 lines | 274 |

**Classification against catalog-subject state.** The eight catalog subjects are `referral`,
`consent`, `communication_consent`, `enrollment`, `billing_episode`, `device`, `contract`, and
`coverage` (`catalog/state_catalog.yaml:32`, `:44`, `:52`, `:61`, `:68`, `:76`, `:85`, `:92`), plus
one registry subject `person` (`catalog/state_catalog.yaml:104`). Two classifications are needed,
because the gate's answer and the honest answer differ:

| Connector | Passes the producer-policy gate today? | Genuinely touches catalog-subject state? | Reasoning |
|---|---|---|---|
| `github-connector` | yes | **no** | Pull requests and commits address no catalog subject. Pure non-subject facts. |
| `hubspot-connector` | yes | **no** | `contact` is not a catalog subject; `created` / `updated` / `deleted` are not any subject's states. Person-registry adjacency exists but the connector asserts no state. |
| `impilo-connector` | yes | **YES — and the gate cannot see it** | `packages/ocean/services/impilo-connector/src/normalizer.py:241` emits the payload key/value pair `"enrollment_status": "enrolled"` on every `patient.*` event. `enrollment` **is** a catalog subject (`catalog/state_catalog.yaml:61`) whose declared states are `pending_start`, `active`, `on_hold`, `ended`. The gate does not flag it for two reasons, both by design: the event type is `patient.enrolled`, whose prefix `patient` is not a subject, and the state vocabulary here is a **single** value, below the two-value floor the subset rule requires (`openspec/changes/archive/2026-08-08-producer-ingress-policy/design.md:73-84`). Semantically this is an enrollment-state assertion crossing the bus. It is the exact false negative the design accepted at `:130-134`. A second, weaker instance: `DEVICE_OFFLINE_STATUSES = {"inactive", "lost"}` at `packages/ocean/services/impilo-connector/src/normalizer.py:44` — `lost` **is** a `device` state (`catalog/state_catalog.yaml:82`), but `inactive` is not, so the set is not a subset of exactly one subject's states and the gate correctly declines to flag it. |
| `linear-connector` | yes | **no** | `ticket` is not a catalog subject. The archived design names `TicketStatus` (`in_progress` / `waiting`) explicitly as a non-subset that must stay green (`openspec/changes/archive/2026-08-08-producer-ingress-policy/design.md:83-84`). |
| `mongodb-connector` | yes | **no** | `patient.feature.changed` on the `patient-state` domain. `patient` is not a catalog subject and `feature`/`changed` name no state. The domain string is a bus detail-type from `LIVE_DOMAINS` (`packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py:55`) and is never read by the classifier. **This corrects the PARTIAL.** |
| `pocar-connector` | yes | **no** | `alert.created`. `AlertStatus` (`claimed` / `dismissed`) is named in the archived design as a deliberate non-subset (`openspec/changes/archive/2026-08-08-producer-ingress-policy/design.md:82-83`). |
| `zcc-connector` | yes | **no** | Call lifecycle events on `interactions`. No catalog subject. |

**What the gate does on a violation, since it decides whether migration is forced or voluntary.**
It **fails the build, hard.** `tests/test_producer_ingress_policy.py:79-83` is a plain pytest
assertion — `assert findings == [], render_report(findings)` and `assert errors == []` — over the
real `packages/ocean` tree (`tests/test_producer_ingress_policy.py:31-32`). That file is inside
`TESTED_PATHS` (`Taskfile.yml:31`), which `task test` consumes (`Taskfile.yml:140`), which
`task check` calls unconditionally (`Taskfile.yml:393`). The classifier itself never raises, exits,
or logs — `packages/pulse-core/src/pulse_core/producer_policy.py` returns findings and lets the
caller decide — so the *test* is the enforcement point and there is no warn-only mode. The
suppression file `packages/ocean/producer-policy-suppressions.yaml:14` contains `suppressions: []`,
zero recorded adjudications, and the archived design states suppressions are for adjudicated
name-collision false positives only, "never exemptions for a genuinely state-asserting producer,
which converts to an ingress adapter with no grandfathering"
(`packages/ocean/producer-policy-suppressions.yaml:4-6`).

**The consequence for migration posture is decisive: six of the seven are green and will stay green,
so migration is voluntary for them.** Only `impilo-connector` carries a genuine subject-state
assertion, and even that one is green because the gate cannot see it.

**One further fact bearing on the cost of any conversion**: **no ocean service imports `pulse_core`
today.** A repository-wide grep for `pulse_core` under `packages/ocean/` returns only documentation
prose (`packages/ocean/docs/producer-policy.md:11`, `:20`, `:47`) and a container mount
(`packages/ocean/infra/docker-compose.yml:123` and `:132`). Converting any connector therefore also
means adding `pulse-core` to that service's `pyproject.toml` **and** to its `Dockerfile`, because
`tests/test_ocean_bus_dependencies.py` asserts each service's Dockerfile installs a distribution set
satisfying the third-party imports its `src/` actually makes
(`tests/test_ocean_bus_dependencies.py:8-12` — "5.6 found images pinning `confluent-kafka` while
omitting `ocean-broker`/`boto3` entirely — an image that cannot start, invisible to every service
test suite").

**Two connectors carry explicitly unverified contracts**, which caps how confidently either can be
converted: `packages/ocean/services/pocar-connector/src/schema/pocar_webhook.py:3` is annotated
"PLACEHOLDER — validate with Brook engineering before production cutover", and
`packages/ocean/services/zcc-connector/src/normalizer.py:3-5` and `:17-18` flag the event-name
mapping as "MEDIUM confidence", unconfirmed against a live Zoom account.

**Protected-health-information posture is inconsistent across the seven**, which a template must
settle: `impilo-connector` raises `ValueError` on any PHI key match and SHA-256 hashes patient
identifiers; `hubspot-connector` redacts via `PHI_DENY_FIELDS` and `SAFE_PROPERTY_FIELDS`;
`pocar-connector` denylists raw payload keys; the other four do none of this. All of them inherit
the structural guard in `packages/ocean/libs/ocean-events/src/ocean_events/base.py:73-85`, which
raises `TypeError` at class definition time for a PHI-named field and `ValueError` at instance
creation for a PHI key in the payload — a guard the pulse command-API path has **no** equivalent of.

### Gap

An engineer who owns one of the seven has no document telling them whether to rewrite, wrap, or
leave it alone, and the mechanical signal available to them is actively misleading in both
directions: six connectors are green and genuinely non-subject (correct), while the seventh —
`impilo-connector` — is green and genuinely asserting `enrollment` state (a false negative its own
design accepted in writing). Absent a written posture, the plausible reading of "the gate is green,
so nothing to do" is right six times out of seven and wrong on the one that matters.

### Options

**Option A — convert all seven to command-API declarers.**
*What it does*: every connector stops publishing and starts declaring, so the entire fleet crosses
the pulse boundary in the sanctioned direction.
*What it costs*: see the per-connector table below; roughly `L` × 6 plus `XL` × 1.
*What it gives up*: six of the seven emit only non-subject facts that producer policy explicitly
says should keep emitting directly — `packages/ocean/docs/producer-policy.md:11-12`, "If your event
is a non-subject fact… keep emitting directly. Nothing changes." Converting them contradicts the
stated policy and throws away 2,239 lines of working, tested code and 2,902 lines of tests to buy
nothing.

**Option B — convert only those touching catalog-subject state.**
*What it does*: converts `impilo-connector`'s `patient.enrolled` path — and only that path — to a
`declare_transition` command against the `enrollment` subject, leaving its `signals` and `logistics`
emits alone. Nothing else changes.
*What it costs*: `L` for that one connector (per-path breakdown below).
*What it gives up*: it requires deciding that `patient.enrolled` really is an enrollment assertion,
which is a business-logic judgement about Impilo's semantics that nobody in this repository can make
alone — and `packages/ocean/docs/producer-policy.md:37-38` is explicit that adding a sanctioned
command source is a raise-it-first decision: "Any other producer that finds itself issuing commands
is out of scope for this policy — raise it before adding a new sanctioned source, don't infer one
from a gate failure." `impilo` is not among the five sanctioned sources at
`packages/ocean/docs/producer-policy.md:31-36`.

**Option C — wrap each in a thin declarer alongside the existing publish.**
*What it does*: the connector keeps emitting and additionally declares, so the ledger gains the
state while the bus consumers keep working.
*What it costs*: `M` per connector, plus `pulse-core` added to seven `pyproject.toml` files and
seven Dockerfiles.
*What it gives up*: dual-write. Every wrapped connector now has two independent failure modes and no
transaction spanning them, and the same fact exists in two stores with no reconciliation. For six
connectors it also declares facts the ledger has no subject for.

**Option D — leave all seven emitting, and apply the template only to new connectors.**
*What it does*: the seven stay exactly as they are; `pricing-engine` and the ten that follow are
born as command-API declarers under the template.
*What it costs*: `S` — writing the classification table above into the template so the answer is
defensible and looked-up rather than re-derived.
*What it gives up*: `impilo-connector`'s `enrollment_status` assertion continues to cross the bus,
so the ledger is not the only place `enrollment` state is asserted. That is a real correctness debt
and must be recorded, not glossed.

**Per-connector level of effort, so the total can be computed once the count is settled:**

| Connector | Option A/B (full conversion) | Option C (wrap) | Notes driving the estimate |
|---|---|---|---|
| `github-connector` | `L` | `M` | 249 source lines, 525 test lines, no cursor, no direct writes. Mechanical but new-package-shaped. |
| `hubspot-connector` | `L` | `M` | 285 / 546 lines. Adds PHI redaction logic that must survive the move. |
| `impilo-connector` | `XL` | `M` | 595 / 663 lines, two ingress paths (webhook and queue), seven logistics types plus the enrollment assertion. `XL` because it needs a business-logic ruling on Impilo semantics and a sanctioned-source decision that `packages/ocean/docs/producer-policy.md:37-38` reserves for Rob. |
| `linear-connector` | `L` | `M` | 252 / 470 lines. Simplest of the seven. |
| `mongodb-connector` | `XL` | `L` | 1157 source lines, **zero tests**, leader election, a durable resume-token cursor, and its own readiness probe. Converting the only untested service is `XL` on the missing safety net alone: the tests must be written first, and `tests/test_taskfile_test_coverage.py:77` currently *encodes* the absence as expected. |
| `pocar-connector` | `XL` | `M` | 315 / 304 lines, but the webhook schema is a self-declared PLACEHOLDER pending Brook engineering validation (`packages/ocean/services/pocar-connector/src/schema/pocar_webhook.py:3`), so conversion is blocked on an external confirmation. |
| `zcc-connector` | `L` | `M` | 274 / 394 lines; the "MEDIUM confidence" mapping (`packages/ocean/services/zcc-connector/src/normalizer.py:3-5`) makes the conversion verifiable only against a live Zoom account, which the offline test posture forbids — so the mapping risk transfers unchanged rather than growing. |

### Recommendation

**Option D, with one carve-out that is filed rather than done.** Producer policy already answers six
of the seven — they emit non-subject facts and should keep emitting, per
`packages/ocean/docs/producer-policy.md:11-12` — so converting them is work against the stated
policy. The seventh, `impilo-connector`'s `patient.enrolled` / `"enrollment_status": "enrolled"`
path, is a genuine catalog-subject assertion the gate structurally cannot catch, and it needs a
business-logic ruling from Rob before anyone writes code; the template should state the finding, the
classification table, and the open question, and the migration itself should be a filed decision
rather than a task an engineer picks up from a green gate.

### Level of effort

**`S`** — the deliverable is the classification table above written into the template's migration
section, with every citation already gathered; the per-connector conversion effort in the table
stays unspent under this recommendation, and the one item that would spend it is escalated rather
than started.

### Dependencies and risks

- **Must land first**: Item 3.2's anti-patterns page, since the migration section is best read as
  its companion — "here is the rule, here is where each existing connector falls under it."
- **Harder than it looks (1)**: the `impilo-connector` finding is a claim about *Impilo's*
  semantics, not about this repository. `"enrollment_status": "enrolled"` may be a denormalised
  convenience field on a signal event rather than an enrollment-state assertion. Nobody here can
  settle that; it is exactly the "never assume business logic" case.
- **Harder than it looks (2)**: any conversion also touches the service's `Dockerfile`, because
  `tests/test_ocean_bus_dependencies.py` asserts the image installs what `src/` imports — so adding
  `pulse-core` to a service's imports without adding it to the image produces a container that
  cannot start, and that gate is what catches it.
- **Harder than it looks (3)**: `mongodb-connector`'s untested state is *encoded as expected* at
  `tests/test_taskfile_test_coverage.py:77` (`assert untested == {"mongodb-connector"}`). Writing
  tests for it does not fail that gate (the set only shrinks if the directory appears, which would
  then make the assertion false and require the gate to be edited) — so anyone adding tests there
  must update that assertion in the same change or `task check` goes red for the right reason at the
  wrong moment.
- **If it could fail silently, doubt this first**: the classification of `hubspot-connector` as
  non-subject. `contact.created` / `contact.updated` sits closest to the `person` registry subject
  and to `communication_consent` (whose states are `unset`, `opted_in`, `opted_out` —
  `catalog/state_catalog.yaml:56-59`). Read
  `packages/ocean/services/hubspot-connector/src/normalizer.py` in full before publishing the table;
  if any HubSpot property maps to an opt-in or opt-out value, that connector joins `impilo` in the
  genuinely-asserting column and the recommendation gains a second carve-out.

---

## Item 3.4 — Scale and backpressure notes

### Current state

**Batching.** `POST /commands:batch` exists and is implemented at
`packages/pulse-ledger/src/pulse_ledger/api.py:769-791`, registered as
`@app.post(COMMANDS_BATCH_PATH, status_code=201)` with the path constant
`COMMANDS_BATCH_PATH = "/commands:batch"` at `packages/pulse-ledger/src/pulse_ledger/api.py:92`.
The whole body is five statements:

- `packages/pulse-ledger/src/pulse_ledger/api.py:787-788` — `if not isinstance(body, list): raise MalformedBatchBodyError()`
- `packages/pulse-ledger/src/pulse_ledger/api.py:789` — `split = [split_idempotency_key(item) for item in body]`
- `packages/pulse-ledger/src/pulse_ledger/api.py:790` — `declarations = [(declaration_from_request(item, writer), key) for item, key in split]`
- `packages/pulse-ledger/src/pulse_ledger/api.py:791` — `return [_commit_response(committer(declaration, key)) for declaration, key in declarations]`

**There is no maximum batch size.** No constant, no length check, no byte cap anywhere in
`packages/pulse-ledger/src/pulse_ledger/api.py`. The only guard is "the body must be a JSON array".
(`DEFAULT_BATCH_SIZE = 100` at `packages/pulse-ledger/src/pulse_ledger/relay.py:66` is the *outbox
relay's* publish batch, a different component on the ledger→bus hop, and is unrelated to this
route.)

**Partial failure is neither atomic nor itemised**, and the route's own docstring says so
(`packages/pulse-ledger/src/pulse_ledger/api.py:776-781`): "Declarations are built for the whole
array before any of them commits: a malformed or spoofed item further down the array aborts the
batch before its predecessors are attempted. Once committing starts, each item is its own call to
`committer` (its own transaction, as `/commands` already is) — the array is a convenience for the
backfill loader's single credential, not an atomic unit across items." So validation is
all-or-nothing (one bad item, zero writes), while commit is a plain list comprehension: an
`IllegalTransitionError` raised on item seven propagates to the 422 handler at
`packages/pulse-ledger/src/pulse_ledger/api.py:617` with **no record of the six items already
committed**. There is no HTTP 207 Multi-Status and no per-item result vocabulary. The client cannot
learn which items landed.

Status codes the route can return: 201 success
(`packages/pulse-ledger/src/pulse_ledger/api.py:769`); 401 `AuthenticationError` (`:575`); 403
`ActorSpoofError` (`:589`); 403 `BackfillActorRequiredError` (`:609`); 422 `IllegalTransitionError`
(`:617`); 422 `DeclarationError`, which covers `MalformedBatchBodyError` (`:642`). **No 429 and no
413 exist anywhere in the ledger API.**

The published contract for the route is one table row —
`docs/contracts/publishes.md:40`, verbatim: "`| `POST /commands:batch` | REST API | beta | backfill
mode, same validation; `backfill_genesis`/`reconstruction_gap` accepted only from the backfill actor
|`" — and it states no size, rate, or batch limit. The specification is equally silent:
`openspec/specs/command-api/spec.md:95-99` states only that "Bulk backfill SHALL use the same
endpoint family, legality validation, and single-writer guarantee as forward writes", and
`openspec/specs/command-api-serving/spec.md` does not contain the string `batch` at all.

**Retry and backoff.** Fully reported in Item 3.1's divergence table. Restated precisely for a
connector author:

- `pulse_core` defaults: `DEFAULT_MAX_ATTEMPTS = 4`
  (`packages/pulse-core/src/pulse_core/client.py:52`), `DEFAULT_BASE_DELAY_SECONDS = 0.5` (`:53`),
  `DEFAULT_MAX_DELAY_SECONDS = 8.0` (`:54`). The delay function
  (`packages/pulse-core/src/pulse_core/client.py:223-226`) is
  `delay = base * (2 ** (attempt - 1))`, returned capped at `maximum`. **Backoff is not jittered** —
  the module imports `dataclasses`, `json`, `time`, `uuid`, `collections.abc`, `dataclass`,
  `datetime`, `Enum`, `typing`, and `httpx`, and no randomness source at all. Worst-case wall clock
  across four attempts at the defaults is 0.5 + 1.0 + 2.0 = **3.5 seconds**.
- **On exhaustion `pulse_core` returns, it does not raise**:
  `packages/pulse-core/src/pulse_core/client.py:322-323` returns a `CommandResponse` still
  classified `TRANSIENT` with `attempts` set. A caller checking only
  `CommandResponse.is_success` (`packages/pulse-core/src/pulse_core/client.py:102-105`) silently
  drops the command. This is the single sharpest edge in the client contract.
- `verdict-relay` overrides all of it: `DECLARE_MAX_ATTEMPTS = 5`
  (`packages/verdict-relay/src/verdict_relay/declarer.py:70`),
  `DEFAULT_MAX_DELAY_SECONDS = 30.0` (`:73`), full jitter at `:289-291`, and **raises**
  `TransientExhaustedError` on exhaustion (`:287`).
- **A paired declaration doubles the budget.** `_pair_transition`
  (`packages/verdict-relay/src/verdict_relay/declarer.py:321-364`) calls `_submit_with_retry` a
  second time, so one row can consume up to **ten** attempts, and a transient-exhausted transition
  fails the run with the verdict already committed
  (`packages/verdict-relay/src/verdict_relay/declarer.py:326-329`).
- The consumer half of the client carries its own numbers:
  `max_messages: int = 10` and `wait_time_seconds: int = 20`
  (`packages/pulse-core/src/pulse_core/client.py:386-387`), `error_backoff_seconds: float = 5.0`
  (`:443`). The whole-pass exception handler at
  `packages/pulse-core/src/pulse_core/client.py:472-473` sleeps and swallows, and its own docstring
  at `:452-453` states "A pass that raises … is logged nowhere here."

**Durable cursors, operationally.** `packages/pulse-core/src/pulse_core/cursor.py` is 76 lines and
**stores nothing** — it is a JSON-nativity validator plus a path constant. Its whole surface:
`CURSOR_PATH_TEMPLATE = "/writers/{writer_id}/cursor"` (`packages/pulse-core/src/pulse_core/cursor.py:23`),
`cursor_path(writer_id)` (`:26-28`), `InvalidCursorError` (`:31-41`), `validate_cursor(cursor)`
(`:44-57`), and the private `_canonical` walker (`:60-76`). The contract it enforces is at
`packages/pulse-core/src/pulse_core/cursor.py:3-9`: the ledger "stores whatever a writer checkpoints
as opaque JSONB (`ledger.writer_state.cursor`, via `pulse_ledger.cursor`); the ledger never
interprets it… a cursor SHALL be JSON-native, because the crash/resume scenario the ledger-read spec
describes only holds if what a writer reads back is exactly what it wrote."

- **Storage**: table `ledger.writer_state`, via
  `packages/pulse-ledger/src/pulse_ledger/cursor.py` — `get_cursor` at `:34-46`, `put_cursor` at
  `:49-64` with `ON CONFLICT (writer_id) DO UPDATE SET cursor = EXCLUDED.cursor, updated_at = now()`
  at `:59`.
- **Routes**: `GET /writers/{writer_id}/cursor` and `PUT /writers/{writer_id}/cursor`, installed at
  `packages/pulse-ledger/src/pulse_ledger/api.py:669-696`, with `_require_own_writer` at
  `packages/pulse-ledger/src/pulse_ledger/api.py:658-667` raising `ActorSpoofError` → 403, and a
  missing cursor returning **404** (`packages/pulse-ledger/src/pulse_ledger/api.py:679-680`).
- **Requirement**: `openspec/specs/ledger-read/spec.md:41-48`, verbatim — "The ledger SHALL provide
  a writer-state facility keyed by writer id: a writer SHALL be able to persist and read back a
  cursor so a crashed run resumes without re-reading or re-declaring completed work." The isolation
  rule is at `:50-60`. **The specification states no freshness, staleness, or liveness requirement
  — only round-trip fidelity and isolation.** (Note for the work order: the writer-state routes are
  specified in `openspec/specs/ledger-read/spec.md`, not in
  `openspec/specs/command-api-serving/spec.md`, which contains neither `writer_state` nor `cursor`.)
- **`PulseCoreClient` has no cursor method.** A grep for `cursor` in
  `packages/pulse-core/src/pulse_core/client.py` returns nothing. The only client implementation is
  `LedgerCursorStore`, and it lives inside a connector:
  `packages/verdict-relay/src/verdict_relay/mart_reader.py:145-207`, with `load()` at `:190-197`
  (404 → `None`, else `raise_for_status()`) and `save()` at `:199-202`. **Neither has retry or
  backoff** — a 503 from the ledger on `save()` raises straight out and fails the run. Every future
  connector either re-implements this class or imports it from `verdict_relay`, which would be a
  connector depending on another connector.
- **How a connector resumes**, using the one worked example: page size `DEFAULT_PAGE_SIZE = 500`
  (`packages/verdict-relay/src/verdict_relay/mart_reader.py:49`); the cursor document carries
  `_CURSOR_PAGE_KEY = "computed_at"` and `_CURSOR_WATERMARKS_KEY = "watermarks"` (`:52-53`) in one
  save, so page position and the per-subject `as_of` watermark map advance together. The design note
  at `packages/verdict-relay/src/verdict_relay/mart_reader.py:12-17`: "A crash between a page's
  declarations and its `commit()` re-reads at most that one page", and the overlap comes back as
  D16 replays. `consent-ingress` uses the identical shape —
  `DEFAULT_PAGE_SIZE = 500` at `packages/consent-ingress/src/consent_ingress/row_source.py:53`.
- **What a stuck cursor looks like from the outside: nothing.** `updated_at` is written on every
  `put_cursor` (`packages/pulse-ledger/src/pulse_ledger/cursor.py:59`) and is read by no alarm, no
  metric, and no endpoint — it is only echoed in the GET response body
  (`packages/pulse-ledger/src/pulse_ledger/api.py:655`). There is no list-all-writer-cursors route:
  every route is per-`writer_id` and `_require_own_writer`
  (`packages/pulse-ledger/src/pulse_ledger/api.py:658-667`) means **an operator cannot read another
  writer's cursor at all** without that writer's own bearer credential. There is no admin or
  staleness view anywhere.

**Existing published limits worth quoting to a connector author.** `docs/contracts/consumes.md`
contains **exactly one** hard numeric limit, at `docs/contracts/consumes.md:83`, verbatim:

> `| EventBridge `ocean` bus | AWS managed bus | `boto3` / `aiobotocore`; bus name via `OCEAN_EVENT_BUS_NAME` | PutEvents entry cap (256 KB) rejects oversized envelopes; missing bus name would route to the account `default` bus, so it is never left unset |`

Its implementation is `MAX_ENTRY_BYTES = 256 * 1024` at
`packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py:30`, checked before the API call at
`packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py:116-121` so an oversized envelope
dead-letters with a legible reason. The Simple Queue Service row
(`docs/contracts/consumes.md:84`) states **no** numeric limit — no queue depth, no visibility
timeout, no receive limit, no retention. Neither `POST /commands:batch`
(`docs/contracts/publishes.md:40`) nor the cursor routes (`docs/contracts/publishes.md:41`) publish
any size or rate limit.

Every other hard limit in the repository, since a connector author will want the whole list:

| Value | Location |
|---|---|
| `MAX_ENTRY_BYTES = 256 * 1024` | `packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py:30` |
| `DLQ_MAX_RECEIVE_COUNT = 5` | `packages/ocean/libs/ocean-broker/src/ocean_broker/local_topology.py:43` |
| `SQS_MAX_MESSAGES = 10` | `packages/ocean/services/impilo-connector/src/sqs_consumer.py:19`, and four other services |
| `MAX_ATTEMPTS = 5` (outbox relay) | `packages/pulse-ledger/src/pulse_ledger/relay.py:56` |
| `INITIAL_BACKOFF_SECONDS = 1.0`, `BACKOFF_FACTOR = 2.0` | `packages/pulse-ledger/src/pulse_ledger/relay.py:61-62` |
| `DEFAULT_BATCH_SIZE = 100` (outbox relay) | `packages/pulse-ledger/src/pulse_ledger/relay.py:66` |
| `_MAX_BACKOFF_SECONDS = 60.0`, jittered | `packages/ocean/services/mongodb-connector/src/watcher.py:32`, applied at `:72` as `delay = min(2**retry_count + random.uniform(0, 1), _MAX_BACKOFF_SECONDS)` |
| `MAX_RECORDS_PER_CALL = 60`, `MAX_REQUESTS_PER_MINUTE = 100` | `packages/pulse-core/src/pulse_core/twenty_seed.py:75-76` |
| `MAX_TIMESTAMP_AGE_SECS = 300` | `packages/ocean/services/hubspot-connector/src/receiver.py:20` |
| `DEFAULT_PAGE_SIZE = 500` | `packages/verdict-relay/src/verdict_relay/mart_reader.py:49`; `packages/consent-ingress/src/consent_ingress/row_source.py:53` |
| `HEARTBEAT_INTERVAL_SECS = 60` | all six heartbeat modules, for example `packages/ocean/services/linear-connector/src/heartbeat.py:18` |

**`packages/pulse-core/src/pulse_core/twenty_seed.py:73-76` is the only place in the repository that
treats a rate limit as a first-class design constraint**, and its comment is the model a connector
should copy: "The dev instance's limits (twenty-dev-instance task 2.5). The loader stays inside them
by construction — chunked batch creates, one paced request at a time — rather than retrying 429s."
The `Pacer` at `packages/pulse-core/src/pulse_core/twenty_seed.py:286-305` implements it
(`self._interval = 60.0 / per_minute` at `:295`). The corresponding requirement is
`openspec/specs/twenty-seed-load/spec.md:72-88`, and it is scoped to the Twenty seed loader alone —
**no equivalent requirement exists for the command API, the batch route, or any connector.**

**`429` appears in exactly two places repository-wide**:
`packages/pulse-core/src/pulse_core/client.py:50` (in `_TRANSIENT_STATUS`, meaning "retry it") and
the `twenty_seed.py:74` comment above. **Nothing in the repository ever emits a 429.** There is no
server-side rate limiting and no admission control. The words `backpressure` and `throttl` have zero
occurrences in `packages/`, `docs/`, and `openspec/specs/` — the concept is absent from the codebase
and the specifications alike.

**Operational visibility: what a stuck connector looks like.** Six of the seven connectors run a
heartbeat at 60-second intervals publishing `connector.heartbeat` to the `ops` domain, for example
`packages/ocean/services/github-connector/src/heartbeat.py:25` and `:40`. Four carry the comment
`# Must be < 300s silence threshold` (`packages/ocean/services/linear-connector/src/heartbeat.py:18`
and three siblings) — **and no 300-second threshold is implemented anywhere.** The consumer side
upserts `connector_health.last_seen = now()`
(`packages/ocean/services/control-plane/src/handlers/heartbeats.py:13-36`, table at
`packages/ocean/infra/postgres/versions/0004_connector_health.py:26`), and **nothing reads that
table to raise an alert.** The heartbeat payload is `{"connector_id", "connector_name"}` only
(`packages/ocean/services/github-connector/src/heartbeat.py:33-36`) — no cursor position, no lag, no
processed count — so **a connector wedged on a stuck cursor heartbeats healthily forever.**

Health endpoints are liveness-only and uniformly content-free: `{"status": "ok", "service": ...}` at
`packages/ocean/services/github-connector/src/main.py:51-53` and six siblings; the ledger's is
`@app.get("/health", include_in_schema=False)` at
`packages/pulse-ledger/src/pulse_ledger/api_server.py:223`, deliberately with no `SELECT 1`
(`packages/pulse-ledger/src/pulse_ledger/api_server.py:43`). The single exception is
`mongodb-connector`: `/readyz` at
`packages/ocean/services/mongodb-connector/src/main.py:140-144` returns 200 "only when leader +
watchers + fresh token", checking `is_leader`, `manager_started`, and `token_fresh`. That is the one
probe in the repository that could reveal a stalled watcher — and it belongs to the one connector
with no tests. **There is no `/metrics` endpoint and no Prometheus anywhere**: a grep for
`prometheus` and `/metrics` across `packages/` returns zero files.

**The asymmetry is the finding.** The ledger→bus hop has real backpressure telemetry —
`packages/pulse-ledger/src/pulse_ledger/relay.py:17-18` states "`outbox_lag_seconds` is the age of
the oldest row still waiting, which is the quantity the p99 < 30 s SLO is stated over.
`dead_letter_depth` is what the monitor alarms on at >= 1", with per-pass counts `published`,
`dead_lettered`, `retried`, `deferred`, `max_lag_seconds` (`packages/pulse-ledger/src/pulse_ledger/relay.py:109-118`).
The connector→ledger hop — the direction this whole programme is about — has a 60-second "I am
alive" ping and a `{"status": "ok"}` string.

### Gap

The template cannot currently answer "what happens when the source produces faster than the command
API accepts", because the command API has no answer: no batch size cap, no rate limit, no 429, no
admission control, and no published throughput figure. It also cannot answer "what does a stuck
connector look like", because nothing observes a cursor's `updated_at`, no operator can read another
writer's cursor at all, and the heartbeat that exists proves liveness rather than progress. Both
gaps are worse than "undocumented": the numbers a connector author would want to be told are not
merely unwritten, they do not exist to be written.

### Options

**Option A — a documentation-only "Scale and limits" section stating the numbers that exist and
naming the ones that do not.**
*What it does*: quotes the 256 KB EventBridge entry cap, the `pulse_core` retry defaults, the
absence of a batch cap, the absence of 429, and the cursor's invisibility, and states each unknown
as an explicit unknown requiring measurement.
*What it costs*: `S`.
*What it gives up*: nothing is fixed. An honest inventory of holes is still an inventory of holes.

**Option B — Option A plus hoisting `LedgerCursorStore` from `verdict-relay` into `pulse_core`.**
*What it does*: gives every connector one durable-cursor client instead of each writing its own,
and is the natural place to add the retry the current implementation lacks.
*What it costs*: `M` — one new module in `packages/pulse-core/src/pulse_core/`, its tests written
first, and `packages/verdict-relay/src/verdict_relay/mart_reader.py` re-pointed at it (a shared-file
change other work must sequence around).
*What it gives up*: `verdict-relay` carries an 85 percent coverage floor
(`Taskfile.yml:145`), so moving code out of it changes that package's coverage denominator and the
move must not drop it below the floor.

**Option C — Option B plus a `MAX_BATCH_ITEMS` cap on `POST /commands:batch` returning HTTP 413.**
*What it does*: gives the batch route a stated, enforced limit a connector author can design
against.
*What it costs*: `XL` — it changes the published behaviour of a `beta` API surface
(`docs/contracts/publishes.md:40`) and adds a status code the specification does not describe, so it
is an OpenSpec change against `openspec/specs/command-api/spec.md`, not an implementation task.
*What it gives up*: nothing technically; it is blocked on process, not difficulty.

### Recommendation

**Option B.** The documentation section is necessary but not sufficient, and hoisting
`LedgerCursorStore` into `pulse_core` is the one change that removes a whole class of per-connector
divergence before eleven connectors each invent their own cursor client — the same argument as Item
3.1's, applied to the one piece of connector plumbing that is already duplicated in production code
rather than only in tests. Option C is the right eventual answer for the batch route and should be
filed as a follow-on OpenSpec proposal rather than folded in here.

### Level of effort

**`M`** — one new module in `packages/pulse-core/` with its tests written first, plus a
`docs/`-side scale section; the `verdict-relay` re-point is mechanical but touches a package with
its own 85 percent coverage floor, which is what keeps this above `S`.

### Dependencies and risks

- **Must land first**: nothing blocks the documentation half. The cursor hoist should follow Item
  3.1's conformance package if both are done, because the hoisted client is the natural first
  subject for the cursor-resume conformance assertion.
- **Harder than it looks (1)**: `LedgerCursorStore.save()`
  (`packages/verdict-relay/src/verdict_relay/mart_reader.py:199-202`) currently has no retry, and
  adding one is not free — a cursor `PUT` that retries after a successful-but-unacknowledged write
  is harmless (the upsert at `packages/pulse-ledger/src/pulse_ledger/cursor.py:59` is idempotent),
  but a retry that races a concurrent run of the same writer would clobber a newer cursor with an
  older one. `ledger.writer_state` has no version column and the routes carry no conditional-write
  semantics, so single-runner-per-writer is an unstated assumption the template must state.
- **Harder than it looks (2)**: the numbers a "scale and limits" section most wants —
  commands per second the API sustains, the safe batch size, the p99 commit latency — **do not
  exist anywhere and cannot be derived from the source.** They require a load measurement against a
  deployed ledger, which the offline test posture forbids and which no runbook describes. Every one
  of them must be written as `UNVERIFIED — requires measurement`, not estimated.
- **If it could fail silently, doubt this first**: the assumption that a connector notices an
  exhausted transient at all. `packages/pulse-core/src/pulse_core/client.py:322-323` **returns**
  rather than raising, and `CommandResponse.is_success`
  (`packages/pulse-core/src/pulse_core/client.py:102-105`) is `False` for it — so a connector that
  branches on `is_success` and logs a generic failure will drop commands under sustained load and
  look exactly like a connector with nothing to do. That is the stuck-connector failure mode nobody
  would notice, and the conformance suite's assertion number 5 is what would catch it.

---

## Item 3.5 — Green continuous integration on the example, and a catalog-version compatibility answer

### Current state

**What `.github/workflows/main.yml` runs.** Ninety-nine lines, three jobs, all
`runs-on: ubuntu-latest`. Triggers are `push` to `main` and `pull_request` with types
`[opened, synchronize, reopened, ready_for_review]` (`.github/workflows/main.yml:3-8`).

- **Job `quality`** (`.github/workflows/main.yml:11-50`): checkout pinned to
  `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1` (`:14-15`); a
  `actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0` step over
  `~/.cache/pre-commit` (`:17-20`); the local composite action
  `./.github/actions/setup-python-env` (`:22-23`);
  `arduino/setup-task@c0bc642852239c2689f73f4ea6459c29405f3c52 # v3.0.0` with `version: 3.x`
  (`:27-31`); `actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0` with
  `node-version: '22'` (`:40-44`); and one single `run:` — **`task check`**
  (`.github/workflows/main.yml:49-50`). The comment above it
  (`.github/workflows/main.yml:46-48`) states the constraint verbatim: "Must stay `task check` —
  tests/scaffold/cat4_ci_contract.py asserts every command in this file resolves to a defined
  Taskfile target or a known tool. This step previously ran `make check` against a repo with no
  Makefile, and every run failed for a week."
- **Job `tests-and-type-check`** (`.github/workflows/main.yml:52-74`): matrix
  `python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]` (`:56`) with `fail-fast: false`
  (`:57`); two `run:` commands — `uv run python -m pytest tests` (`:70-71`) and `uv run mypy`
  (`:73-74`).
- **Job `check-docs`** (`.github/workflows/main.yml:78-99`): two `run:` commands —
  `task docs:lock-guard` (`:95-96`) and `task docs:build` (`:98-99`).

**`tests/scaffold/cat4_ci_contract.py` asserts six things**, quoted from the file:
`test_workflows_exist` (`tests/scaffold/cat4_ci_contract.py:114-115`);
`test_every_task_invocation_resolves` (`:119-124`, failing with "`{wf.name}` job '{job}' runs
`task {target}`, which Taskfile.yml does not define"); `test_no_forbidden_task_runner` (`:128-135`,
against `FORBIDDEN_RUNNERS = {"make", "just", "rake", "invoke"}` at `:69`);
`test_every_command_is_a_known_tool` (`:139-145`, against a twenty-entry `KNOWN_TOOLS` at `:29-49`);
`test_third_party_actions_are_pinned_by_sha` (`:164-174`, `re.fullmatch(r"[0-9a-f]{40}", version)`);
`test_pinned_actions_record_their_version` (`:178-184`); `test_ci_runs_the_check_target`
(`:187-190`, `assert "check" in invoked`); and `test_check_target_is_ci_safe` (`:193-213`, which
walks the `check` target transitively and asserts neither `openspec` nor `openlore` appears, with
the message "`task check` transitively runs `{tool}`, which CI does not install; keep it in `verify`
instead").

**A defect in that gate worth recording**: three action pins in
`.github/workflows/auto-heal.yml` are all-zero placeholder SHAs —
`actions/checkout@0000000000000000000000000000000000000000 # v4.0` at
`.github/workflows/auto-heal.yml:16`, plus `:100` and `:111`, and the same placeholder at
`.github/workflows/ci-health.yml:11`. They are forty hex characters, so
`test_third_party_actions_are_pinned_by_sha` passes; they carry `# vX.Y` comments, so
`test_pinned_actions_record_their_version` passes. The gate is satisfied by a SHA that cannot
resolve on GitHub. Not a connector concern, but it belongs in the record.

**What adding a new package costs in that workflow: nothing.** `.github/workflows/main.yml`
enumerates no package and contains no `packages/` path anywhere. All five `run:` commands are
generic. The cost is paid entirely in `Taskfile.yml` and the root `pyproject.toml`, per the
seven-point registration table in Item 3.1, plus a new `tests/test_pricing_engine_scaffold.py`
following the `tests/test_twenty_projection_scaffold.py` precedent.

**One caveat a connector author must know**: the `tests-and-type-check` job runs
`uv run python -m pytest tests` (`.github/workflows/main.yml:71`) — the **root** `tests/` directory
only, matching `testpaths = ["tests"]` at `pyproject.toml:113`. A new package's own
`packages/pricing-engine/tests/` reaches continuous integration solely through
`task check` → `task test` → `TESTED_PATHS` in the `quality` job. Omit it from `Taskfile.yml:31` and
the suite runs nowhere while every job stays green.

**Badges: none exist.** Greps across every `README.md` (excluding `node_modules`, `.venv`, and
`site`) for `img.shields.io`, `badge.svg`, and the markdown image-link opener `[![` return zero
matches. The root `README.md` has a `## Status` section at lines 21–23 that links a planning report
(`.planning/reports/2026-08-03-program-status.md`), not continuous integration. The repository slug
from `git config --get remote.origin.url` is
`https://github.com/robford-brookai/pulse.git`, so the badge URL would be
`https://github.com/robford-brookai/pulse/actions/workflows/main.yml/badge.svg` linking to
`https://github.com/robford-brookai/pulse/actions/workflows/main.yml`. Note it can only be scoped to
the *workflow*, not to a package: `main.yml` has one `quality` job running one `task check`, so
there is no per-connector job whose status a badge could reflect.

**How the state catalog is versioned.** `catalog/state_catalog.yaml:28` declares
`catalog_version: 1.1.0`. `catalog/state_catalog.yaml:13-15` states the semver rule inline: "MAJOR
incrementing exactly on breaking releases — a release that removes a state, narrows a ValueSet, or
changes a transition's legality in either direction (pulse-runtime-readiness §4.3)."

The specification is `openspec/specs/catalog-versioning/spec.md`, three requirements:

- `openspec/specs/catalog-versioning/spec.md:8` — "Every release is an immutable snapshot"
  (scenarios at `:16`, `:22`)
- `openspec/specs/catalog-versioning/spec.md:28` — "Releases are classified against the
  breaking-change rule" (scenarios at `:35`, `:40`, `:51`, `:57`)
- `openspec/specs/catalog-versioning/spec.md:63` — "Breaking releases pay the migration ceremony"
  (scenarios at `:71`, `:77`, `:86`)

**The exact breaking-versus-additive rule**, `openspec/specs/catalog-versioning/spec.md:30-33`,
verbatim:

> "A release SHALL be classified breaking when, relative to the previous released version, it
> removes a state, narrows a ValueSet, or changes a transition's legality (in either direction — the
> rule is verbatim from runtime-readiness §4.3). Purely additive releases — new states, new
> commands, widened ValueSets, new programs — SHALL classify non-breaking."

With the qualifier at `openspec/specs/catalog-versioning/spec.md:45-49`: "Legality is a property of
a `(subject, from, to)` pair both versions can express: an edge whose endpoint state exists only in
the newer version was undefined before, not illegal… **Removed commands or programs are
deliberately NOT breaking under the §4.3 rule.**"

**Exactly what a breaking release requires of consumers**,
`openspec/specs/catalog-versioning/spec.md:65-69`, verbatim:

> "A breaking release SHALL increment the major version and SHALL ship a migration note in the
> release PR containing a consumer checklist — Twenty metadata redeploy, ConceptMap regeneration,
> and a rule_version bump if verdict criteria reference the changed codes. The check suite SHALL
> fail a breaking release missing either the major bump or the migration note, so the ceremony is
> enforced by CI, not convention."

`docs/runbooks/catalog-release.md` gives the five-step procedure: edit
`catalog/state_catalog.yaml` and bump `catalog_version` (`docs/runbooks/catalog-release.md:14-17`);
regenerate with `uv run python -m pulse_core.catalog_gen` (`:18-19`); freeze the snapshot into
`catalog/releases/v<version>.yaml` and append its sha256 line to
`catalog/releases/MANIFEST.sha256`, which is append-only (`:20-22`); for a breaking release only,
add `catalog/releases/v<version>-migration.md` with the consumer checklist (`:23-26`); open and
merge the pull request, after which
`.github/workflows/catalog-release.yml` runs `task catalog:release APPLY=1` (`:27-29`).

**There is no consumer-notification step anywhere.** The "consumer checklist" is three items —
Twenty metadata redeploy, ConceptMap regeneration, `rule_version` bump — and none of them is a
connector. There is no consumer registry, no notification, and nothing that tells a connector author
their vocabulary changed. The ceremony is entirely internal to the release pull request.

**How a connector obtains its command types — and what happens at a version bump.** This is the
most important finding in the item, so it is traced in full.

`packages/pulse-core/src/pulse_core/generated/__init__.py` is a **committed, git-tracked** generated
file (6,664 bytes; it appears in `git ls-files` and no `generated` entry exists in `.gitignore`). Its
header, `packages/pulse-core/src/pulse_core/generated/__init__.py:1-7`:

> "Generated command surface — DO NOT EDIT. Generated by `pulse_core.catalog_gen` from
> `catalog/state_catalog.yaml` (catalog_version: 1.1.0). Regenerate with:
> `uv run python -m pulse_core.catalog_gen`"

It exports `CATALOG_VERSION = "1.1.0"`
(`packages/pulse-core/src/pulse_core/generated/__init__.py:18`), `TRANSITIONS` (`:20`),
`SUBJECT_TYPES` (`:77`), `COMMAND_TYPES` (`:83`), `BACKFILL_ONLY_COMMAND_TYPES` (`:96`), and
`parse_command` (`:214`). The generator is
`packages/pulse-core/src/pulse_core/catalog_gen.py`, writing to
`GENERATED_PATH = PACKAGE_ROOT / "generated" / "__init__.py"`
(`packages/pulse-core/src/pulse_core/catalog_gen.py:38`) from
`CATALOG_PATH = REPO_ROOT / "catalog" / "state_catalog.yaml"` (`:43`), emitting the version literal
at `:186`. Its docstring at `packages/pulse-core/src/pulse_core/catalog_gen.py:1-14` states "**The
generated module is committed and version-pinned to `catalog_version`**; producers and the
write-path validator both import it", and at `:39-41` "**Only the committed generated module ships
in the wheel.**"

**Answer: a connector at a catalog version bump silently keeps working against a stale vocabulary.**
Three candidate failure modes, all traced to ground:

**(a) Fails at import — no.** `packages/pulse-core/src/pulse_core/generated/__init__.py` contains no
assertion, no version comparison, and no import-time check. It is a flat module of literals and
Pydantic models.

**(b) Fails at boot — a guard exists and is never called.**
`packages/pulse-ledger/src/pulse_ledger/validation.py:190-193`:

```
def require_catalog_version(configured: str) -> None:
    """Boot-time guard: refuse to run against a catalog release the tables were not built from."""
    if configured != CATALOG_VERSION:
        raise CatalogVersionMismatchError(configured=configured, generated=CATALOG_VERSION)
```

The module docstring at `packages/pulse-ledger/src/pulse_ledger/validation.py:5-6` claims "The
service refuses to boot when the generated tables' version disagrees with the catalog release it is
configured for (D18)." **That claim is not implemented.** A repository-wide grep for
`require_catalog_version` returns exactly four hits: the definition at
`packages/pulse-ledger/src/pulse_ledger/validation.py:190`, and three in tests —
`packages/pulse-ledger/tests/test_validation.py:15` (import), `:138`, and `:143`. **No production
code path calls it.** There is no app-factory call, no startup hook, nothing in
`packages/pulse-ledger/src/pulse_ledger/api_server.py`. The guard is tested-but-dead.

**(c) Fails at runtime, server-side — no; the API never sees a client catalog version.**
Both write endpoints route through `declaration_from_request`
(`packages/pulse-ledger/src/pulse_ledger/api.py:265-273`), which reads no `catalog_version` field
from the body. Every occurrence of `catalog_version` in
`packages/pulse-ledger/src/pulse_ledger/api.py` is **outbound only** — the server stamping its own
version onto a rejection: `:406`, `:478`, and `:622` inside the `IllegalTransitionError` handler
that returns HTTP 422. And that value is hardcoded from the *server's* generated module —
`packages/pulse-ledger/src/pulse_ledger/validation.py:45` is `self.catalog_version = CATALOG_VERSION`.

**A fourth finding fell out of this trace and is worse than any of the three.** The command API
**never validates `event_type` against `COMMAND_TYPES` at all.** The only command-vocabulary check
in the write path is `if declaration.event_type in BACKFILL_ONLY_COMMAND_TYPES and writer.writer_id != BACKFILL_ACTOR_ID`
(`packages/pulse-ledger/src/pulse_ledger/api.py:271`), which restricts the backfill vocabulary but
never rejects an unknown one. `commit_declaration`
(`packages/pulse-ledger/src/pulse_ledger/commit.py:366-401`) validates the *subject type* and the
*transition*, never the command type; the event type is passed straight through to `_insert_event`
at `packages/pulse-ledger/src/pulse_ledger/commit.py:411`. This means
`openspec/specs/command-api/spec.md:80-81` — "a command not present in the generated set SHALL be
rejected" — and its scenario at `:85-88` ("Unknown command type is rejected") are **specified and
unimplemented**. Marked here as a finding, not a task; verifying it against a running service was
not possible offline, so treat the *behavioural* consequence as `UNVERIFIED` while the code path is
verified.

**So the observable behaviour at a catalog major bump is:** a connector holding a stale
`pulse_core.generated` submits a command; if the subject and target state are still legal under the
server's newer catalog, the write **succeeds**, stamped `rule_version = CATALOG_VERSION` — the
*server's* version (`packages/pulse-ledger/src/pulse_ledger/commit.py:390`, `:503`, `:537`) — with
nothing recording that the client was stale. If the transition became illegal, the connector gets a
422 whose `catalog_version` field names the *server's* version, not a mismatch diagnosis, and must
infer version drift from a legality rejection. **There is no catalog-version mismatch error path
reachable over HTTP at all.**

**That stale clients are a real, current state is visible in the tree**: fixtures in two packages
still carry `"catalog_version": "appendix-c-v0.7"` — an entirely different versioning scheme from
today's semver — at `packages/verdict-relay/tests/test_declarer.py:71`,
`packages/verdict-relay/tests/test_fixture_corpus.py:69`,
`packages/verdict-relay/tests/test_run.py:65`,
`packages/verdict-relay/tests/test_coverage_first_declare.py:55`, and
`packages/identity/tests/test_resolver.py:65`.

**The one drift gate that does exist is same-tree only.** `tests/test_catalog_consumer_contract.py`
asserts four equalities — `:29` `assert _catalog()["catalog_version"] == generated.CATALOG_VERSION`,
`:32` on `SUBJECT_TYPES`, `:39` on `TRANSITIONS`, `:42` on `COMMAND_TYPES`. Its docstring
(`tests/test_catalog_consumer_contract.py:1-10`) frames it as acting as a downstream consumer
resolving the contract from its two pinned surfaces. The stronger sibling is
`packages/pulse-core/tests/test_catalog_gen.py:23`,
`assert catalog_gen.render_module(catalog) == GENERATED_PATH.read_text()` — the
render-equals-committed drift test the runbook names at `docs/runbooks/catalog-release.md:18-19`.
Both prove the committed generated module matches the head catalog **file in the same working
copy**. Neither can say anything about whether a *deployed* connector's installed `pulse_core`
matches the catalog a *running* ledger was built from.

**No pinning mechanism exists.** Every consumer declares a bare, unversioned workspace dependency —
`packages/pulse-ledger/pyproject.toml:16` is `"pulse-core",` with `:40`
`pulse-core = { workspace = true }`, and the same shape appears in
`packages/identity/pyproject.toml:9` and `:16`, `packages/schedules/pyproject.toml:9` and `:20`,
`packages/consent-ingress/pyproject.toml:15` and `:19`, and
`packages/verdict-relay/pyproject.toml:13` and `:17`. No `>=`, `==`, or `~=` constraint on
`pulse-core` appears anywhere. The `pulse-core` package version is `0.1.0`
(`packages/pulse-core/pyproject.toml:3`) and has never moved with the catalog, so pinning
`pulse-core==0.1.0` would pin nothing about the vocabulary. There is no `catalog.lock`. The
checksums in `catalog/releases/MANIFEST.sha256` cover the two frozen snapshots
(`catalog/releases/v1.0.0.yaml`, `catalog/releases/v1.1.0.yaml`) and nothing checksums
`packages/pulse-core/src/pulse_core/generated/__init__.py`.

**The GitHub Actions budget.** Continuous integration is **currently running and green**. Verified
directly: `gh` is authenticated as `robford-brookai`, and `gh run list` shows the most recent
completed `Main` run as `success` at 2026-08-23T00:15:52Z (run id 32607396827, "Merge pull request
#270", 3m0s), with a further `Main` run in progress and prior runs green. **The budget figure itself
is `UNVERIFIED`** and cannot be read from within the repository: the billing endpoint requires
scopes the authenticated token does not hold (its scopes are `delete_repo`, `gist`, `project`,
`read:org`, `repo`, `workflow` — no `admin:org`, no billing read). Note that
`docs/runbooks/catalog-release.md:36-38` still asserts "the account budget is currently $0, which
rejects runs; check `settings/billing/budgets` before trusting a green merge to have deployed" —
that statement is contradicted by runs executing successfully today, so **the runbook is stale or
its claim was always about the Snowflake secrets prerequisite rather than a live block.** Treat it
as a documentation defect to correct, not as a live constraint on any recommendation here.

### Gap

The example's continuous integration is already green and needs nothing — but the template has no
catalog-version compatibility answer at all, and the honest answer is the worst of the three
possibilities the work order named: a connector holding a stale generated vocabulary **silently
keeps working**, its writes stamped with the server's newer `rule_version`, with no import failure,
no boot guard (the guard exists at
`packages/pulse-ledger/src/pulse_ledger/validation.py:190-193` and is never called), no server-side
handshake, no version pin, no checksum, and no notification path in the release ceremony. The only
signal a connector author ever gets is an eventual HTTP 422 that names the server's version and
looks like an ordinary legality rejection.

### Options

**Option A — document the answer, add a badge, and stop there.**
*What it does*: the template states plainly that a stale connector fails silently, tells the author
to re-run `uv sync` and re-read `catalog/releases/MANIFEST.sha256` after any catalog release, and
adds
`https://github.com/robford-brookai/pulse/actions/workflows/main.yml/badge.svg` to the root
`README.md`.
*What it costs*: `S` for the section, `XS` for the badge.
*What it gives up*: the failure mode remains. Documentation does not make a stale connector notice.

**Option B — Option A plus a connector-side startup assertion, and wiring the dead guard.**
*What it does*: two mechanical changes. First, call the existing
`require_catalog_version` from the ledger's startup path so a ledger built against one catalog
cannot serve while configured for another — the behaviour
`packages/pulse-ledger/src/pulse_ledger/validation.py:5-6` already claims. Second, give the template
a startup pattern: the connector pins the catalog version it was written against as a module
constant, compares it to `pulse_core.generated.CATALOG_VERSION` at startup, and refuses to run — or
at minimum logs at `ERROR` — on a **major** mismatch, which is the only class the breaking rule at
`openspec/specs/catalog-versioning/spec.md:30-33` says can change legality.
*What it costs*: `M` — a call site plus tests in `packages/pulse-ledger/`, and a documented pattern
plus a conformance assertion in the template.
*What it gives up*: it detects a mismatch only between a connector and *its own installed*
`pulse_core`, not between the connector and the server it is talking to. Two components in the same
working copy always agree, so this catches the deployed-drift case only when the connector is
installed separately — which is precisely the out-of-repository case that matters.

**Option C — Option B plus a server-side catalog-version handshake.**
*What it does*: the command API accepts an optional `catalog_version` on the request (or an
`X-Pulse-Catalog-Version` header), compares it to its own `CATALOG_VERSION`, and rejects on a major
mismatch with a distinct reason code — closing the loop so a stale connector learns immediately
instead of eventually.
*What it costs*: `XL` — it adds a field and a rejection class to a published API surface, so it is
an OpenSpec change against `openspec/specs/command-api/spec.md` plus a decision about whether a
minor mismatch warns or rejects. It would also naturally carry the fix for the unimplemented
"Unknown command type is rejected" scenario (`openspec/specs/command-api/spec.md:85-88`), since both
are the same missing validation boundary.
*What it gives up*: nothing technical. It is blocked on process and on a decision, not on
difficulty.

### Recommendation

**Option B, with Option C filed as a follow-on OpenSpec proposal.** Wiring
`require_catalog_version` costs one call site and makes a docstring true that is currently false,
and the connector-side startup assertion gives the template a concrete, copyable answer to "what do
I do when the catalog version changes" instead of silence. Option C is the only change that actually
closes the deployed-drift case and should be proposed on its own merits alongside the unimplemented
command-type validation it shares a boundary with — but it needs a specification change and a
decision, so folding it in here would block everything else behind it.

### Level of effort

**`M`** — one call site plus its tests in `packages/pulse-ledger/`, one documented startup pattern
plus one conformance assertion in the template, and an `XS` badge line; the work is small but
touches a shared module (`packages/pulse-ledger/src/pulse_ledger/validation.py`) and needs its tests
written first, which is what keeps it above `S`.

### Dependencies and risks

- **Must land first**: nothing for the badge or the documentation. The connector-side startup
  assertion is best expressed as a conformance-suite assertion, so Item 3.1 is its natural home if
  both are done.
- **Harder than it looks (1)**: `require_catalog_version(configured)` takes a *configured* version
  string, which implies a configuration key that **does not exist today** — no environment variable
  in the tree supplies it. Wiring the guard therefore also means defining that key, naming it in the
  deploy runbook (`docs/runbooks/pulse-command-api-deploy.md`), and deciding its default, and a
  wrong default would refuse to boot a currently-working service. This is the part most likely to
  turn `M` into `L`.
- **Harder than it looks (2)**: a connector-side major-version assertion is only as good as the
  version the connector pins, and there is no mechanism to keep that pin honest — no
  `catalog.lock`, no checksum over the generated module, and `pulse-core`'s own package version
  (`0.1.0`, `packages/pulse-core/pyproject.toml:3`) is decoupled from `CATALOG_VERSION`. A pin that
  is hand-updated will rot.
- **Harder than it looks (3)**: a badge scoped to `main.yml` reflects the whole repository, not the
  connector. Because `main.yml` has one `quality` job running one `task check`
  (`.github/workflows/main.yml:49-50`), a per-connector badge would require a separate workflow or
  job — and `tests/scaffold/cat4_ci_contract.py:139-145` constrains what a new job may run to
  `KNOWN_TOOLS` plus defined Taskfile targets. Recommend a repository-level badge and an explicit
  sentence saying it is repository-level.
- **If it could fail silently, doubt this first — and this is the single most consequential value in
  this report**: the assumption that a running ledger and a running connector share a catalog
  version. Nothing enforces it, nothing checks it, nothing reports it, and the one guard written to
  enforce it is never invoked. Before trusting any deployment, the value to verify by hand is
  `pulse_core.generated.CATALOG_VERSION` as installed in the connector's own environment, compared
  against the version the ledger stamps into `rule_version` on a real committed event. If those two
  strings differ and everything looks fine, that is the failure mode, not the absence of one.

---

## Cross-item summary

| Item | Level of effort | One-line verdict |
|---|---|---|
| 3.1 Conformance suite | `XL` | Nothing shared exists; seven copy-pasted conftests and six `ScriptedApi` reimplementations prove the divergence has already begun, and the out-of-repository distribution question needs Rob. |
| 3.2 Anti-patterns document | `S` | All four candidates are located and cited; ranking them by whether anything catches them is the missing deliverable, and direct pulse-Postgres writes rank first because nothing gates them. |
| 3.3 Migration story | `S` | Six of seven connectors emit only non-subject facts and should be left alone; `impilo-connector` genuinely asserts `enrollment` state through a false negative the gate's own design accepted in writing. |
| 3.4 Scale and backpressure | `M` | The command API has no batch cap, no rate limit, no 429, and no admission control, and a stuck cursor is invisible from outside — hoisting `LedgerCursorStore` into `pulse_core` is the one change worth making now. |
| 3.5 Catalog-version compatibility | `M` | A stale connector silently keeps working; the boot guard that would catch it exists at `packages/pulse-ledger/src/pulse_ledger/validation.py:190-193` and is called from nowhere but tests. |

**Single most consequential finding**: a connector holding a stale
`pulse_core.generated` vocabulary keeps writing successfully after a breaking catalog release, and
its events are stamped with the *server's* `rule_version`
(`packages/pulse-ledger/src/pulse_ledger/commit.py:390`), so the ledger carries no record that the
declaration came from a stale writer. Every mechanism that would catch it is absent or inert: no
import assertion, no version pin, no checksum, no server-side handshake, no consumer notification in
the release ceremony (`openspec/specs/catalog-versioning/spec.md:65-69`), and a boot guard defined
at `packages/pulse-ledger/src/pulse_ledger/validation.py:190-193` whose only four call sites in the
entire repository are its own definition and three lines of its own test file.
