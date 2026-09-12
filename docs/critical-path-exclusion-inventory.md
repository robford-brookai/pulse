# Critical-path exclusion inventory

What a green `task check` does **not** cover, and why each gap is or is not acceptable on a path a
PULSE event can travel. Written for `critical-path-verification` task 2.2; the spec clause it
answers is *"a reachable-path exclusion inventory SHALL identify each inherited service exclusion,
owner and disposition"*, and its companion, *"confirmed reachable injection or leakage SHALL block
readiness until its focused fix merges"*.

The gate under this page is `tests/test_critical_path_debt_inventory.py`. It is not a formatting
check: it re-derives the suppression rows by running ruff with the suppressions switched off, it
re-derives every service's reachability from the bus topology, and it fails while any row sits at
`fix-required`. A row cannot be added, dropped or softened without the tree agreeing.

## How reachability is decided

"Reachable" here means *on a path a PULSE event travels*, not *running somewhere*. It is computed,
never asserted:

- **`bus-consume`** — the service is a key in `ocean_broker.catalog.CONSUMER_DOMAINS`, which is the
  single table behind both the Terraform rules and the LocalStack topology. A service in it has a
  rule and a queue delivering PULSE events to it.
- **`bus-publish`** — the service imports `ocean_broker`, which by ADR-0002 is what a publish site
  does: one publisher, one addressing table, thirteen sites.
- **`off-bus`** — neither. Exactly one service is in this state today (`stacte-bridge`), and the
  gate pins that fact, because every deferral below that rests on it stops being justified the day
  it changes.
- **`n/a`** — not a service: a script, a test tree, or a tree-wide toolchain exclusion.

Owner roles are roles, not people: `ocean-service-owner` (a service under
`packages/ocean/services/`), `ocean-platform-owner` (`packages/ocean/libs` and
`packages/ocean/scripts`), `ocean-test-owner` (`packages/ocean/tests`), `pulse-platform-owner`
(everything first-party).

## What the audit found

**No reachable SQL injection.** All ten production `S608` sites build SQL by interpolating an
*identifier* — a table or column name — and in every case the interpolated name comes from a
module-level allowlist (`_ENTITY_TABLE_MAP`), a literal tuple being iterated, a literal ternary, or
a list of fixed `SET` fragments. No caller-supplied string reaches query text on any of them. The
five with the least protection by construction are in `stacte-bridge`, which is off-bus. The
first-party PULSE tree reports no security findings at all under an isolated ruff run — its one
string-built query (`pulse_ledger.reads.enumerate_state`) validates the two values it interpolates
against the generated catalog and binds everything else.

**One reachable redaction defect, fixed in this change.**
`verdict_relay.mart_reader` quoted the offending cell value into `MartContractError` — both in the
timestamp rejections and in every row name — and `run.run_once` logs that message verbatim. The
kit's identical validator next door (`pulse_core.connector.rows.required_timestamp`) refuses to
quote it, for the stated reason that a timestamp column fed from a drifted source "could hold
anything, including payload content". The verdict mart is not first-party data. Fixed here: the
message names the column, and the row name carries the two pseudonymous identifier columns only.

**Three deferred risks with reproducers**, all of the same shape — text that originates outside the
first-party boundary being re-rendered into a first-party log line. They are not confirmed leaks
today, so each carries an owner and an executable reproducer rather than a fix.

## Inventory

