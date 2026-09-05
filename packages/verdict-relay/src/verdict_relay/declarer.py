"""One mart row to one attributed, idempotent `declare_verdict` command (task 2.2).

The declarer is the relay's half of the single write path: it turns a validated mart-contract row
into a `pulse_core.generated.DeclareVerdictCommand`, submits it through `PulseCoreClient` — which
derives the D16 idempotency key client-side and posts under the relay's service credential (D15:
the credential *name* is configuration, the value comes from the environment, actor attribution is
applied server-side from that credential) — and handles the four response classifications
distinctly (design decision 4):

- **committed** → counted as declared; the subject's watermark advances.
- **replayed** → an idempotent hit: counted, never re-declared, watermark advances the same way.
- **rejected** → counted, logged with the ledger's reason and catalog version, never retried.
- **transient** → retried with jittered exponential backoff up to `DECLARE_MAX_ATTEMPTS`, after
  which the run fails naming the row. The retry loop itself — attempt budget, backoff, and the
  three-count settle it retries toward — is the kit's `pulse_core.connector.declare`
  (connector-kit spec, task 2.2); retry policy lives above the client either way, keyed off
  classification only — the client is constructed with `max_attempts=1` (`service_client`), so
  nothing retries twice.

Two structural rules the declarer owns:

- **Validation before submission** (design decision 5): the row is validated on the generated
  command type — trinary outcome, indeterminate-requires-reason, aware `as_of` — so an invalid
  row raises `RowValidationError` locally with zero API calls.
- **Stale-skip against the cursor watermark** (design decision 3): a row strictly older than its
  subject's high-water `as_of` is skipped and counted, never declared and never an error. A row
  *equal* to the watermark is declared so D16 can answer it as a replay. The watermark values stay
  JSON-native ISO strings, ready for the writer cursor the reader persists.

The mart contract carries no `subject_type` column, and the ledger validates `subject_type`
against the catalog — so the declarer takes an explicit `subject_type_by_verdict` mapping
(configuration), and an unmapped `verdict_type` fails validation naming the row. The row's
`verdict_type` and `lineage_ref` travel in the command's `lineage`, so distinct verdict types on
one subject stay distinct facts under D16.

**Outcome→transition pairing** (design decision 3, billing-state): a verdict type carrying a
`transition_by_outcome` entry (`verdict_type → {outcome → to_state}`) follows a committed or
replayed verdict with a `declare_transition` on the same subject. The transition's D16 key derives
from the verdict row — same `effective_at`, a reason citing the verdict's `verdict_type`,
`rule_version`, and `lineage_ref` — so the pair is replay-safe as a unit: a rerun replays both
halves, and a run that died between the two completes the pair on resume (the verdict replays, the
transition commits). A committed or replayed transition counts as `transitioned`; one the ledger
rejects counts as `transition_rejected` — distinctly from a rejected verdict — and is never
retried: past a lifecycle boundary, rejection is the correct answer, and the verdict half stands.
A verdict type without an entry, or an outcome its entry does not map, submits the verdict only —
exactly as before.

Errors and logs carry subject keys, verdict types, and timestamps only — never outcome values or
anything beyond the row's keys (no-PHI posture).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from os import environ

import httpx
import pydantic
from pulse_core.client import CommandResponse, PulseCoreClient, ResponseClassification
from pulse_core.connector import DeclareCounts, Jitter, Sleeper, submit_with_retry
from pulse_core.connector import TransientExhaustedError as _KitTransientExhaustedError
from pulse_core.generated import DeclareTransitionCommand, DeclareVerdictCommand

logger = logging.getLogger("verdict_relay.declarer")

#: Transient submissions get exactly this many attempts before the run fails (spec:
#: verdict-declare, "Response classifications drive distinct handling").
DECLARE_MAX_ATTEMPTS = 5

DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 30.0


class RowDisposition(str, Enum):
    """What the declarer did with one row — the run's receipt counts key off these."""

    DECLARED = "declared"
    REPLAYED = "replayed"
    SKIPPED_STALE = "skipped_stale"
    REJECTED = "rejected"


