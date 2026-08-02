"""End-to-end CDC pipeline integration tests.

Proves:
  1. MongoDB insert → ``patient.feature.changed`` event on ``ocean.patient-state``
  2. Resume token persists across watcher restart (no replay of old events)
  3. All 9 collections produce events via WatcherManager (multi-collection)

Requires Docker (MongoDB 7, Redpanda, Postgres via testcontainers).

Skipped since DNA-749: mongodb-connector publishes through the shared ``EventBridgePublisher``,
so the Redpanda consumers below have nothing to read and ``src.publisher`` no longer exists. The
body is kept as the shape the replacement must reproduce — it is rewritten against LocalStack in
task 6.5 and folded into the equivalence harness in 8.1, not repaired here.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="Kafka path retired for mongodb-connector by DNA-749; LocalStack equivalent lands in 6.5"),
]

# ---------------------------------------------------------------------------
# DDL for cdc_resume_tokens (run directly — no Alembic in test context)
# ---------------------------------------------------------------------------

_RESUME_TOKEN_DDL = """
CREATE TABLE IF NOT EXISTS cdc_resume_tokens (
    collection_name TEXT PRIMARY KEY,
    resume_token JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _consume_one(bootstrap_servers: str, topic: str, group_suffix: str = "", timeout: float = 15.0) -> dict | None:
    """Consume one message from *topic* with a unique consumer group."""
    from confluent_kafka import Consumer

    consumer = Consumer({
        "bootstrap.servers": bootstrap_servers,
        "group.id": f"cdc-test-{topic}-{int(time.time())}-{group_suffix}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([topic])

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                continue
            return json.loads(msg.value())
    finally:
        consumer.close()
    return None


def _consume_all(bootstrap_servers: str, topic: str, group_suffix: str = "", timeout: float = 15.0) -> list[dict]:
    """Consume ALL available messages from *topic* using a single consumer group."""
    from confluent_kafka import Consumer

    consumer = Consumer({
        "bootstrap.servers": bootstrap_servers,
        "group.id": f"cdc-test-all-{topic}-{int(time.time())}-{group_suffix}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([topic])

    events: list[dict] = []
    deadline = time.time() + timeout
    idle_deadline = None
    try:
        while time.time() < deadline:
            msg = consumer.poll(timeout=1.0)
            if msg is None or msg.error():
                if events and idle_deadline is None:
                    # Got at least one event; wait 3 more seconds for stragglers
                    idle_deadline = time.time() + 3.0
                if idle_deadline and time.time() > idle_deadline:
                    break
                continue
            events.append(json.loads(msg.value()))
            idle_deadline = None  # reset idle timer on new message
    finally:
        consumer.close()
    return events


async def _make_watcher(
    mongodb_uri: str,
    bootstrap_servers: str,
    db_url: str,
    engine=None,
    topic: str = "ocean.patient-state",
):
    """Create all CDC components and return (watcher, shutdown_event, engine, session_factory).

    If *engine* is provided it is reused; otherwise a new one is created.

    Temporarily swaps ``sys.modules["src"]`` to point at the mongodb-connector
    ``src`` package, avoiding namespace collisions with graph-projection's ``src``.
    """
    import os
    import pathlib
    import sys

    import motor.motor_asyncio

    _SVC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector"

    # Ensure ocean-broker picks up the Redpanda address
    os.environ["REDPANDA_BROKERS"] = bootstrap_servers

    # Save and evict any existing 'src' and 'src.*' modules
    saved = {}
    for key in list(sys.modules):
        if key == "src" or key.startswith("src."):
            saved[key] = sys.modules.pop(key)

    # Temporarily put mongodb-connector at front of sys.path
    svc_str = str(_SVC_ROOT)
    sys.path.insert(0, svc_str)
    try:
        from src.publisher import EventPublisher
        from src.resume_token import ResumeTokenStore
        from src.transformer import AlertsTransformer
        from src.watcher import CollectionWatcher
    finally:
        sys.path.remove(svc_str)
        # Evict mongodb-connector src modules so they don't shadow others
        for key in list(sys.modules):
            if key == "src" or key.startswith("src."):
                sys.modules.pop(key, None)
        # Restore original src modules
        sys.modules.update(saved)

    mongo_client = motor.motor_asyncio.AsyncIOMotorClient(mongodb_uri)
    collection = mongo_client["testdb"]["alerts"]

    if engine is None:
        engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    publisher = EventPublisher()
    token_store = ResumeTokenStore()
    transformer = AlertsTransformer()
    shutdown_event = asyncio.Event()

    watcher = CollectionWatcher(
        collection=collection,
        transformer=transformer,
        publisher=publisher,
        token_store=token_store,
        db_session_factory=session_factory,
        collection_name="alerts",
        topic=topic,
    )

    return watcher, shutdown_event, engine, session_factory, mongo_client


async def _make_manager(
    mongodb_uri: str,
    bootstrap_servers: str,
    db_url: str,
    engine=None,
    topic: str = "ocean.patient-state-multi",
):
    """Create a WatcherManager for all 9 collections.

    Uses the same ``sys.modules["src"]`` save/swap/restore pattern as
    ``_make_watcher``.  Returns (manager, shutdown_event, engine, mongo_client).
    """
    import os
    import pathlib
    import sys

    import motor.motor_asyncio

    _SVC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector"

    os.environ["REDPANDA_BROKERS"] = bootstrap_servers

    # Save and evict any existing 'src' and 'src.*' modules
    saved = {}
    for key in list(sys.modules):
        if key == "src" or key.startswith("src."):
            saved[key] = sys.modules.pop(key)

    svc_str = str(_SVC_ROOT)
    sys.path.insert(0, svc_str)
    try:
        from src.publisher import EventPublisher
        from src.resume_token import ResumeTokenStore
        from src.transformer import TRANSFORMER_REGISTRY
        from src.watcher_manager import WatcherManager
    finally:
        sys.path.remove(svc_str)
        for key in list(sys.modules):
            if key == "src" or key.startswith("src."):
                sys.modules.pop(key, None)
        sys.modules.update(saved)

    mongo_client = motor.motor_asyncio.AsyncIOMotorClient(mongodb_uri)
    db = mongo_client["testdb"]

    if engine is None:
        engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    publisher = EventPublisher()
    token_store = ResumeTokenStore()
    shutdown_event = asyncio.Event()

    manager = WatcherManager(
        db=db,
        publisher=publisher,
        token_store=token_store,
        db_session_factory=session_factory,
        transformer_registry=TRANSFORMER_REGISTRY,
        topic=topic,
    )

    return manager, shutdown_event, engine, mongo_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCDCPipeline:
    """Prove the full CDC pipeline: MongoDB → Watcher → Kafka topic."""

    async def test_mongodb_insert_produces_event(
        self,
        mongodb_container,
        mongodb_uri,
        redpanda_container,
        bootstrap_servers,
        postgres_container,
    ):
        """Insert into alerts → event with correct envelope on ocean.patient-state."""
        # Build async Postgres URL
        pg_url = postgres_container.get_connection_url()
        async_pg_url = pg_url.replace("postgresql://", "postgresql+asyncpg://").replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )

        # Create resume-token table
        engine = create_async_engine(async_pg_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(sa.text(_RESUME_TOKEN_DDL))

        # Create watcher components
        watcher, shutdown_event, engine, session_factory, mongo_client = await _make_watcher(
            mongodb_uri,
            bootstrap_servers,
            async_pg_url,
            engine=engine,
        )

        # Start watcher as background task
        watcher_task = asyncio.create_task(watcher.watch(shutdown_event))

        try:
            # Small delay to let watcher establish Change Stream
            await asyncio.sleep(2)

            # Insert a test document
            collection = mongo_client["testdb"]["alerts"]
            await collection.insert_one({
                "patientId": "patient-001",
                "status": "CRITICAL",
                "type": "glucose_high",
                "vitalType": "glucose",
                "createdAt": datetime.now(timezone.utc),
            })

            # Consume from topic in a thread (confluent-kafka consumer is sync)
            loop = asyncio.get_running_loop()
            event = await loop.run_in_executor(
                None,
                _consume_one,
                bootstrap_servers,
                "ocean.patient-state",
                "t1",
            )

            # -- Assertions --
            assert event is not None, "No event consumed from ocean.patient-state within timeout"
            assert event["event_type"] == "patient.feature.changed"
            assert event["source_system"] == "mongodb-connector"
            assert event["entity_id"] == "patient-001"
            assert event["schema_version"] == "1.0.0"

            payload = event["payload"]
            assert payload["collection"] == "alerts"
            assert payload["patient_id"] == "patient-001"
            assert payload["features"]["alert_status"] == "CRITICAL"
            assert payload["features"]["alert_type"] == "glucose_high"
            assert payload["features"]["vital_type"] == "glucose"

            # PHI guard: no PHI field names in payload keys (recursive)
            from ocean_events.base import _PHI_FIELD_NAMES

            all_keys = set(payload.keys()) | set(payload.get("features", {}).keys())
            phi_overlap = all_keys & _PHI_FIELD_NAMES
            assert phi_overlap == set(), f"PHI fields leaked into payload: {phi_overlap}"

            # Verify resume token row exists in Postgres
            async with session_factory() as session:
                result = await session.execute(
                    sa.text("SELECT resume_token FROM cdc_resume_tokens WHERE collection_name = :c"),
                    {"c": "alerts"},
                )
                row = result.fetchone()
                assert row is not None, "No resume token row found for 'alerts'"
                assert row[0] is not None, "Resume token value is null"

        finally:
            shutdown_event.set()
            watcher_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                pass
            mongo_client.close()
            await engine.dispose()

    async def test_resume_token_persists_across_restart(
        self,
        mongodb_container,
        mongodb_uri,
        redpanda_container,
        bootstrap_servers,
        postgres_container,
    ):
        """Watcher resumes from saved token after restart — no replay of old events."""
        pg_url = postgres_container.get_connection_url()
        async_pg_url = pg_url.replace("postgresql://", "postgresql+asyncpg://").replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )

        # Create resume-token table
        engine = create_async_engine(async_pg_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(sa.text(_RESUME_TOKEN_DDL))

        # Use a dedicated topic to isolate from other tests' events
        _RESUME_TOPIC = "ocean.patient-state-resume"

        # ---- Phase 1: Start watcher, insert doc A, consume event A, stop ----
        watcher1, shutdown1, engine, sf1, mongo1 = await _make_watcher(
            mongodb_uri,
            bootstrap_servers,
            async_pg_url,
            engine=engine,
            topic=_RESUME_TOPIC,
        )
        task1 = asyncio.create_task(watcher1.watch(shutdown1))
        await asyncio.sleep(2)

        collection = mongo1["testdb"]["alerts"]
        await collection.insert_one({
            "patientId": "patient-A",
            "status": "URGENT",
            "type": "spo2_low",
            "vitalType": "spo2",
            "createdAt": datetime.now(timezone.utc),
        })

        loop = asyncio.get_running_loop()
        event_a = await loop.run_in_executor(
            None,
            _consume_one,
            bootstrap_servers,
            _RESUME_TOPIC,
            "resume-a",
        )
        assert event_a is not None, "Event A not consumed"
        assert event_a["entity_id"] == "patient-A"

        # Stop watcher 1 — set shutdown event and wait for clean exit
        shutdown1.set()
        try:
            await asyncio.wait_for(task1, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            task1.cancel()
            try:
                await task1
            except asyncio.CancelledError:
                pass
        mongo1.close()

        # ---- Phase 2: Insert doc B while watcher is stopped ----
        import motor.motor_asyncio

        mongo2 = motor.motor_asyncio.AsyncIOMotorClient(mongodb_uri)
        collection2 = mongo2["testdb"]["alerts"]
        await collection2.insert_one({
            "patientId": "patient-B",
            "status": "WARNING",
            "type": "hr_elevated",
            "vitalType": "heart_rate",
            "createdAt": datetime.now(timezone.utc),
        })
        mongo2.close()

        # ---- Phase 3: Restart watcher, consume event B only ----
        watcher2, shutdown2, engine, sf2, mongo3 = await _make_watcher(
            mongodb_uri,
            bootstrap_servers,
            async_pg_url,
            engine=engine,
            topic=_RESUME_TOPIC,
        )
        task2 = asyncio.create_task(watcher2.watch(shutdown2))

        try:
            await asyncio.sleep(2)

            # Consume ALL messages from the resume topic with a single consumer.
            # Phase 1 produced event A; Phase 3 (restarted watcher) should produce
            # ONLY event B (resumed from saved token, not from beginning).
            events = await loop.run_in_executor(
                None,
                _consume_all,
                bootstrap_servers,
                _RESUME_TOPIC,
                "resume-all",
            )

            entity_ids = [e["entity_id"] for e in events]

            # Find the patient-B event
            b_events = [e for e in events if e["entity_id"] == "patient-B"]
            assert len(b_events) >= 1, f"Expected event for patient-B, got entities: {entity_ids}"

            # Count patient-A events — there should be exactly 1 (from Phase 1),
            # not 2 (which would mean the restarted watcher replayed it).
            a_events = [e for e in events if e["entity_id"] == "patient-A"]
            assert len(a_events) == 1, (
                f"Watcher replayed old events — found {len(a_events)} patient-A events "
                f"(expected exactly 1 from Phase 1), entities: {entity_ids}"
            )

        finally:
            shutdown2.set()
            task2.cancel()
            try:
                await task2
            except asyncio.CancelledError:
                pass
            mongo3.close()
            await engine.dispose()

    async def test_multi_collection_produces_events(
        self,
        mongodb_container,
        mongodb_uri,
        redpanda_container,
        bootstrap_servers,
        postgres_container,
    ):
        """Insert one doc per collection via WatcherManager → 9 events, all PHI-free."""
        _MULTI_TOPIC = "ocean.patient-state-multi"

        pg_url = postgres_container.get_connection_url()
        async_pg_url = pg_url.replace("postgresql://", "postgresql+asyncpg://").replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )

        # Create resume-token table
        engine = create_async_engine(async_pg_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(sa.text(_RESUME_TOKEN_DDL))

        # Build manager for all 9 collections
        manager, shutdown_event, engine, mongo_client = await _make_manager(
            mongodb_uri,
            bootstrap_servers,
            async_pg_url,
            engine=engine,
            topic=_MULTI_TOPIC,
        )

        await manager.start(shutdown_event)

        try:
            # Let all 9 change streams establish
            await asyncio.sleep(3)

            db = mongo_client["testdb"]

            # Representative documents — one per collection with correct patient_id field
            docs = {
                "alerts": {"patientId": "p-alerts", "status": "ACTIVE", "type": "glucose", "vitalType": "glucose"},
                "chatRooms": {"type": "expert", "subscribers": [{"personaID": "p-chatrooms"}], "unreadMessageCount": 3},
                "activity": {"persona_id": "p-activity", "lastReadingAt": "2026-01-01T00:00:00Z"},
                "provider_protocols": {"persona_id": "p-protocols", "adherenceRate": 0.95},
                "patient_care_plans": {"persona_id": "p-careplans", "problem_list": [{"updated_at": "2026-01-01"}]},
                "patient_note": {
                    "persona_id": "p-notes",
                    "pendingEmrNotes": 2,
                    "is_interaction": True,
                    "provider": "dr-x",
                    "interaction": True,
                },
                "monitoring_time_raw": {"persona_id": "p-monitoring", "lastPocarOpenedAt": "2026-01-01T00:00:00Z"},
                "persona": {"personaID": "p-persona", "providerDetails": {"program": "RPM"}},
                "persona.dashboard_details": {"persona_id": "p-dashboard", "billableMinutesMtd": 25},
            }

            for coll_name, doc in docs.items():
                await db[coll_name].insert_one(doc)

            # Consume all events with a generous timeout for 9 change streams
            loop = asyncio.get_running_loop()
            events = await loop.run_in_executor(
                None,
                _consume_all,
                bootstrap_servers,
                _MULTI_TOPIC,
                "multi",
                25.0,
            )

            # ---- Assertions ----
            assert len(events) >= 9, (
                f"Expected at least 9 events, got {len(events)}. "
                f"Collections seen: {sorted({e['payload']['collection'] for e in events})}"
            )

            # Every expected collection name appears
            collections_seen = {e["payload"]["collection"] for e in events}
            expected_collections = set(docs.keys())
            missing = expected_collections - collections_seen
            assert not missing, f"Missing collection(s) in events: {sorted(missing)}. Seen: {sorted(collections_seen)}"

            # Envelope checks on every event
            for evt in events:
                assert evt["event_type"] == "patient.feature.changed", f"Wrong event_type: {evt['event_type']}"
                assert evt["source_system"] == "mongodb-connector", f"Wrong source_system: {evt['source_system']}"

            # PHI guard: no PHI field names in any event's features
            from ocean_events.base import _PHI_FIELD_NAMES

            for evt in events:
                payload = evt["payload"]
                feature_keys = set(payload.get("features", {}).keys())
                phi_overlap = feature_keys & _PHI_FIELD_NAMES
                assert phi_overlap == set(), f"PHI fields leaked in {payload['collection']} event: {phi_overlap}"

        finally:
            shutdown_event.set()
            await manager.stop()
            mongo_client.close()
            await engine.dispose()
