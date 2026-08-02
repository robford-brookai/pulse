"""Unit tests for mongodb-connector's publish site after the EventBridge conversion (DNA-749).

The connector no longer owns transport code. ``CollectionWatcher`` emits through the shared
``EventBridgePublisher``, addressed by *domain* (``patient-state``) rather than by Kafka topic
(``ocean.patient-state``), and inherits the Postgres ``failed_webhooks`` fallback the service
never had under Kafka.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import pathlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import setup.
#
# motor/pymongo/bson are the connector's own runtime dependencies and are not
# installed in the workspace venv, so they are stubbed. ocean_broker IS a
# workspace library and is deliberately NOT stubbed: these tests exercise the
# real shared publisher.
#
# Sixteen ocean services each own a top-level package called ``src``, so a
# permanent ``sys.path`` insert makes whichever test imported first decide what
# ``src`` means for the whole session. This module borrows the name for the
# duration of one import and hands it back, so it passes whether it runs alone
# or alongside another service's tests.
# ---------------------------------------------------------------------------
_CONNECTOR_ROOT = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector"


class _StubPyMongoError(Exception):
    """Stand-in for ``pymongo.errors.PyMongoError`` — must be a real class to sit in an except."""


def _stub(name: str) -> MagicMock:
    """Return the stub registered under *name*, creating it if a sibling test has not already."""
    module = sys.modules.setdefault(name, MagicMock())
    return module


for _name in ("motor", "motor.motor_asyncio", "pymongo", "pymongo.errors", "bson", "bson.json_util"):
    _stub(_name)

# Two attributes need real behaviour rather than a MagicMock, and are set unconditionally: a
# sibling test may have registered a bare stub first, and these are what the watcher's own code
# calls. `PyMongoError` sits in an `except` clause, which rejects a non-class; `json_util.dumps`
# feeds `json.loads`.
_stub("pymongo.errors").PyMongoError = _StubPyMongoError
_stub("pymongo").errors = _stub("pymongo.errors")
_stub("bson.json_util").dumps = json.dumps
_stub("bson").json_util = _stub("bson.json_util")


def _import_from_connector(dotted_name: str) -> ModuleType:
    """Import ``dotted_name`` resolving ``src`` to mongodb-connector, then restore the name."""
    displaced = {key: sys.modules.pop(key) for key in list(sys.modules) if key == "src" or key.startswith("src.")}
    root = str(_CONNECTOR_ROOT)
    sys.path.insert(0, root)
    try:
        return importlib.import_module(dotted_name)
    finally:
        sys.path.remove(root)
        for key in list(sys.modules):
            if key == "src" or key.startswith("src."):
                del sys.modules[key]
        sys.modules.update(displaced)


from ocean_broker.publisher import EventBridgePublisher

CollectionWatcher = _import_from_connector("src.watcher").CollectionWatcher

_PATIENT_ID = "patient-0001"
_SRC_DIR = _CONNECTOR_ROOT / "src"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeChangeStream:
    """Async context manager yielding a fixed list of change documents, then stopping."""

    def __init__(self, changes: list[dict]) -> None:
        self._changes = changes

    async def __aenter__(self) -> _FakeChangeStream:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def __aiter__(self):
        async def _gen():
            for change in self._changes:
                yield change

        return _gen()


def _make_session_factory() -> MagicMock:
    """A session factory whose sessions record every ``execute`` call."""
    session = AsyncMock()
    session.execute = AsyncMock()

    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_ctx)

    class _SessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_):
            return False

    factory = MagicMock(side_effect=lambda: _SessionCtx())
    factory.session = session
    return factory


def _make_watcher(publisher, *, changes: list[dict] | None = None):
    if changes is None:
        changes = [{"_id": {"_data": "token-1"}, "operationType": "insert"}]

    collection = MagicMock()
    collection.watch = MagicMock(return_value=_FakeChangeStream(changes))

    transformer = MagicMock()
    transformer.transform = MagicMock(return_value={"patient_id": _PATIENT_ID, "feature": "risk_score"})

    token_store = AsyncMock()
    token_store.get_token = AsyncMock(return_value=None)
    token_store.save_token = AsyncMock()

    return CollectionWatcher(
        collection=collection,
        transformer=transformer,
        publisher=publisher,
        token_store=token_store,
        db_session_factory=_make_session_factory(),
        collection_name="alerts",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_emits_through_the_shared_publisher() -> None:
    """The site publishes via EventBridgePublisher, addressed by domain, keyed by patient_id."""
    publisher = AsyncMock(spec=EventBridgePublisher)
    watcher = _make_watcher(publisher)

    await watcher.watch(asyncio.Event())

    publisher.publish.assert_awaited_once()
    args, kwargs = publisher.publish.await_args
    detail_type = args[0]
    envelope = args[1]

    assert detail_type == "patient-state"
    assert kwargs["key"] == _PATIENT_ID
    # The envelope's event_type must not be promoted to detail-type.
    assert envelope["event_type"] == "patient.feature.changed"
    assert detail_type != envelope["event_type"]
    assert envelope["payload"] == {"patient_id": _PATIENT_ID, "feature": "risk_score"}


@pytest.mark.asyncio
async def test_publish_failure_writes_failed_webhooks() -> None:
    """A bus failure at this site dead-letters to Postgres instead of raising.

    The connector had no fallback under Kafka; it inherits one from the shared publisher.
    """
    dlq_factory = _make_session_factory()

    with patch("ocean_broker.publisher.boto3") as mock_boto3:
        client = MagicMock()
        client.put_events = MagicMock(side_effect=RuntimeError("bus unavailable"))
        mock_boto3.client.return_value = client
        publisher = EventBridgePublisher(region="us-east-1", db_session_maker=dlq_factory)

    watcher = _make_watcher(publisher)

    await watcher.watch(asyncio.Event())  # must not raise

    dlq_factory.session.execute.assert_awaited_once()
    sql, params = dlq_factory.session.execute.await_args.args
    assert "INSERT INTO failed_webhooks" in str(sql)
    assert params["key"] == _PATIENT_ID
    assert params["error"] == "bus unavailable"
    assert json.loads(params["payload"])["key"] == _PATIENT_ID


@pytest.mark.asyncio
async def test_resume_token_is_still_persisted_after_a_dead_lettered_publish() -> None:
    """At-least-once holds: the envelope is durable in failed_webhooks, so the token advances."""
    dlq_factory = _make_session_factory()

    with patch("ocean_broker.publisher.boto3") as mock_boto3:
        client = MagicMock()
        client.put_events = MagicMock(return_value={"FailedEntryCount": 1, "Entries": [{"ErrorMessage": "throttled"}]})
        mock_boto3.client.return_value = client
        publisher = EventBridgePublisher(region="us-east-1", db_session_maker=dlq_factory)

    watcher = _make_watcher(publisher)
    await watcher.watch(asyncio.Event())

    watcher._token_store.save_token.assert_awaited_once()


def test_no_transport_client_survives_in_the_connector() -> None:
    """No source file in this service references a bus client, and publisher.py is gone."""
    assert not (_SRC_DIR / "publisher.py").exists()

    offenders = {
        path.name: marker
        for path in sorted(_SRC_DIR.glob("*.py"))
        for marker in ("confluent_kafka", "build_producer_config", "Producer(")
        if marker in path.read_text()
    }
    assert offenders == {}