@dataclass(frozen=True)
class DeclarerCounts:
    """Running tally of dispositions; `failed` is the run's to count, since a failure raises.

    `declared`/`replayed`/`rejected` are the kit's own `DeclareCounts` three-count core (committed
    renamed to declared, this relay's own term); `skipped_stale`, `transitioned`, and
    `transition_rejected` are dispositions this relay adds on top — the kit's receipt is not the
    whole of this one (connector-kit spec: a connector's own receipt may carry more).
    """

    declared: int = 0
    replayed: int = 0
    skipped_stale: int = 0
    rejected: int = 0
    transitioned: int = 0
    transition_rejected: int = 0

    @classmethod
    def from_base(
        cls,
        base: DeclareCounts,
        *,
        skipped_stale: int,
        transitioned: int,
        transition_rejected: int,
    ) -> DeclarerCounts:
        return cls(
            declared=base.committed,
            replayed=base.replayed,
            rejected=base.rejected,
            skipped_stale=skipped_stale,
            transitioned=transitioned,
            transition_rejected=transition_rejected,
        )


class DeclarerError(RuntimeError):
    """Base for failures that carry a row reference — keys only, never verdict content."""


class RowValidationError(DeclarerError):
    """The row cannot become a legal command; no API call was attempted."""

    def __init__(self, row_ref: str, detail: str) -> None:
        self.row_ref = row_ref
        super().__init__(f"row {row_ref} failed validation before submission: {detail}")


class TransientExhaustedError(DeclarerError):
    """Every attempt classified transient; the run fails naming the row.

    Wraps the kit's own `pulse_core.connector.declare.TransientExhaustedError` (raised by
    `submit_with_retry`) rather than replacing it: this subclass exists so the exception stays a
    `DeclarerError` — the base `run.py` catches — while carrying the same row-named message the
    relay always raised.
    """

    def __init__(self, row_ref: str, attempts: int, detail: str) -> None:
        self.row_ref = row_ref
        self.attempts = attempts
        super().__init__(f"row {row_ref} failed after {attempts} transient attempts: {detail}")


class MissingCredentialError(DeclarerError):
    """The named environment variable is unset — the error names the variable, never a value."""

    def __init__(self, token_env: str) -> None:
        self.token_env = token_env
        super().__init__(
            f"service credential environment variable {token_env} is not set (D15: the name is "
            "configuration, the value lives in the environment)"
        )


def service_client(
    base_url: str,
    *,
    writer_id: str,
    token_env: str,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
) -> PulseCoreClient:
    """The relay's command-API client under its D15 service credential.

    `token_env` is the credential's *name*; its value is read from the environment here and
    nowhere else. The client is pinned to `max_attempts=1` because retry policy belongs to the
    declarer (design decision 4) — a client that also retried would multiply the attempt budget.
    """
    token = environ.get(token_env)
    if token is None:
        raise MissingCredentialError(token_env)
    return PulseCoreClient(
        base_url,
        writer_id=writer_id,
        token=token,
        transport=transport,
        timeout=timeout,
        max_attempts=1,
    )


def _row_ref(row: Mapping[str, object]) -> str:
    """The row named by its keys — subject key, verdict type, as_of — and nothing else."""
    return f"subject={row.get('subject_id')!r} verdict_type={row.get('verdict_type')!r} as_of={row.get('as_of')!r}"


def _aware_as_of(command: DeclareVerdictCommand, row_ref: str) -> datetime:
    if command.as_of.tzinfo is None or command.as_of.tzinfo.utcoffset(command.as_of) is None:
        raise RowValidationError(row_ref, "as_of must be timezone-aware; a naive timestamp has no instant")
    return command.as_of


