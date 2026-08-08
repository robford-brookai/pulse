"""`consent_ingress.declarer` — grain composition, provenance, and D15 attribution (task 3.1).

Covers three spec scenarios: "A landed row becomes a command", "A declared command is
customer.io-attributed and traceable", and "Ingress and sweep address the same row identically".

Two boundaries are faked, both the ones this change's testing posture pins: the landing read at
`RowSource` (`FixtureRowSource`) and the command API at the client's HTTP edge
(`httpx.MockTransport` under a real `PulseCoreClient`, `consent_sweep`'s pattern). No socket is
opened — `tests/conftest.py` blocks them for every run that collects this package.

Every row here is synthetic. The cross-package half of the grain assertion — that this module's
composition and `schedules.consent_sweep`'s agree on a live call, not just on a pinned string —
lives in `tests/test_consent_grain_parity.py` at the repo root, the only place both packages are
importable (this package deliberately does not depend on `schedules`; design decision 3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import httpx
from consent_ingress.declarer import (
    CUSTOMERIO_WRITER_ID,
    ConsentDeclaration,
    build_record_communication_consent_command,
    declare_consent_rows,
    landing_row_reference,
    ledger_subject_key,
)
from consent_ingress.row_source import ConsentRow, ConsentRowReader, FixtureRowSource
from pulse_core.client import COMMANDS_PATH, PulseCoreClient

_TOKEN = "unit-test-token"  # noqa: S105 — a fixture value, not a secret

_DECLARER_SOURCE = Path(__file__).resolve().parents[1] / "src" / "consent_ingress" / "declarer.py"

#: The two distinct (subject, channel) pairs this task's fixtures pin (task 3.1). Synthetic subject
#: keys and channel names only — no contact value, by the PHI rule this package's fixtures follow.
_LANDING_ROWS: tuple[dict[str, object], ...] = (
    {
        "subject_key": "SUBJ-001",
        "channel": "email",
        "to_state": "opted_in",
        "message_id": "cio-msg-0001",
        "event_time": "2026-08-01T12:00:00+00:00",
    },
    {
        "subject_key": "SUBJ-002",
        "channel": "sms",
        "to_state": "opted_out",
        "message_id": "cio-msg-0002",
        "event_time": "2026-08-01T12:05:00+00:00",
    },
)


def _fixture_rows() -> list[ConsentRow]:
    """The fixture landing rows as validated `ConsentRow`s, through the real reader.

    Driving `ConsentRowReader` rather than constructing `ConsentRow`s by hand keeps the declarer's
    input exactly what task 2.1's validation actually produces.
    """
    reader = ConsentRowReader(FixtureRowSource(_LANDING_ROWS), _NullCursorStore())
    rows: list[ConsentRow] = []
    for page in reader.batches():
        assert page.errors == []
        rows.extend(page.rows)
    return rows


class _NullCursorStore:
    """A never-checkpointed `CursorStore` — the cursor is task 2.1's contract, not this test's."""

    def __init__(self) -> None:
        self.saves: list[dict[str, object]] = []

    def load(self) -> None:
        return None

    def save(self, cursor: object) -> None:
        self.saves.append(cast("dict[str, object]", cursor))


class ScriptedApi:
    """The command API faked at the client's HTTP edge: recorded requests, scripted answers.

    Records the full request — method and path included — so a test can assert not just *what*
    was submitted but that `POST /commands` was the only write path used at all (spec: "A landed
    row becomes a command").
    """

    def __init__(self, *, writer_id: str = CUSTOMERIO_WRITER_ID) -> None:
        self.requests: list[tuple[str, str]] = []
        self.bodies: list[dict[str, object]] = []
        self._writer_id = writer_id

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        parsed = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        return httpx.Response(201, json={"event_id": f"e{len(self.bodies)}", "replayed": False})

    def client(self) -> PulseCoreClient:
        """A client authenticated with this ingress's own D15 credential.

        Stands in for what the CLI boundary (task 4.1) builds from config (the credential *name*)
        plus the environment (its token value).
        """
        return PulseCoreClient(
            "http://ledger.test",
            writer_id=self._writer_id,
            token=_TOKEN,
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


# --- Requirement: Landed consent rows declare through the command API ---


def test_a_landed_row_becomes_exactly_one_command():
    """spec: "A landed row becomes a command" — one `record_communication_consent` per row
    through the command API client, and no other write path used."""
    rows = _fixture_rows()
    api = ScriptedApi()

    declarations = declare_consent_rows(rows, api.client())

    assert len(rows) == 2
    assert len(declarations) == 2
    assert len(api.bodies) == 2
    assert api.requests == [("POST", COMMANDS_PATH), ("POST", COMMANDS_PATH)]
    assert [body["event_type"] for body in api.bodies] == [
        "record_communication_consent",
        "record_communication_consent",
    ]
    assert [body["subject_type"] for body in api.bodies] == ["communication_consent", "communication_consent"]
    assert all(declaration.response.classification.value == "committed" for declaration in declarations)


def test_each_declaration_pairs_its_own_row_with_its_own_command():
    """Declarations come back in read order, each carrying the row that produced it — the receipt
    (task 3.3) tallies these without re-reading the landing."""
    rows = _fixture_rows()

    declarations = declare_consent_rows(rows, ScriptedApi().client())

    assert [declaration.row for declaration in declarations] == rows
    assert [declaration.command.subject_key for declaration in declarations] == ["SUBJ-001:email", "SUBJ-002:sms"]
    assert [declaration.command.to_state for declaration in declarations] == ["opted_in", "opted_out"]
    assert [declaration.command.channel for declaration in declarations] == ["email", "sms"]
    assert all(isinstance(declaration, ConsentDeclaration) for declaration in declarations)


def test_no_rows_declares_nothing():
    api = ScriptedApi()

    assert declare_consent_rows([], api.client()) == []
    assert api.bodies == []


# --- Requirement: Every declaration attributes to actor `customer.io` ---


def test_a_declared_command_is_customerio_attributed_and_traceable():
    """spec: "A declared command is customer.io-attributed and traceable" — submitted under this
    ingress's own `customer.io` credential, payload referencing the source row's message id.

    Attribution is authentication (ADR-0003): no actor field travels in the body, so the actor
    assertion is that the client authenticates with the `customer.io` credential — observable here
    through the D16 idempotency key, which is always `{writer_id}:{digest}`.
    """
    rows = _fixture_rows()
    api = ScriptedApi()

    declare_consent_rows(rows, api.client())

    for row, body in zip(rows, api.bodies, strict=True):
        assert str(body["idempotency_key"]).startswith(f"{CUSTOMERIO_WRITER_ID}:")
        payload = cast("dict[str, object]", body["payload"])
        assert payload["evidence_ref"] == landing_row_reference(row)
        assert row.message_id in str(payload["evidence_ref"])


def test_no_actor_field_travels_in_any_declared_body():
    """ADR-0003: the credential supplies attribution server-side. A body naming its own actor
    would be a spoof attempt, so this module writes no actor field anywhere."""
    api = ScriptedApi()

    declare_consent_rows(_fixture_rows(), api.client())

    actor_fields = {"actor", "actor_id", "actor_type", "actor_authority", "producer"}
    for body in api.bodies:
        assert actor_fields.isdisjoint(body)
        assert actor_fields.isdisjoint(cast("dict[str, object]", body["payload"]))
    assert not any(field in _DECLARER_SOURCE.read_text() for field in ("actor_id=", "actor_type=", "producer="))


def test_the_declarer_reaches_the_ledger_only_through_the_client():
    """The "no other write path" half of Requirement 1, asserted structurally: this module holds
    no HTTP client, no SQL, and no bus publish of its own — `PulseCoreClient` is the only exit."""
    source = _DECLARER_SOURCE.read_text()

    assert "import httpx" not in source
    assert "snowflake" not in source.lower()
    assert "boto3" not in source


def test_provenance_reference_names_the_landing_message_and_no_contact_value():
    row = _fixture_rows()[0]

    reference = landing_row_reference(row)

    assert reference == f"cio:message:{row.message_id}"
    assert row.subject_key not in reference


def test_logical_time_is_the_rows_own_event_time_not_wall_clock():
    """D16 groundwork (design decision 4): `effective_at` doubles as the idempotency key's
    `logical_time`, so it must come from the row's own event identity. Task 3.2 proves the replay
    classification this makes possible; here the assertion is only that no wall clock is read."""
    rows = _fixture_rows()
    api = ScriptedApi()

    declare_consent_rows(rows, api.client())

    assert [body["effective_at"] for body in api.bodies] == [row.event_time.isoformat() for row in rows]
    assert "utcnow" not in _DECLARER_SOURCE.read_text()
    assert "now(" not in _DECLARER_SOURCE.read_text()


# --- Requirement: The consent grain composes identically to the reconciliation sweep ---


def test_ingress_and_sweep_address_the_same_row_identically():
    """spec: "Ingress and sweep address the same row identically" — subject key `S:C`, the exact
    composition `consent-reconciliation`'s sweep uses (`openspec/specs/consent-reconciliation`).

    The pinned-string half of the assertion. `tests/test_consent_grain_parity.py` at the repo root
    calls the sweep's own composition function and asserts agreement on live output.
    """
    assert ledger_subject_key("SUBJ-001", "email") == "SUBJ-001:email"
    assert ledger_subject_key("SUBJ-002", "sms") == "SUBJ-002:sms"

    command = build_record_communication_consent_command(_fixture_rows()[0])

    assert command.subject_key == "SUBJ-001:email"
    assert command.subject_type == "communication_consent"
    assert command.command_type == "record_communication_consent"


def test_the_channel_survives_composition_as_its_own_field():
    """The composed key folds the channel into the `current_state` row key; the command still
    carries `channel` separately, so a consumer never has to split the key back apart."""
    row = ConsentRow(
        subject_key="SUBJ-003",
        channel="voice",
        to_state="opted_out",
        message_id="cio-msg-0003",
        event_time=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )

    command = build_record_communication_consent_command(row)

    assert command.subject_key == "SUBJ-003:voice"
    assert command.channel == "voice"


def test_two_rows_for_one_subject_on_different_channels_address_different_keys():
    """`CommunicationConsent` is per patient x channel: one subject's email and sms consent are
    distinct ledger rows, never one row that overwrites itself."""
    assert ledger_subject_key("SUBJ-001", "email") != ledger_subject_key("SUBJ-001", "sms")
