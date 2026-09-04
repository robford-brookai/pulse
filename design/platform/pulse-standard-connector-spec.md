# PULSE Standard Connector Specification — moved

This spec has one canonical copy, and it is not this file:

**`openspec/specs/connectors/pulse-standard-connector-spec.md`**

That copy is written in the vocabulary of the shipped kit (`pulse_core.connector`), and it is the
one the archived `connector-pattern` change ratified. Read it for the connector contract: the
five-stage anatomy, the command envelope (§4.2), idempotency derivation (§4.3), ordering (§4.4),
failure handling (§4.5), the adapter → shadow → retired lifecycle (§5.0), and the acceptance
criteria (§8.0).

Two things that used to live here have their own homes now:

- The PAP work breakdown, CX-1 through CX-8, and the D-PAP decision register:
  `design/migration/pap-connector-agent-batch.md`.
- How to build a connector against the kit, hands-on: `docs/connectors/authoring.md`.

This file stays as a pointer because the path is cited in earlier design docs and reports. Do not
re-add spec content here — a second copy is the defect that
`tests/scaffold/cat10_devex.py::test_connector_spec_has_one_canonical_copy` guards against.
