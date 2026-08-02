"""Integration test infrastructure — testcontainers for Redpanda and Postgres.

Provides session-scoped Redpanda and Postgres containers, SQLAlchemy session
factories, and helper utilities. Tests in this directory require Docker.

Skip gracefully if Docker is unavailable:
    pytest tests/integration/ -v

To run integration tests explicitly:
    python -m pytest tests/integration/ -v -m integration
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_ROOT = pathlib.Path(__file__).parents[2]

# Add graph-projection for models and handlers
_GRAPH_PROJ = str(_ROOT / "services" / "graph-projection")
if _GRAPH_PROJ not in sys.path:
    sys.path.insert(0, _GRAPH_PROJ)

_SLACK_BOT = str(_ROOT / "services" / "slack-bot")
if _SLACK_BOT not in sys.path:
    sys.path.insert(1, _SLACK_BOT)

_ZCC_CONN = str(_ROOT / "services" / "zcc-connector")
if _ZCC_CONN not in sys.path:
    sys.path.insert(2, _ZCC_CONN)

_MONGO_CONN = str(_ROOT / "services" / "mongodb-connector")
if _MONGO_CONN not in sys.path:
    sys.path.insert(3, _MONGO_CONN)

# ocean-broker lives in the M007 worktree until merged
_OCEAN_BROKER = str(_ROOT / ".gsd" / "worktrees" / "M007" / "libs" / "ocean-broker" / "src")
if _OCEAN_BROKER not in sys.path:
    sys.path.insert(4, _OCEAN_BROKER)


# ---------------------------------------------------------------------------
# Docker availability guard
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    import subprocess

    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


_SKIP_NO_DOCKER = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker not available — skipping integration tests",
)


# ---------------------------------------------------------------------------
# Postgres container + SQLAlchemy session factory
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():
    """Start a Postgres container for the test session."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed")

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session")
async def async_engine(postgres_container):
    """Create async SQLAlchemy engine pointed at the test Postgres container."""
    url = postgres_container.get_connection_url()
    # Replace sync driver with async driver
    async_url = url.replace("postgresql://", "postgresql+asyncpg://").replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )

    engine = create_async_engine(async_url, echo=False)

    # Create all tables (graph-projection models + ai_drafts table)
    async with engine.begin() as conn:
        # Import models after path is configured
        from src.models import Base

        await conn.run_sync(Base.metadata.create_all)

        # Create ai_drafts table (not in ORM models — used by slack-bot raw SQL)
        await conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS ai_drafts (
                    draft_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL DEFAULT '',
                    patient_id TEXT NOT NULL DEFAULT '',
                    alert_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    actor_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def session_factory(async_engine):
    """Return an async_sessionmaker bound to the test Postgres engine."""
    return async_sessionmaker(async_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Redpanda container + Kafka producer/consumer helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def redpanda_container():
    """Start a Redpanda container for the test session."""
    try:
        from testcontainers.redpanda import RedpandaContainer
    except ImportError:
        try:
            from testcontainers.kafka import KafkaContainer as RedpandaContainer
        except ImportError:
            pytest.skip("testcontainers[redpanda] or testcontainers[kafka] not installed")

    with RedpandaContainer() as rp:
        yield rp


@pytest.fixture(scope="session")
def bootstrap_servers(redpanda_container):
    """Return bootstrap server address for test Redpanda."""
    return redpanda_container.get_bootstrap_server()


def make_test_producer(bootstrap_servers: str):
    """Create a confluent_kafka Producer for the test broker."""
    from confluent_kafka import Producer

    return Producer({"bootstrap.servers": bootstrap_servers})


def consume_one(bootstrap_servers: str, topic: str, timeout: float = 10.0) -> dict | None:
    """Consume one message from a topic using a short-lived consumer group."""
    from confluent_kafka import Consumer

    consumer = Consumer({
        "bootstrap.servers": bootstrap_servers,
        "group.id": f"test-consumer-{topic}-{int(time.time())}",
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


# ---------------------------------------------------------------------------
# Event-store tables (events + audit_log) for STORE / AUDIT requirement tests
# ---------------------------------------------------------------------------

_EVENT_STORE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id UUID PRIMARY KEY,
        event_type TEXT NOT NULL,
        schema_version TEXT NOT NULL DEFAULT '1.0.0',
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        source_system TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        actor_id TEXT,
        timestamp TIMESTAMPTZ NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}',
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        audit_id UUID PRIMARY KEY,
        event_id UUID,
        action_type TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        source_system TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        timestamp TIMESTAMPTZ NOT NULL,
        detail JSONB NOT NULL DEFAULT '{}',
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE OR REPLACE FUNCTION audit_log_immutable()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'audit_log is append-only: UPDATE and DELETE are not permitted';
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log",
    """
    CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()
    """,
]


@pytest_asyncio.fixture(scope="session")
async def event_store_tables(async_engine):
    """Create events and audit_log tables with immutability trigger (from migration 0001)."""
    async with async_engine.begin() as conn:
        for stmt in _EVENT_STORE_STATEMENTS:
            await conn.execute(sa.text(stmt))
    yield async_engine


def produce_ocean_event(
    producer,
    topic: str,
    event_id: str | None = None,
) -> dict:
    """Build and produce a minimal valid Ocean event to the given topic.

    Returns the event dict that was produced.
    """
    eid = event_id or str(uuid.uuid4())
    event = {
        "event_id": eid,
        "event_type": "test.created",
        "schema_version": "1.0.0",
        "entity_type": "test",
        "entity_id": "test-001",
        "source_system": "test",
        "correlation_id": "",
        "actor_id": "test",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": {},
    }
    producer.produce(topic, json.dumps(event).encode())
    producer.flush()
    return event


async def poll_row_count(
    session_factory,
    table: str,
    expected: int,
    timeout: float = 10.0,
) -> int:
    """Poll SELECT COUNT(*) FROM table until count >= expected or timeout.

    Returns the final count.
    """
    deadline = time.time() + timeout
    count = 0
    while time.time() < deadline:
        async with session_factory() as session:
            result = await session.execute(sa.text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
        if count >= expected:
            return count
        await asyncio.sleep(0.2)
    return count


# ---------------------------------------------------------------------------
# MongoDB container (replica set enabled for Change Streams)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mongodb_container():
    """Start a MongoDB replica-set container for CDC integration tests.

    Change Streams require a replica set.  We start ``mongod --replSet rs0``,
    then exec ``rs.initiate()`` *inside* the container (so the member host
    matches the internal listener on port 27017), and wait for PRIMARY.
    """
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    container = (
        DockerContainer("mongo:7").with_exposed_ports(27017).with_command("mongod --replSet rs0 --bind_ip_all --noauth")
    )
    container.start()
    wait_for_logs(container, "Waiting for connections")

    try:
        # Initiate replica set from INSIDE the container so the member
        # address (localhost:27017) matches the internal listener.
        exit_code, output = container.exec(
            'mongosh --eval \'rs.initiate({_id:"rs0", members:[{_id:0, host:"localhost:27017"}]})\''
        )
        if exit_code != 0:
            raise RuntimeError(f"rs.initiate failed: {output}")

        # Poll until PRIMARY (up to 30s) — from outside via pymongo
        import pymongo

        host = container.get_container_host_ip()
        port = container.get_exposed_port(27017)
        conn_url = f"mongodb://{host}:{port}/?directConnection=true"
        client = pymongo.MongoClient(conn_url, directConnection=True, serverSelectionTimeoutMS=10000)

        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                status = client.admin.command("replSetGetStatus")
                if status["members"][0].get("stateStr") == "PRIMARY":
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("MongoDB replica set did not reach PRIMARY within 30s")

        client.close()
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def mongodb_uri(mongodb_container):
    """Return the MongoDB connection string with directConnection for tests."""
    host = mongodb_container.get_container_host_ip()
    port = mongodb_container.get_exposed_port(27017)
    return f"mongodb://{host}:{port}/?directConnection=true"
