"""Brook fixture overlays: declarative engineered patients on top of the generated base.

Each overlay is one YAML file, schema-validated here, naming the design-doc fixture it
implements (design.md decision 3). Application is deterministic and all-or-nothing: a malformed
overlay fails naming the file and reason before anything is applied, and applying the same set
twice yields identical results. The overlay semantics are grounded in the object model
(design/migration/rpc-object-model-assessment.md) and the genesis adjudication rules
(design/migration/genesis-and-cutover.md §2) — these are the mandatory regression fixtures
downstream suites depend on. All patients are synthetic by construction; no PHI.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

OVERLAY_FORMAT = "synthea-seed/overlay@1"

DEFAULT_OVERLAY_DIR = Path(__file__).parent / "overlays"

#: The design docs' mandatory fixture sets; the shipped overlay directory must cover them all.
NAMED_FIXTURES: tuple[str, ...] = (
    "mid_month_exclusivity_switch",
    "trinary_verdicts",
    "genesis_contradictions",
    "quarantine_bound_consent",
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
PatientId = Annotated[str, StringConstraints(pattern=r"^brook-fx-[a-z0-9-]+$")]

#: §5.2 ended-state reasons, verbatim from the object model.
EndReason = Literal[
    "consent_revoked",
    "deceased",
    "patient_choice",
    "copay_burden",
    "moved",
    "graduated",
    "program_switch",
    "clinic_offboarded",
]


class OverlayError(ValueError):
    """A malformed overlay, always naming the file and the reason."""

    def __init__(self, file_name: str, reason: str) -> None:
        self.file_name = file_name
        self.reason = reason
        super().__init__(f"{file_name}: {reason}")


class Enrollment(BaseModel):
    """A program enrollment; exclusivity_group is the CMS same-group conflict key (I6, §5.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str = Field(min_length=1)
    exclusivity_group: Identifier
    status: Literal["active", "on_hold", "ended"]
    activated_on: datetime.date | None = None
    ended_on: datetime.date | None = None
    end_reason: EndReason | None = None

    @model_validator(mode="after")
    def _ended_carries_its_evidence(self) -> Enrollment:
        if self.status == "ended" and (self.ended_on is None or self.end_reason is None):
            msg = "an ended enrollment requires ended_on and end_reason (object model §5.2)"
            raise ValueError(msg)
        if self.status != "ended" and (self.ended_on is not None or self.end_reason is not None):
            msg = f"a {self.status} enrollment must not carry ended_on/end_reason"
            raise ValueError(msg)
        return self


class BillingEpisode(BaseModel):
    """One patient x program x calendar month; the month-grain exclusivity home (§5.2, v0.7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str = Field(min_length=1)
    exclusivity_group: Identifier
    month: datetime.date
    status: Literal["open", "closed"]
    #: Trinary per §3 plus `pending` = not yet run (§5.4); `indeterminate` = ran but unevaluable.
    qualification_verdict: Literal["qualified", "not_qualified", "indeterminate", "pending"]
    verdict_reason: str | None = None
    rule_version: str | None = None

    @model_validator(mode="after")
    def _month_grain_and_trinary_discipline(self) -> BillingEpisode:
        if self.month.day != 1:
            msg = f"month must be a first-of-month date, got {self.month.isoformat()}"
            raise ValueError(msg)
        if self.qualification_verdict == "indeterminate" and not self.verdict_reason:
            msg = "an indeterminate verdict requires its mandatory reason (object model §3)"
            raise ValueError(msg)
        if self.qualification_verdict != "indeterminate" and self.verdict_reason is not None:
            msg = f"verdict_reason is only legal on indeterminate, not {self.qualification_verdict!r}"
            raise ValueError(msg)
        return self


class Verdict(BaseModel):
    """A computed verdict with lineage (I3): trinary outcome, rule_version, as_of."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Identifier
    outcome: Literal["positive", "negative", "indeterminate"]
    reason: str | None = None
    rule_version: str = Field(min_length=1)
    as_of: datetime.date

    @model_validator(mode="after")
    def _indeterminate_carries_its_reason(self) -> Verdict:
        if self.outcome == "indeterminate" and not self.reason:
            msg = "an indeterminate verdict requires its mandatory reason (object model §3)"
            raise ValueError(msg)
        if self.outcome != "indeterminate" and self.reason is not None:
            msg = f"reason is only legal on indeterminate, not {self.outcome!r}"
            raise ValueError(msg)
        return self


class SourceState(BaseModel):
    """What one legacy system asserts about the patient — the raw material of adjudication."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: Identifier
    attribute: Identifier
    value: str = Field(min_length=1)


class GenesisExpectation(BaseModel):
    """The referee's expected disposition for the patient's source states (genesis §2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition: Literal["adjudicated", "quarantine"]
    adjudication_rule: str | None = None
    expected_state: str | None = None
    quarantine_reason: str | None = None

    @model_validator(mode="after")
    def _disposition_is_complete(self) -> GenesisExpectation:
        if self.disposition == "adjudicated" and not (self.adjudication_rule and self.expected_state):
            msg = "an adjudicated disposition requires adjudication_rule and expected_state"
            raise ValueError(msg)
        if self.disposition == "quarantine" and not self.quarantine_reason:
            msg = "a quarantine disposition requires quarantine_reason"
            raise ValueError(msg)
        return self


class Consent(BaseModel):
    """A consent record; evidence_ref absent is exactly the quarantine-bound case (genesis §2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: Identifier
    status: Literal["granted", "revoked"]
    recorded_in: Identifier
    evidence_ref: str | None


class PatientState(BaseModel):
    """The engineered state an overlay declares for one patient."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enrollments: tuple[Enrollment, ...] = ()
    billing_episodes: tuple[BillingEpisode, ...] = ()
    verdicts: tuple[Verdict, ...] = ()
    source_states: tuple[SourceState, ...] = ()
    genesis_expectation: GenesisExpectation | None = None
    consents: tuple[Consent, ...] = ()

    @model_validator(mode="after")
    def _not_empty(self) -> PatientState:
        engineered = (
            self.enrollments,
            self.billing_episodes,
            self.verdicts,
            self.source_states,
            self.consents,
            self.genesis_expectation,
        )
        if not any(engineered):
            msg = "a patient state must engineer at least one thing"
            raise ValueError(msg)
        return self


class OverlayPatient(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    patient_id: PatientId
    state: PatientState


class Overlay(BaseModel):
    """One fixture file: the named design-doc fixture and its engineered patients."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    overlay_format: str = Field(alias="format")
    fixture: Identifier
    design_ref: str = Field(min_length=1)
    description: str = Field(min_length=1)
    patients: tuple[OverlayPatient, ...] = Field(min_length=1)
    #: Set by the loader; None for overlays constructed in code.
    source_file: str | None = None

    @model_validator(mode="after")
    def _well_formed(self) -> Overlay:
        if self.overlay_format != OVERLAY_FORMAT:
            msg = f"unsupported overlay format {self.overlay_format!r}; expected {OVERLAY_FORMAT!r}"
            raise ValueError(msg)
        ids = [p.patient_id for p in self.patients]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            msg = f"duplicate patient_id within one overlay: {duplicates}"
            raise ValueError(msg)
        return self


def _first_error(error: ValidationError) -> str:
    detail = error.errors()[0]
    location = ".".join(str(part) for part in detail["loc"])
    return f"{location}: {detail['msg']}" if location else detail["msg"]


def load_overlay(path: Path) -> Overlay:
    """Parse and validate one overlay file, or raise OverlayError naming file and reason."""
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise OverlayError(path.name, f"not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise OverlayError(path.name, "overlay must be a YAML mapping")
    try:
        overlay = Overlay.model_validate(raw)
    except ValidationError as error:
        raise OverlayError(path.name, _first_error(error)) from error
    return overlay.model_copy(update={"source_file": path.name})


def load_overlay_set(directory: Path | None = None) -> tuple[Overlay, ...]:
    """Load every overlay in the directory; any malformed file fails the whole set.

    All-or-nothing by construction: validation errors are collected across the full set and
    raised together, so nothing is ever applied partially (spec: "Overlay validation rejects
    malformed fixtures").
    """
    root = directory if directory is not None else DEFAULT_OVERLAY_DIR
    paths = sorted(root.glob("*.yaml"))
    if not paths:
        raise OverlayError(str(root), "no overlay files found")
    overlays: list[Overlay] = []
    problems: list[str] = []
    for path in paths:
        try:
            overlays.append(load_overlay(path))
        except OverlayError as error:
            problems.append(str(error))
    seen: dict[str, str] = {}
    for overlay in overlays:
        for patient in overlay.patients:
            file_name = overlay.source_file or overlay.fixture
            if patient.patient_id in seen:
                problems.append(
                    f"{file_name}: patient_id {patient.patient_id!r} already declared in {seen[patient.patient_id]}"
                )
            else:
                seen[patient.patient_id] = file_name
    if problems:
        scope = "overlay set"
        combined = "; ".join(problems)
        raise OverlayError(scope, combined)
    return tuple(overlays)


def apply_overlays(base: Mapping[str, Mapping[str, Any]], overlays: Sequence[Overlay]) -> dict[str, dict[str, Any]]:
    """Apply overlays onto the generated base, returning a new population mapping.

    Pure and deterministic: the base is never mutated, engineered patients are added (or their
    engineered state replaced) by patient identifier in sorted order, and applying the same set
    to the result again yields an identical population.
    """
    result: dict[str, dict[str, Any]] = {pid: dict(record) for pid, record in sorted(base.items())}
    entries = sorted(
        ((patient.patient_id, overlay) for overlay in overlays for patient in overlay.patients),
        key=lambda pair: pair[0],
    )
    for patient_id, overlay in entries:
        patient = next(p for p in overlay.patients if p.patient_id == patient_id)
        record = dict(result.get(patient_id, {}))
        record["brook_fixture"] = overlay.fixture
        record["brook_state"] = patient.state.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
        result[patient_id] = record
    return result