class Declarer:
    """Declares mart rows one at a time, in the (subject, `as_of`) order the reader yields.

    `watermarks` is the per-subject high-water `as_of` map carried in the writer cursor (design
    decision 3): pass the map loaded from the persisted cursor, and read `watermarks` back to
    persist it — values are ISO-8601 UTC strings, JSON-native by construction. It only advances on
    committed or replayed, so a crash before persistence re-declares at most what D16 answers as
    replays.
    """

    def __init__(
        self,
        client: PulseCoreClient,
        *,
        subject_type_by_verdict: Mapping[str, str],
        transition_by_outcome: Mapping[str, Mapping[str, str]] | None = None,
        watermarks: Mapping[str, str] | None = None,
        max_attempts: int = DECLARE_MAX_ATTEMPTS,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        sleep: Sleeper = time.sleep,
        jitter: Jitter = random.random,
    ) -> None:
        if max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        self._client = client
        self._subject_type_by_verdict = dict(subject_type_by_verdict)
        self._transition_by_outcome = {
            verdict_type: dict(by_outcome) for verdict_type, by_outcome in (transition_by_outcome or {}).items()
        }
        self._watermarks = dict(watermarks or {})
        self._max_attempts = max_attempts
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._sleep = sleep
        self._jitter = jitter
        self._base_counts = DeclareCounts()
        self._skipped_stale = 0
        self._transitioned = 0
        self._transition_rejected = 0

    @property
    def counts(self) -> DeclarerCounts:
        return DeclarerCounts.from_base(
            self._base_counts,
            skipped_stale=self._skipped_stale,
            transitioned=self._transitioned,
            transition_rejected=self._transition_rejected,
        )

    @property
    def watermarks(self) -> dict[str, str]:
        """Per-subject high-water `as_of`, JSON-native, ready for the writer cursor."""
        return dict(self._watermarks)

    def declare(self, row: Mapping[str, object]) -> RowDisposition:
        """Validate, stale-check, and submit one mart row; return its disposition.

        Raises `RowValidationError` (no API call was made) or `TransientExhaustedError` (the
        attempt budget is spent) — both name the row by its keys.
        """
        row_ref = _row_ref(row)
        command = self._command_for(row, row_ref)
        as_of = _aware_as_of(command, row_ref)

        watermark = self._watermarks.get(command.subject_key)
        if watermark is not None and as_of < datetime.fromisoformat(watermark):
            self._skipped_stale += 1
            logger.info("skipped stale row %s behind watermark %s", row_ref, watermark)
            return RowDisposition.SKIPPED_STALE

        response = self._submit_with_retry(command, as_of, row_ref)
        disposition = self._settle(command, response, as_of, row_ref)
        if disposition in (RowDisposition.DECLARED, RowDisposition.REPLAYED):
            self._pair_transition(command, as_of, row_ref)
        return disposition

    def _command_for(self, row: Mapping[str, object], row_ref: str) -> DeclareVerdictCommand:
        verdict_type = row.get("verdict_type")
        subject_type = self._subject_type_by_verdict.get(str(verdict_type))
        if subject_type is None:
            raise RowValidationError(row_ref, f"verdict_type {verdict_type!r} has no configured subject_type")
        try:
            return DeclareVerdictCommand.model_validate({
                "subject_type": subject_type,
                "subject_key": row["subject_id"],
                "outcome": row.get("outcome"),
                "reason": row.get("reason"),
                "rule_version": row.get("rule_version"),
                "as_of": row.get("as_of"),
                "lineage": {
                    "lineage_ref": row.get("lineage_ref"),
                    "verdict_type": verdict_type,
                },
            })
        except KeyError as exc:
            raise RowValidationError(row_ref, f"missing contract column {exc.args[0]!r}") from exc
        except pydantic.ValidationError as exc:
            fields = "; ".join(
                f"{'.'.join(str(loc) for loc in error['loc']) or 'command'}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise RowValidationError(row_ref, fields) from exc

    def _submit_with_retry(
        self,
        command: DeclareVerdictCommand | DeclareTransitionCommand,
        as_of: datetime,
        row_ref: str,
    ) -> CommandResponse:
        # A pydantic KeyError above guarantees rule_version/as_of exist; `effective_at=as_of`
        # doubles as the D16 logical time, so the same row always derives the same key. The
        # attempt loop and backoff are the kit's (`pulse_core.connector.declare`); its exception
        # is translated to this module's own `TransientExhaustedError` so `run.py`'s
        # `except DeclarerError` still catches it.
        try:
            return submit_with_retry(
                lambda: self._client.submit_command(command, effective_at=as_of),
                ref=row_ref,
                max_attempts=self._max_attempts,
                base_delay_seconds=self._base_delay,
                max_delay_seconds=self._max_delay,
                sleep=self._sleep,
                jitter=self._jitter,
            )
        except _KitTransientExhaustedError as exc:
            raise TransientExhaustedError(row_ref, exc.attempts, exc.detail) from exc

    def _settle(
        self,
        command: DeclareVerdictCommand,
        response: CommandResponse,
        as_of: datetime,
        row_ref: str,
    ) -> RowDisposition:
        if response.classification is ResponseClassification.REJECTED:
            rejection = response.rejection
            logger.warning(
                "row %s rejected by the ledger: %s (reason=%s catalog_version=%s); not retried",
                row_ref,
                rejection.message if rejection else "no detail",
                rejection.reason if rejection else None,
                rejection.catalog_version if rejection else None,
            )
            self._base_counts = self._base_counts.record(response.classification)
            return RowDisposition.REJECTED

        self._advance_watermark(command.subject_key, as_of)
        self._base_counts = self._base_counts.record(response.classification)
        if response.classification is ResponseClassification.REPLAYED:
            logger.info("row %s replayed: idempotent hit, not a second declaration", row_ref)
            return RowDisposition.REPLAYED
        logger.info("row %s declared (event_id=%s)", row_ref, response.event_id)
        return RowDisposition.DECLARED

    def _pair_transition(self, command: DeclareVerdictCommand, as_of: datetime, row_ref: str) -> None:
        """Follow a committed or replayed verdict with its configured `declare_transition`.

        The transition's D16 key derives from the verdict row: same subject, same `effective_at`,
        and a reason built only from the row's own fields — so the same row always derives the
        same pair of keys, and the pair replays as a unit. Runs after the verdict half settled,
        so a transient-exhausted transition fails the run with the verdict already committed; the
        resumed run replays the verdict (the watermark only skips strictly-older rows) and
        completes the pair.
        """
        lineage = command.lineage or {}
        verdict_type = str(lineage.get("verdict_type"))
        to_state = self._transition_by_outcome.get(verdict_type, {}).get(command.outcome.value)
        if to_state is None:
            return
        transition = DeclareTransitionCommand(
            subject_type=command.subject_type,
            subject_key=command.subject_key,
            to_state=to_state,
            reason=(
                f"paired declare_verdict verdict_type={verdict_type} "
                f"rule_version={command.rule_version} lineage_ref={lineage.get('lineage_ref')}"
            ),
        )
        response = self._submit_with_retry(transition, as_of, row_ref)
        if response.classification is ResponseClassification.REJECTED:
            rejection = response.rejection
            logger.warning(
                "row %s paired transition rejected by the ledger: %s (reason=%s catalog_version=%s); "
                "not retried, the verdict stands",
                row_ref,
                rejection.message if rejection else "no detail",
                rejection.reason if rejection else None,
                rejection.catalog_version if rejection else None,
            )
            self._transition_rejected += 1
            return
        self._transitioned += 1
        logger.info(
            "row %s paired transition %s (event_id=%s)",
            row_ref,
            response.classification.value,
            response.event_id,
        )

    def _advance_watermark(self, subject_key: str, as_of: datetime) -> None:
        existing = self._watermarks.get(subject_key)
        if existing is None or datetime.fromisoformat(existing) < as_of:
            self._watermarks[subject_key] = as_of.isoformat()