| Path | Exclusion | Sites | Owner role | Reachability | Risk | Disposition | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `packages/ocean/services/**` | mypy | 16 | ocean-service-owner | bus-publish+consume | medium | deferred | 217 errors at absorption (DNA-779); libs are typed, services are not |
| `packages/ocean/services/**` | coverage | 16 | ocean-service-owner | bus-publish+consume | medium | deferred | suites run in `test:services`, outside the coverage floor (DNA-779) |
| `packages/ocean/tests/**` | tests | 1 | ocean-test-owner | n/a | medium | deferred | ADR-0002: ~60 pre-existing cross-service failures; four self-contained files named into `TESTED_PATHS` |
| `packages/ocean/libs/ocean-connector-mcp` | coverage | 1 | ocean-platform-owner | n/a | low | deferred | outside the migration, 0% covered (DNA-779); not on a bus path |
| `pyproject.toml` | mypy-override | 1 | ocean-platform-owner | n/a | low | accepted | `ignore_missing_imports` for `aws_msk_iam_sasl_signer.*`: no py.typed and no stubs on PyPI; deleted with the Kafka teardown (task 9.2) |
| `packages/ocean/scripts/equivalence_harness.py` | S608 | 1 | ocean-platform-owner | n/a | low | accepted | `capture_query` rejects any table outside `COLUMN_CLASSES` before interpolating it; a one-shot migration gate, not a runtime path |
| `packages/ocean/scripts/warehouse_smoke.py` | S607 | 1 | ocean-platform-owner | n/a | low | accepted | operator smoke script invoking a tool by name; no untrusted input |
| `packages/ocean/services/agent-worker/src/claim.py` | S311 | 1 | ocean-service-owner | bus-publish+consume | low | accepted | `random.uniform` for a persona claim delay; simulation timing, not a secret |
| `packages/ocean/services/agent-worker/src/consumer.py` | S311 | 1 | ocean-service-owner | bus-publish+consume | low | accepted | persona approve-rate draw; a simulated decision, not an authorisation |
| `packages/ocean/services/call-simulator/src/call_sim.py` | S311 | 3 | ocean-service-owner | bus-publish+consume | low | accepted | ring/answer/talk timings in a simulator; the whole service is synthetic |
| `packages/ocean/services/control-plane/src/escalation.py` | S608 | 1 | ocean-service-owner | bus-publish+consume | medium | deferred | table and id column come from a literal ternary on `entity_type`; no caller string reaches the text |
| `packages/ocean/services/control-plane/src/handlers/tickets.py` | S608 | 1 | ocean-service-owner | bus-publish+consume | medium | deferred | `SET` fragments are fixed literals chosen by branch; every value is a bind parameter |
| `packages/ocean/services/event-store/src/main.py` | S104 | 1 | ocean-service-owner | bus-consume | low | accepted | container bind address under `__main__`; exposure is the task definition, not the code |
| `packages/ocean/services/graph-projection/tests/test_rebuild_patients.py` | S106 | 1 | ocean-service-owner | bus-consume | low | accepted | fixture connection string in a test; no live credential |
| `packages/ocean/services/mongodb-connector/src/leader.py` | S110 | 1 | ocean-service-owner | bus-publish | low | accepted | swallowed `close()` during lock release; a raise there would replace the real cause |
| `packages/ocean/services/mongodb-connector/src/leader.py` | S324 | 1 | ocean-service-owner | bus-publish | low | accepted | md5 derives a stable advisory-lock id from a constant service name; not a security primitive |
| `packages/ocean/services/mongodb-connector/src/watcher.py` | S311 | 1 | ocean-service-owner | bus-publish | low | accepted | retry backoff jitter |
| `packages/ocean/services/slack-bot/src/bolt_app.py` | S106 | 1 | ocean-service-owner | bus-publish+consume | low | accepted | literal `"stubbed"` on the PHI-store-unconfigured branch; the branch exists to avoid sending a real value |
| `packages/ocean/services/slack-bot/src/main.py` | S110 | 1 | ocean-service-owner | bus-publish+consume | low | accepted | swallowed gather during shutdown, with `return_exceptions=True` already set |
| `packages/ocean/services/slack-bot/src/thread_manager.py` | S311 | 2 | ocean-service-owner | bus-publish+consume | low | accepted | 3-9s batch flush jitter, so replies read as organic |
| `packages/ocean/services/slack-bot/src/thread_manager.py` | S608 | 1 | ocean-service-owner | bus-publish+consume | medium | deferred | `key_column` is a private-method argument passed only the literals `"task_id"`/`"ticket_id"` |
| `packages/ocean/services/slack-bot/tests/test_ai_summary.py` | S106 | 3 | ocean-service-owner | bus-publish+consume | low | accepted | fixture tokens in a test |
| `packages/ocean/services/stacte-bridge/src/crud_api.py` | S608 | 1 | ocean-service-owner | off-bus | medium | deferred | table/pk pair iterated from a literal tuple; service is off-bus, so no PULSE event reaches it |
| `packages/ocean/services/stacte-bridge/src/graph_search.py` | S608 | 1 | ocean-service-owner | off-bus | medium | deferred | same literal-tuple traversal; off-bus |
| `packages/ocean/services/stacte-bridge/src/indexer.py` | S608 | 3 | ocean-service-owner | off-bus | medium | deferred | table and pk come from `_ENTITY_TABLE_MAP`, which raises on an unknown `entity_type`; off-bus |
| `packages/ocean/services/warehouse-sync/src/main.py` | S104 | 1 | ocean-service-owner | bus-consume | low | accepted | container bind address under `__main__` |
| `packages/ocean/services/warehouse-sync/src/main.py` | S608 | 1 | ocean-service-owner | bus-consume | medium | deferred | the interpolated fragment is `", ".join(["(%s, %s)"] * len(batch))` — a placeholder count; every event value is bound |
| `packages/ocean/tests/gates/cat3_connectivity.py` | S310 | 3 | ocean-test-owner | n/a | low | accepted | connectivity gate opening fixed local URLs |
| `packages/ocean/tests/gates/test_patients_read_only.py` | S608 | 1 | ocean-test-owner | n/a | low | accepted | the gate's own source-scan pattern, not an executed query |
| `packages/ocean/tests/integration/conftest.py` | S110 | 1 | ocean-test-owner | n/a | low | accepted | best-effort teardown in a fixture |
| `packages/ocean/tests/integration/conftest.py` | S607 | 1 | ocean-test-owner | n/a | low | accepted | `docker`/`psql` invoked by name in a fixture |
| `packages/ocean/tests/integration/conftest.py` | S608 | 1 | ocean-test-owner | n/a | low | accepted | fixture truncation statement over literal table names |
| `packages/ocean/tests/integration/test_localstack_delivery.py` | S310 | 1 | ocean-test-owner | n/a | low | accepted | LocalStack endpoint on localhost |
| `packages/ocean/tests/integration/test_localstack_delivery.py` | S607 | 1 | ocean-test-owner | n/a | low | accepted | `docker` invoked by name |
| `packages/ocean/tests/integration/test_migration_chain.py` | S607 | 1 | ocean-test-owner | n/a | low | accepted | migration tool invoked by name |
| `packages/ocean/tests/requirements/conftest.py` | S608 | 1 | ocean-test-owner | n/a | low | accepted | fixture query over literal table names |
| `packages/ocean/tests/requirements/test_AI_01.py` | S106 | 3 | ocean-test-owner | n/a | low | accepted | fixture tokens |
| `packages/ocean/tests/requirements/test_AUDIT_03.py` | S607 | 1 | ocean-test-owner | n/a | low | accepted | tool invoked by name |
| `packages/ocean/tests/requirements/test_AUDIT_03.py` | S608 | 1 | ocean-test-owner | n/a | low | accepted | audit assertion query over literal table names |
| `packages/ocean/tests/requirements/test_ZCC_01.py` | S106 | 1 | ocean-test-owner | n/a | low | accepted | fixture token |
| `packages/ocean/tests/unit/test_warehouse_smoke.py` | S607 | 1 | ocean-test-owner | n/a | low | accepted | tool invoked by name |

