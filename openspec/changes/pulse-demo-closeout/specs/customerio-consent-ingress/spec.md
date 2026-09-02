## RENAMED Requirements

- FROM: `### Requirement: Every declaration attributes to actor `customer.io``
- TO: `### Requirement: Every declaration attributes to actor `customer-io``

## MODIFIED Requirements

### Requirement: Every declaration attributes to actor `customer-io`

Every command the ingress declares SHALL attribute to actor `customer-io` by virtue of the
per-service credential the ingress authenticates with — never by a payload field naming the
actor (ADR-0003: attribution is authentication). The writer id is spelled `customer-io` because
the command API derives writer ids from `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>` by lowercasing the
suffix and mapping `_` to `-`, so the credential is registered as
`PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO` (decision recorded 2026-09-02, `pulse-demo-closeout`
design.md decision 9). Every command's payload SHALL carry message-level provenance: a reference
to the source landing row (its message or event identifier) sufficient to trace a recorded
consent state back to the Customer.io message that produced it.

#### Scenario: A declared command is customer-io-attributed and traceable

- **GIVEN** a consent row read from the landing
- **WHEN** the ingress declares it
- **THEN** the command is submitted under the ingress's own `customer-io` service credential, and
  its payload references the source row's message/event identifier

#### Scenario: The writer id round-trips through the registry's suffix mapping

- **GIVEN** a credential registered as `PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO`
- **WHEN** the API resolves the writer id from that variable name
- **THEN** the resolved id equals the ingress's declared writer id, `customer-io`, exactly
