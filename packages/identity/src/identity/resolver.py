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

import psycopg
from pulse_core.client import CommandResponse, PulseCoreClient, ResponseClassification
from pulse_core.generated import AttachIdentifierCommand, Command, MintPersonCommand, ResolveReferralCommand
from pulse_core.idempotency import derive_idempotency_key
from pulse_ledger import idempotency as ledger_idempotency
from pulse_ledger import review as ledger_review
from pulse_ledger.commit import Declaration

from identity.matcher import Ambiguous, CandidateLookup, Decision, Evidence, ExternalIdentifier, Match, Mint, Referral

logger = logging.getLogger("identity.resolver")

__all__ = [
    "HOLD_EVENT_TYPE",
    "CommandOutcome",
    "PersonKeyFactory",
    "QuarantineOutcome",
    "RejectedCommandError",
    "ResolutionOutcome",
    "ResolverError",
    "TransientCommandError",
    "act",
    "default_person_key",
    "quarantine",
]

PersonKeyFactory = Callable[[], str]

#: The namespace this module's own audit-scoped D16 key is derived under (design decision 5).
#: Distinct from the client's `writer_id` — this key is not the one that reaches the wire; it is
#: this module's own auditable record, so it does not need to share the client's identity.
_AUDIT_WRITER_ID = "identity-resolver"

#: The non-state-bearing fact `quarantine()` declares (design decision 6) — no `to_state`, so
#: `commit_declaration` skips catalog-transition validation and the state re-fold: a quarantined
#: Referral is left exactly where it was, in `received`.
HOLD_EVENT_TYPE = "resolution_hold"
_HOLD_SUBJECT_TYPE = "referral"


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


@dataclass(frozen=True)
class QuarantineOutcome:
    """What one `quarantine()` call produced: the hold fact and the queue row it belongs to.

    Stable across redelivery (design decision 6): a repeat of the same ambiguous decision derives
    the same hold idempotency key — a replay, not a second event — and finds the subject already
    pending, which is reported here rather than raised past.
    """

    referral_key: str
    hold_event_id: uuid.UUID
    review_id: uuid.UUID
    candidates: tuple[str, ...]


def quarantine(
    decision: Decision,
    *,
    referral_key: str,
    triggering_event_id: str,
    effective_at: datetime,
    conn: psycopg.Connection,
) -> QuarantineOutcome:
    """Hold an ambiguous referral for human review: a `resolution_hold` fact plus a queue row.

    Two effects, made convergent by construction (design decision 6): the hold fact commits under
    a D16 idempotency key derived from this resolution (`pulse_ledger.idempotency.commit_idempotent`
    — redelivery replays the same event, never a second one), then the subject is enqueued on
    `ledger.review_queue` (`pulse_ledger.review.quarantine_subject`) naming that event. Unlike
    `act()`, there is no `PulseCoreClient` here to derive its own wire key — `resolution_hold` is
    not part of the generated command vocabulary (it is a fact, not a command) — so the key this
    function derives is the one the ledger actually claims, not an audit-only copy.

    Either effect may already have happened before a crash: the hold fact may be committed with no
    queue row yet, or both may already exist. A `SubjectAlreadyPendingError` from the second effect
    is therefore not a failure here — it means a prior attempt already got this subject onto the
    queue — and this call reports that row instead of raising past it (spec: "a subject SHALL be
    pending at most once"). The referral itself never transitions: the hold fact carries no
    `to_state`, so `commit_declaration` skips the state re-fold and `received` stands.

    The candidate set travels as `decision.candidates` — pseudonymous person keys only, exactly as
    the matcher decided them — and no demographic field is ever in scope of this function to leak.

    Raises `TypeError` for any decision that is not `Ambiguous` — `act()` resolves `Match`/`Mint`.
    """
    if not isinstance(decision, Ambiguous):
        msg = f"quarantine() holds Ambiguous decisions only; got {type(decision).__name__} — act() resolves Match/Mint"
        raise TypeError(msg)

    idempotency_key = _hold_idempotency_key(referral_key, decision.evidence, triggering_event_id=triggering_event_id)
    hold = ledger_idempotency.commit_idempotent(
        conn,
        Declaration(
            subject_type=_HOLD_SUBJECT_TYPE,
            subject_key=referral_key,
            event_type=HOLD_EVENT_TYPE,
            effective_at=effective_at,
            actor_type="system",
            actor_id=_AUDIT_WRITER_ID,
            producer=_AUDIT_WRITER_ID,
            evidence={
                "matched_fields": list(decision.evidence.matched_fields),
                "rule_id": decision.evidence.rule_id,
                "candidate_count": decision.evidence.candidate_count,
                "idempotency_key": idempotency_key,
            },
        ),
        idempotency_key=idempotency_key,
    )
    logger.info(
        "quarantining subject %s (rule_id=%s, candidate_count=%d)",
        referral_key,
        decision.evidence.rule_id,
        decision.evidence.candidate_count,
    )
    try:
        review = ledger_review.quarantine_subject(
            conn,
            subject_type=_HOLD_SUBJECT_TYPE,
            subject_key=referral_key,
            hold_event_id=hold.event_id,
            candidates=decision.candidates,
        )
    except ledger_review.SubjectAlreadyPendingError as exc:
        logger.info("subject %s already pending review as %s", referral_key, exc.review_id)
        return QuarantineOutcome(
            referral_key=referral_key,
            hold_event_id=hold.event_id,
            review_id=exc.review_id,
            candidates=decision.candidates,
        )
    return QuarantineOutcome(
        referral_key=referral_key,
        hold_event_id=hold.event_id,
        review_id=review.review_id,
        candidates=review.candidates,
    )


def _hold_idempotency_key(referral_key: str, evidence: Evidence, *, triggering_event_id: str) -> str:
    """The D16 key that protects the hold fact — the real protective key, `commit_idempotent` claims.

    Unlike `_audit_key` (an audit-only record alongside the wire key `PulseCoreClient` derives for
    itself), `quarantine()` calls `commit_idempotent` directly — there is no intervening client — so
    this key must be the one the ledger actually enforces uniqueness on.
    """
    return derive_idempotency_key(
        writer_id=_AUDIT_WRITER_ID,
        subject_type=_HOLD_SUBJECT_TYPE,
        subject_key=referral_key,
        command_type=HOLD_EVENT_TYPE,
        payload={
            "matched_fields": list(evidence.matched_fields),
            "rule_id": evidence.rule_id,
            "candidate_count": evidence.candidate_count,
        },
        logical_time=triggering_event_id,
    )


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
