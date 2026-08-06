"""Decisions to commands: the resolver's write boundary (design decision 1, task 4.1).

`act(decision, referral, ...)` turns a `Match`/`Mint` decision (task 3.1's pure matcher core) into
the commands the ledger's command API accepts, submitted through
`pulse_core.client.PulseCoreClient` — design decision 1's whole point: `matcher.py`/`normalize.py`
are pure, and this module owns all command submission, so the determinism property test never has
to mock an effect.

- **Match** declares `resolve_referral` for the matched person, then `attach_identifier` for every
  referral identifier that person does not already hold — identifiers already held are skipped,
  never re-attached (design decision 5). "Already held" is answered by the same
  `CandidateLookup.lookup_identifier` port the matcher itself reads (task 3.1): an identifier no
  one holds, or that someone *else* holds, is submitted regardless — this module never pre-empts
  the ledger's own uniqueness judgment, it just lets a genuine conflict come back `rejected`.
- **Mint** declares `mint_person` for a freshly minted person key, then `resolve_referral` to that
  person, then `attach_identifier` for every referral identifier, in that order, so the referral
  never resolves to a person that does not exist yet (design decision 5). A newly minted person
  cannot already hold anything, so every identifier attaches unconditionally — no lookup needed.
- Every command carries the decision's evidence (matched fields, rule id, candidate count) plus a
  D16 idempotency key (`pulse_core.idempotency.derive_idempotency_key`, logical time = the
  triggering event's id) attached as an auditable field of that evidence (spec: "every resolution
  command carries evidence and an idempotency key"). The key that actually protects the ledger
  write is the one `PulseCoreClient.submit_command` derives itself from `effective_at` — the
  caller supplies that as the triggering event's own logical time, so the same event redelivered
  gets `replayed`, never a second event (`pulse_core.client`, D16). The two keys are deliberately
  distinct: this module's own key is scoped to *this resolution* (logical time = the event id) so
  the evidence record stays stable across redelivery and changes only when a referral is
  genuinely re-sent (a new event, a new key — design — Risks); it does not, and need not, retrace
  `pulse_core.client`'s private wire-payload shape to match its key byte for byte.
- `rejected` stops the sequence immediately — the raised error's evidence is the rejection, which
  is task 4.2's signal to quarantine. `transient` means the client's own bounded retry budget is
  already spent; this module raises rather than retrying again — redelivery of the triggering
  event is the outer retry (spec: consumption is one referral per invocation, safe under
  redelivery).

Logging never carries a demographic value or an identifier value — only field names, rule ids,
subject keys, and identifier *systems* (design decision 3c, flagged path (c)): `Referral.__repr__`
already redacts, and every log line here names `identifier.system`, never `identifier.value`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from pulse_core.client import CommandResponse, PulseCoreClient, ResponseClassification
from pulse_core.generated import AttachIdentifierCommand, Command, MintPersonCommand, ResolveReferralCommand
from pulse_core.idempotency import derive_idempotency_key

from identity.matcher import CandidateLookup, Decision, Evidence, ExternalIdentifier, Match, Mint, Referral

logger = logging.getLogger("identity.resolver")

__all__ = [
    "CommandOutcome",
    "PersonKeyFactory",
    "RejectedCommandError",
    "ResolutionOutcome",
    "ResolverError",
    "TransientCommandError",
    "act",
    "default_person_key",
]

PersonKeyFactory = Callable[[], str]

#: The namespace this module's own audit-scoped D16 key is derived under (design decision 5).
#: Distinct from the client's `writer_id` — this key is not the one that reaches the wire; it is
#: this module's own auditable record, so it does not need to share the client's identity.
_AUDIT_WRITER_ID = "identity-resolver"


def default_person_key() -> str:
    """A freshly minted person key. Opaque to this module; the ledger stores it as a bare string."""
    return f"tide-{uuid.uuid4()}"


class ResolverError(RuntimeError):
    """Base for a resolution the resolver could not carry to completion."""


class RejectedCommandError(ResolverError):
    """The ledger rejected one command in the sequence; the sequence stops here.

    Quarantine-worthy (design decision 5) — task 4.2 catches this and declares the hold. Carries
    the rejection itself (never the request payload) and every command that already committed or
    replayed before the rejection, so a caller can reason about partial progress without re-running
    anything: the ledger's own idempotency makes re-running the whole sequence safe regardless.
    """

    def __init__(self, command: Command, response: CommandResponse, completed: Sequence[CommandOutcome]) -> None:
        self.command_type = command.command_type
        self.response = response
        self.completed = tuple(completed)
        reason = response.rejection.message if response.rejection else "no detail"
        super().__init__(f"{command.command_type} rejected for subject {command.subject_key!r}: {reason}")


class TransientCommandError(ResolverError):
    """The client's own retry budget for one command was exhausted.

    Not retried again here: redelivery of the triggering event is the outer retry (spec —
    consumption is one referral per invocation, safe under redelivery).
    """

    def __init__(self, command: Command, response: CommandResponse) -> None:
        self.command_type = command.command_type
        self.response = response
        reason = response.rejection.message if response.rejection else "transient"
        super().__init__(
            f"{command.command_type} transient for subject {command.subject_key!r} after "
            f"{response.attempts} attempt(s): {reason}"
        )


@dataclass(frozen=True)
class CommandOutcome:
    """One declared command's classified answer, plus the audit-scoped key it carried."""

    command_type: str
    subject_key: str
    classification: ResponseClassification
    idempotency_key: str
    event_id: str | None


