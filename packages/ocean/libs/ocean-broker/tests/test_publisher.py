"""Unit tests for EventBridgePublisher."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ocean_broker.catalog import LIVE_DOMAINS, address_for, pattern_matches, rule_pattern
from ocean_broker.publisher import MAX_ENTRY_BYTES, EventBridgePublisher, PublishFailed


class TestEventBridgePublisher:
    """Tests for EventBridge event publisher with Postgres fallback."""

    @pytest.fixture
    def mock_eventbridge_client(self):
        """Mock boto3 EventBridge client."""
        client = MagicMock()
        client.put_events = MagicMock(return_value={"FailedEntryCount": 0})
        return client

    @pytest.fixture
    def mock_db_session_maker(self):
        """Mock SQLAlchemy async session maker."""

        # Create a mock session with execute
        session = AsyncMock()
        session.execute = AsyncMock()

        # Create mock for session.begin() async context manager
        begin_context = AsyncMock()
        begin_context.__aenter__ = AsyncMock(return_value=None)
        begin_context.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=begin_context)

        # Create an async context manager class
        class SessionContextManager:
            def __init__(self, session_obj):
                self.session = session_obj

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, *_):
                pass

        # Store the session on the maker for test assertions
        ctx_mgr = SessionContextManager(session)

        # Create the maker as a callable that returns the context manager
        def maker_call():
            return ctx_mgr

        maker = MagicMock(side_effect=maker_call)
        maker._test_session = session
        return maker

    @pytest.fixture
    def publisher(self, mock_eventbridge_client):
        """Create an EventBridgePublisher with mocked client."""
        with patch("ocean_broker.publisher.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_eventbridge_client
            publisher = EventBridgePublisher(region="us-east-1")
            publisher._client = mock_eventbridge_client
            return publisher

    @pytest.mark.asyncio
    async def test_envelope_roundtrips_fieldforfield(self, publisher, mock_eventbridge_client):
        """Envelope should round-trip with all fields intact.

        When an event is published, the entire envelope should be carried
        in EventBridge's 'detail' field without modification.
        """
        entity_id = str(uuid.uuid4())
        key = "test-key"

        # -- Construct test payload (the envelope) --
        envelope = {
            "event_type": "patient.feature.changed",
            "source_system": "mongodb-connector",
            "entity_type": "patient_feature",
            "entity_id": entity_id,
            "collection": "alerts",
            "payload": {
                "glucose_mg_dl": 250,
                "spo2_pct": 88,
                "transformed_at": "2026-03-18T21:00:00Z",
            },
        }

        # -- Publish --
        await publisher.publish(detail_type="patient-state", event=envelope, key=key)

        # -- Verify EventBridge was called correctly --
        mock_eventbridge_client.put_events.assert_called_once()
        call_args = mock_eventbridge_client.put_events.call_args

        # The envelope should be in the Entries
        entries = call_args.kwargs["Entries"] if "Entries" in call_args.kwargs else call_args[1]["Entries"]
        assert len(entries) == 1
        entry = entries[0]

        # -- Verify envelope round-trip: it's in detail untouched --
        assert entry["Source"] == "ocean"
        assert entry["DetailType"] == "patient-state"
        detail = json.loads(entry["Detail"])
        # The key should be added to the envelope
        expected_envelope = dict(envelope)
        expected_envelope["key"] = key
        assert detail == expected_envelope

    @pytest.mark.asyncio
    async def test_event_type_not_promoted_to_detailtype(self, publisher, mock_eventbridge_client):
        """event_type should not be promoted to detail-type.

        The detail-type comes from the domain mapping, not from event_type.
        event_type stays inside the envelope.
        """
        envelope = {
            "event_type": "patient.feature.changed",
            "source_system": "test-source",
        }

        await publisher.publish(detail_type="patient-state", event=envelope, key="key1")

        # -- Verify detail-type is the domain, not the event_type --
        mock_eventbridge_client.put_events.assert_called_once()
        call_args = mock_eventbridge_client.put_events.call_args
        entries = call_args.kwargs["Entries"] if "Entries" in call_args.kwargs else call_args[1]["Entries"]
        entry = entries[0]

        assert entry["DetailType"] == "patient-state"
        detail = json.loads(entry["Detail"])
        assert detail["event_type"] == "patient.feature.changed"

    @pytest.mark.asyncio
    async def test_key_carried_as_envelope_field(self, publisher, mock_eventbridge_client):
        """Key should be carried as an envelope field.

        The key is used for grouping by sequence guards, not for routing.
        """
        key = "entity-123"
        envelope = {
            "event_type": "test.event",
            "source_system": "test-source",
        }

        await publisher.publish(detail_type="signals", event=envelope, key=key)

        # -- Verify key is in the envelope detail --
        mock_eventbridge_client.put_events.assert_called_once()
        call_args = mock_eventbridge_client.put_events.call_args
        entries = call_args.kwargs["Entries"] if "Entries" in call_args.kwargs else call_args[1]["Entries"]
        entry = entries[0]

        detail = json.loads(entry["Detail"])
        assert detail["key"] == key

    @pytest.mark.asyncio
    async def test_bus_failure_writes_failed_webhooks(self, publisher, mock_eventbridge_client, mock_db_session_maker):
        """On EventBridge failure, write to failed_webhooks table and do not raise.

        A publish failure should not raise an exception; instead it should
        write to the Postgres DLQ and log the error.
        """
        # -- Set up the publisher with DB session maker --
        publisher._db_session_maker = mock_db_session_maker

        # -- Mock EventBridge to return a failure --
        error_message = "EventBridge service error"
        mock_eventbridge_client.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "500", "ErrorMessage": error_message}],
        }

        envelope = {
            "event_type": "test.event",
            "source_system": "test-source",
        }
        key = "test-key"

        # -- Publish should not raise --
        await publisher.publish(detail_type="signals", event=envelope, key=key)

        # -- Verify DLQ write was called --
        mock_db_session_maker.assert_called_once()
        # Get the session that was used
        session = mock_db_session_maker._test_session
        session.execute.assert_called_once()

        # -- Verify the DLQ insert statement --
        call_args = session.execute.call_args
        insert_sql = call_args[0][0]
        params = call_args[0][1]

        assert "INSERT INTO failed_webhooks" in str(insert_sql)
        assert params["key"] == key
        assert params["error"] == error_message

    @pytest.mark.asyncio
    async def test_bus_failure_does_not_raise(self, publisher, mock_eventbridge_client, mock_db_session_maker):
        """Bus failure should not raise an exception."""
        publisher._db_session_maker = mock_db_session_maker
        mock_eventbridge_client.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "500", "ErrorMessage": "Service error"}],
        }

        envelope = {"event_type": "test.event"}

        # This should not raise
        await publisher.publish(detail_type="signals", event=envelope, key="key")

    @pytest.mark.asyncio
    async def test_dlq_write_failing_does_not_raise_either(
        self, publisher, mock_eventbridge_client, mock_db_session_maker
    ):
        """A DLQ that is itself down must not turn a publish failure into a caller exception.

        The event is lost at this point, and nothing can prevent that — but a connector must not
        also lose the webhook it was in the middle of acknowledging.
        """
        publisher._db_session_maker = mock_db_session_maker
        mock_db_session_maker._test_session.execute.side_effect = RuntimeError("postgres is down")
        mock_eventbridge_client.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "500", "ErrorMessage": "Service error"}],
        }

        await publisher.publish(detail_type="signals", event={"event_type": "test.event"}, key="k")

    @pytest.mark.asyncio
    async def test_success_does_not_touch_the_dlq(self, publisher, mock_eventbridge_client, mock_db_session_maker):
        """A successful publish must not write to failed_webhooks."""
        publisher._db_session_maker = mock_db_session_maker

        await publisher.publish(detail_type="signals", event={"event_type": "test.event"})

        mock_eventbridge_client.put_events.assert_called_once()
        mock_db_session_maker.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_key_leaves_envelope_untouched(self, publisher, mock_eventbridge_client):
        """Without a key, no `key` field is invented on the envelope."""
        envelope = {"event_type": "test.event", "source_system": "test-source"}

        await publisher.publish(detail_type="signals", event=envelope)

        entry = mock_eventbridge_client.put_events.call_args.kwargs["Entries"][0]
        assert json.loads(entry["Detail"]) == envelope

    @pytest.mark.asyncio
    async def test_retired_domain_is_rejected(self, publisher, mock_eventbridge_client):
        """A retired domain never reaches the bus — the catalog has no address for it."""
        with pytest.raises(KeyError, match="warehouse-dlq"):
            await publisher.publish(detail_type="warehouse-dlq", event={"event_type": "x"})

        mock_eventbridge_client.put_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_client_exception_writes_dlq(self, publisher, mock_eventbridge_client, mock_db_session_maker):
        """A raising boto3 client is handled on the same path as a rejected entry."""
        publisher._db_session_maker = mock_db_session_maker
        mock_eventbridge_client.put_events.side_effect = RuntimeError("connection reset")

        await publisher.publish(detail_type="signals", event={"event_type": "x"}, key="k")

        params = mock_db_session_maker._test_session.execute.call_args[0][1]
        assert params["error"] == "connection reset"
        assert json.loads(params["payload"].decode())["key"] == "k"

    @pytest.mark.asyncio
    async def test_every_live_domain_addresses_from_the_catalog(self, publisher, mock_eventbridge_client):
        """Each live domain publishes at the address the catalog gives it.

        The list is not restated here: a domain added to the catalog is covered by this test
        without an edit, which is the point of there being one table.
        """
        for domain in LIVE_DOMAINS:
            mock_eventbridge_client.reset_mock()
            await publisher.publish(detail_type=domain, event={"event_type": "test.event"})

            entry = mock_eventbridge_client.put_events.call_args.kwargs["Entries"][0]
            expected = address_for(domain)
            assert entry["Source"] == expected.source
            assert entry["DetailType"] == expected.detail_type

    @pytest.mark.asyncio
    async def test_what_is_published_is_what_the_rules_match(self, publisher, mock_eventbridge_client):
        """Every address this publisher emits is caught by the generated rule pattern.

        This is the publisher half of the surface equivalence: the two derived surfaces cannot
        drift, because both resolve the same table.
        """
        pattern = rule_pattern(LIVE_DOMAINS)

        for domain in LIVE_DOMAINS:
            mock_eventbridge_client.reset_mock()
            await publisher.publish(detail_type=domain, event={"event_type": "test.event"})

            entry = mock_eventbridge_client.put_events.call_args.kwargs["Entries"][0]
            assert pattern_matches(pattern, entry["Source"], entry["DetailType"])

    @pytest.mark.asyncio
    async def test_no_database_session_maker_no_dlq_write(self, publisher, mock_eventbridge_client):
        """Without a DB session maker, a failed publish still does not raise."""
        publisher._db_session_maker = None

        mock_eventbridge_client.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "500", "ErrorMessage": "Service error"}],
        }

        await publisher.publish(detail_type="signals", event={"event_type": "test.event"}, key="k")


class TestEventBusTargeting:
    """The bus must be named explicitly on every entry.

    Omitting ``EventBusName`` sends the event to the account's ``default`` bus. PutEvents accepts
    it, ``FailedEntryCount`` stays 0, and the event is simply gone — the per-consumer rules from
    task 6.2 live on the ``ocean`` bus and never see it. It would have surfaced at the LocalStack
    equivalence gate as "no consumer receives anything", which is an expensive place to learn it.
    """

    @pytest.fixture
    def client(self):
        c = MagicMock()
        c.put_events = MagicMock(return_value={"FailedEntryCount": 0})
        return c

    def _publisher(self, client, **kwargs):
        with patch("ocean_broker.publisher.boto3") as mock_boto3:
            mock_boto3.client.return_value = client
            pub = EventBridgePublisher(region="us-east-1", **kwargs)
            pub._client = client
            return pub

    @pytest.mark.asyncio
    async def test_entry_names_the_bus(self, client):
        pub = self._publisher(client, event_bus_name="ocean-prod")
        await pub.publish("alerts", {"event_id": "e1"})
        entry = client.put_events.call_args.kwargs["Entries"][0]
        assert entry["EventBusName"] == "ocean-prod"

    @pytest.mark.asyncio
    async def test_bus_defaults_to_ocean_not_aws_default(self, client, monkeypatch):
        monkeypatch.delenv("OCEAN_EVENT_BUS_NAME", raising=False)
        pub = self._publisher(client)
        await pub.publish("alerts", {"event_id": "e1"})
        entry = client.put_events.call_args.kwargs["Entries"][0]
        assert entry["EventBusName"] == "ocean"
        assert entry["EventBusName"] != "default"

    @pytest.mark.asyncio
    async def test_bus_is_configurable_by_environment(self, client, monkeypatch):
        monkeypatch.setenv("OCEAN_EVENT_BUS_NAME", "ocean-staging")
        pub = self._publisher(client)
        await pub.publish("alerts", {"event_id": "e1"})
        assert client.put_events.call_args.kwargs["Entries"][0]["EventBusName"] == "ocean-staging"

    @pytest.mark.asyncio
    async def test_every_entry_carries_a_bus(self, client):
        """Not just the first — a regression here would be silent for whichever call missed it."""
        pub = self._publisher(client)
        for domain in ("alerts", "tasks", "signals"):
            await pub.publish(domain, {"event_id": "e1"})
        for call in client.put_events.call_args_list:
            assert "EventBusName" in call.kwargs["Entries"][0]


class TestEntrySizeLimit:
    """PutEvents caps one entry at 256 KB, counted across the whole entry, not just detail."""

    @pytest.fixture
    def mock_db_session_maker(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        begin = AsyncMock()
        begin.__aenter__ = AsyncMock(return_value=None)
        begin.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=begin)

        class Ctx:
            async def __aenter__(self_inner):
                return session

            async def __aexit__(self_inner, *_):
                pass

        maker = MagicMock(side_effect=lambda: Ctx())
        maker._test_session = session
        return maker

    @pytest.fixture
    def client(self):
        c = MagicMock()
        c.put_events = MagicMock(return_value={"FailedEntryCount": 0})
        return c

    def _publisher(self, client, maker=None):
        with patch("ocean_broker.publisher.boto3") as mock_boto3:
            mock_boto3.client.return_value = client
            pub = EventBridgePublisher(region="us-east-1", db_session_maker=maker)
            pub._client = client
            return pub

    @pytest.mark.asyncio
    async def test_oversized_entry_is_not_sent(self, client):
        pub = self._publisher(client)
        await pub.publish("alerts", {"event_id": "e1", "blob": "x" * (MAX_ENTRY_BYTES + 1)})
        assert client.put_events.call_count == 0, "an entry known to exceed the limit should never be sent"

    @pytest.mark.asyncio
    async def test_oversized_entry_dead_letters_with_a_legible_reason(self, client, mock_db_session_maker):
        pub = self._publisher(client, maker=mock_db_session_maker)
        await pub.publish("alerts", {"event_id": "e1", "blob": "x" * (MAX_ENTRY_BYTES + 1)})
        params = mock_db_session_maker._test_session.execute.call_args.args[1]
        assert "over the" in params["error"]
        assert str(MAX_ENTRY_BYTES) in params["error"]

    @pytest.mark.asyncio
    async def test_an_entry_under_the_limit_is_sent(self, client):
        pub = self._publisher(client)
        await pub.publish("alerts", {"event_id": "e1", "blob": "x" * 1000})
        assert client.put_events.call_count == 1


class TestFailureMode:
    """`on_failure` decides who owns a refused entry: this publisher's DLQ, or the caller's.

    Every converted OCEAN publish site is fire-and-forget and takes the default, `"dlq"`. The
    PULSE ledger relay takes `"raise"`: the transactional outbox is already that event's durable
    queue, and a second copy in `failed_webhooks` would split one event's record across two stores
    and hide the failure from the retry and dead-letter policy that owns it.
    """

    @pytest.fixture
    def refusing_client(self):
        c = MagicMock()
        c.put_events = MagicMock(return_value={"FailedEntryCount": 1, "Entries": [{"ErrorMessage": "Throttled"}]})
        return c

    @pytest.fixture
    def accepting_client(self):
        c = MagicMock()
        c.put_events = MagicMock(return_value={"FailedEntryCount": 0})
        return c

    def _publisher(self, client, **kwargs):
        with patch("ocean_broker.publisher.boto3") as mock_boto3:
            mock_boto3.client.return_value = client
            pub = EventBridgePublisher(region="us-east-1", **kwargs)
            pub._client = client
            return pub

    @pytest.mark.asyncio
    async def test_the_default_still_swallows(self, refusing_client):
        """Unchanged for the thirteen sites that never pass the argument."""
        pub = self._publisher(refusing_client)
        await pub.publish("alerts", {"event_id": "e1"})

    @pytest.mark.asyncio
    async def test_raise_mode_surfaces_the_rejection(self, refusing_client):
        pub = self._publisher(refusing_client, on_failure="raise")
        with pytest.raises(PublishFailed) as caught:
            await pub.publish("alerts", {"event_id": "e1"})
        assert caught.value.detail_type == "alerts"
        assert caught.value.reason == "Throttled"

    @pytest.mark.asyncio
    async def test_raise_mode_surfaces_a_transport_exception(self, refusing_client):
        refusing_client.put_events = MagicMock(side_effect=ConnectionError("no route to host"))
        pub = self._publisher(refusing_client, on_failure="raise")
        with pytest.raises(PublishFailed, match="no route to host"):
            await pub.publish("alerts", {"event_id": "e1"})

    @pytest.mark.asyncio
    async def test_raise_mode_surfaces_an_oversized_entry(self, accepting_client):
        """The size check dead-letters too, and a caller owning its own queue must hear about it."""
        pub = self._publisher(accepting_client, on_failure="raise")
        with pytest.raises(PublishFailed, match="over the"):
            await pub.publish("alerts", {"event_id": "e1", "blob": "x" * (MAX_ENTRY_BYTES + 1)})
        assert accepting_client.put_events.call_count == 0

    @pytest.mark.asyncio
    async def test_raise_mode_writes_no_second_dlq_copy(self, refusing_client, mock_db_session_maker):
        """Even with a session maker configured — the raise is the handoff, not a second record."""
        pub = self._publisher(refusing_client, db_session_maker=mock_db_session_maker, on_failure="raise")
        with pytest.raises(PublishFailed):
            await pub.publish("alerts", {"event_id": "e1"})
        assert mock_db_session_maker._test_session.execute.call_count == 0

    @pytest.mark.asyncio
    async def test_a_success_is_unaffected_by_the_mode(self, accepting_client):
        pub = self._publisher(accepting_client, on_failure="raise")
        await pub.publish("alerts", {"event_id": "e1"})
        assert accepting_client.put_events.call_count == 1

    @pytest.fixture
    def mock_db_session_maker(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        begin = AsyncMock()
        begin.__aenter__ = AsyncMock(return_value=None)
        begin.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=begin)

        class Ctx:
            async def __aenter__(self_inner):
                return session

            async def __aexit__(self_inner, *_):
                pass

        maker = MagicMock(side_effect=lambda: Ctx())
        maker._test_session = session
        return maker
