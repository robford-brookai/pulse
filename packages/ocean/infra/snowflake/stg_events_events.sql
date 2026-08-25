-- STG_EVENTS.EVENTS — the typed, deduplicated ledger envelope view.
--
-- Committed SQL, not dbt (design.md decision 3): this view IS the publisher contract other repos
-- read (docs/contracts/publishes.md), so it versions with this repo. Applied idempotently by
-- `task snowflake:stg-events` — CREATE OR REPLACE makes a re-run a no-op on an unchanged file.
--
-- Column list is derived from the emitting code, never from the superseded v1 envelope spec
-- (design/platform/event-envelope-spec.md): `pulse_ledger.relay._envelope` builds the envelope
-- dict the outbox relay publishes, and `ocean_broker.publisher.EventBridgePublisher.publish`
-- adds one more field — `key`, the routing key — before the entry reaches the bus. Both together
-- are what actually lands in `STREAMLINE.OCEAN_RAW.EVENTS.data`. `actor`, `evidence`, and
-- `payload` are nested JSON documents on the envelope, not scalar fields, so each keeps its
-- Snowflake VARIANT typing rather than being flattened into columns the emitter does not produce.
--
-- No filter on `_topic` (design.md decision 2 / open question 2): consumers filter on `_topic`
-- themselves.
CREATE OR REPLACE VIEW STREAMLINE.STG_EVENTS.EVENTS AS
SELECT
    data:event_id::VARCHAR             AS event_id,
    data:event_type::VARCHAR           AS event_type,
    data:subject_type::VARCHAR         AS subject_type,
    data:subject_key::VARCHAR          AS subject_key,
    data:seq::NUMBER                   AS seq,
    data:effective_at::TIMESTAMP_TZ    AS effective_at,
    data:occurred_at::TIMESTAMP_TZ     AS occurred_at,
    data:recorded_at::TIMESTAMP_TZ     AS recorded_at,
    data:producer::VARCHAR             AS producer,
    data:schema_version::NUMBER        AS schema_version,
    data:rule_version::VARCHAR         AS rule_version,
    data:correlation_id::VARCHAR       AS correlation_id,
    data:causation_id::VARCHAR         AS causation_id,
    data:reverses_event_id::VARCHAR    AS reverses_event_id,
    data:actor::VARIANT                AS actor,
    data:evidence::VARIANT             AS evidence,
    data:evidence_class::VARCHAR       AS evidence_class,
    data:epoch::VARCHAR                AS epoch,
    data:payload::VARIANT              AS payload,
    data:key::VARCHAR                  AS "key",
    _topic,
    _loaded_at
FROM STREAMLINE.OCEAN_RAW.EVENTS
QUALIFY ROW_NUMBER() OVER (PARTITION BY data:event_id ORDER BY _loaded_at ASC) = 1
;