## Reachable-path findings

Findings from the bounded audit of write and consume paths, as opposed to the configured exclusions
above. Each `deferred` row names a reproducer that demonstrates the exposure today, so the fix
cannot land without the row being re-dispositioned.

| Path | Finding | Owner role | Reachability | Risk | Disposition | Reproducer |
| --- | --- | --- | --- | --- | --- | --- |
| `packages/verdict-relay/src/verdict_relay/mart_reader.py` | mart cell value quoted into a logged rejection | pulse-platform-owner | n/a | high | fixed | `test_critical_path_debt_inventory.py::test_mart_contract_rejections_do_not_echo_the_offending_cell` |
| `packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py` | transport exception text can embed the envelope in `eventbridge_publish_failed` | ocean-platform-owner | n/a | high | deferred | `test_critical_path_debt_inventory.py::test_deferred_risk_transport_error_text_reaches_the_publish_failure_log` |
| `packages/pulse-ledger/src/pulse_ledger/relay.py` | the same transport text is persisted to `ledger.outbox.last_error` | pulse-platform-owner | n/a | high | deferred | `test_critical_path_debt_inventory.py::test_deferred_risk_transport_error_text_reaches_the_publish_failure_log` |
| `packages/pulse-core/src/pulse_core/client.py` | 200 bytes of an unrecognised response body embedded in the error five declarers log | pulse-platform-owner | n/a | high | deferred | `test_critical_path_debt_inventory.py::test_deferred_risk_ledger_response_body_reaches_the_rejection_message` |

## What is out of scope here

Reformatting the legacy tree, and closing the mypy/coverage exclusions themselves — design.md is
explicit that neither belongs in this change. This page accounts for them; it does not resolve
them. The two fixed-by-configuration items (`aws_msk_iam_sasl_signer`, the Kafka half of
`ocean-broker`) disappear with the Kafka teardown rather than being burned down here.