@dataclass(frozen=True)
class ResolutionOutcome:
    """Every command one `act()` call declared, in declaration order."""

    referral_key: str
    person_key: str
    commands: tuple[CommandOutcome, ...]


def act(
    decision: Decision,
    referral: Referral,
    *,
    referral_key: str,
    triggering_event_id: str,
    effective_at: datetime,
    lookup: CandidateLookup,
    client: PulseCoreClient,
    person_key_factory: PersonKeyFactory = default_person_key,
) -> ResolutionOutcome:
    """Declare the commands one `Match` or `Mint` decision requires, in design decision 5's order.

    `effective_at` must be the triggering event's own logical time (never wall-clock "now") — it
    is what `PulseCoreClient.submit_command` uses as the D16 logical time, so redelivery of the
    same event derives the same wire key and comes back `replayed`. `triggering_event_id` scopes
    this module's own audit key the same way (see module docstring).

    Raises `TypeError` for any decision that is not `Match`/`Mint` — `Ambiguous` quarantines
    instead (task 4.2), and this function never guesses at one. Raises `RejectedCommandError` the
    moment any command in the sequence comes back `rejected`, or `TransientCommandError` if the
    client's retry budget for one command is spent; neither error undoes commands that already
    committed or replayed.
    """
    if isinstance(decision, Mint):
        person_key = person_key_factory()
        mint_command = MintPersonCommand(subject_key=person_key)
        outcomes = [
            _declare(
                mint_command,
                decision.evidence,
                [],
                client=client,
                effective_at=effective_at,
                triggering_event_id=triggering_event_id,
            )
        ]
        identifiers_to_attach: Sequence[ExternalIdentifier] = referral.identifiers
    elif isinstance(decision, Match):
        person_key = decision.person_id
        outcomes = []
        identifiers_to_attach = _unheld_identifiers(referral.identifiers, person_key, lookup)
    else:
        msg = f"act() resolves Match/Mint decisions only; got {type(decision).__name__} — Ambiguous quarantines (task 4.2)"
        raise TypeError(msg)

    resolve_command = ResolveReferralCommand(subject_key=referral_key, person_key=person_key)
    outcomes.append(
        _declare(
            resolve_command,
            decision.evidence,
            outcomes,
            client=client,
            effective_at=effective_at,
            triggering_event_id=triggering_event_id,
        )
    )

    for identifier in identifiers_to_attach:
        attach_command = AttachIdentifierCommand(
            subject_key=person_key, system=identifier.system, value=identifier.value
        )
        outcomes.append(
            _declare(
                attach_command,
                decision.evidence,
                outcomes,
                client=client,
                effective_at=effective_at,
                triggering_event_id=triggering_event_id,
            )
        )

    return ResolutionOutcome(referral_key=referral_key, person_key=person_key, commands=tuple(outcomes))


def _unheld_identifiers(
    identifiers: Sequence[ExternalIdentifier], person_key: str, lookup: CandidateLookup
) -> tuple[ExternalIdentifier, ...]:
    """Every referral identifier `person_key` does not already hold, in stable (system, value) order.

    Skips only identifiers this exact person already holds (design decision 5). An identifier held
    by someone else is left in — submitted anyway — and left to the ledger's own uniqueness
    constraint, which comes back `rejected`; `act`'s stop-on-reject rule quarantines it from there.
    """
    ordered = sorted(identifiers, key=lambda entry: (entry.system, entry.value))
    return tuple(entry for entry in ordered if lookup.lookup_identifier(entry.system, entry.value) != person_key)


def _audit_key(command: Command, *, triggering_event_id: str) -> str:
    """This resolution's own D16 audit key — logical time = the triggering event id.

    Deliberately independent of `pulse_core.client`'s private wire-payload shape (this module's
    layering does not extend to duplicating another module's internals): the fields chosen here
    only have to be stable per identical command and distinct across distinct ones, which the
    command's own declared fields already are.
    """
    fields = command.model_dump(mode="json")
    payload = {key: value for key, value in fields.items() if key not in ("command_type", "subject_type")}
    return derive_idempotency_key(
        writer_id=_AUDIT_WRITER_ID,
        subject_type=command.subject_type,
        subject_key=command.subject_key,
        command_type=command.command_type,
        payload=payload,
        logical_time=triggering_event_id,
    )


def _declare(
    command: Command,
    evidence: Evidence,
    completed: Sequence[CommandOutcome],
    *,
    client: PulseCoreClient,
    effective_at: datetime,
    triggering_event_id: str,
) -> CommandOutcome:
    idempotency_key = _audit_key(command, triggering_event_id=triggering_event_id)
    logger.info(
        "declaring %s for subject %s (rule_id=%s, candidate_count=%d)",
        command.command_type,
        command.subject_key,
        evidence.rule_id,
        evidence.candidate_count,
    )
    response = client.submit_command(
        command,
        effective_at=effective_at,
        evidence={
            "matched_fields": list(evidence.matched_fields),
            "rule_id": evidence.rule_id,
            "candidate_count": evidence.candidate_count,
            "idempotency_key": idempotency_key,
        },
    )
    if response.classification is ResponseClassification.REJECTED:
        logger.warning(
            "%s rejected for subject %s: %s",
            command.command_type,
            command.subject_key,
            response.rejection.message if response.rejection else "no detail",
        )
        raise RejectedCommandError(command, response, completed)
    if response.classification is ResponseClassification.TRANSIENT:
        raise TransientCommandError(command, response)
    return CommandOutcome(
        command_type=command.command_type,
        subject_key=command.subject_key,
        classification=response.classification,
        idempotency_key=idempotency_key,
        event_id=response.event_id,
    )
