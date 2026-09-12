"""The inherited-exclusion inventory and its synthetic reachability reproducers (task 2.2).

`critical-path-verification` design decision 3 asks a question a list of debt cannot answer: of
the typing, coverage, test-collection and security-suppression exclusions PULSE inherited with the
OCEAN absorption (ADR-0002), *which sit on a path a PULSE event can actually travel*, and what is
being done about each. This module is the gate under that answer. Four parts, each failing for its
own reason:

**The inventory is complete.** `docs/critical-path-exclusion-inventory.md` carries one row per
exclusion. The suppression half of that table is not trusted prose: it is re-derived here by
running ruff with the repository's `packages/ocean/**` security suppressions switched off, and the
derived set must equal the inventoried set exactly. A newly suppressed site cannot enter the tree
without an audit row, and a row cannot outlive the finding it describes.

**Reachability is computed, not asserted.** A row says `bus-publish`, `bus-consume`,
`bus-publish+consume` or `off-bus`, and each is checked against the bus topology itself —
`ocean_broker.catalog.CONSUMER_DOMAINS` for the consume side, the `ocean_broker` import for the
publish side. Wiring a service onto the bus flips its reachability and fails this gate until its
rows are re-audited, which is the point: the risk an exclusion carries is a function of what the
service is connected to, and that changes without anyone touching the exclusion.

**A confirmed reachable defect blocks readiness.** The findings table's `fix-required`
disposition is red by construction; a finding leaves it only when its focused fix merges.

**The boundaries the audit relied on are executable.** The audit's conclusions — that every
interpolated SQL identifier on a reachable path comes from an allowlist, and that the identity
package's PHI holders redact — are claims about runtime behaviour, so they are tested as runtime
behaviour with synthetic inputs. The deferred risks get reproducers too: each one is a live
demonstration of the exposure, so the day it is fixed, its reproducer fails and forces the row to
be re-dispositioned rather than quietly left behind.

Every fixture here is synthetic and deliberately unrealistic. The sentinels are nonsense tokens
with a shared prefix so a leak is unambiguous and so nothing in this file could be read as data
about a person.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import structlog
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_INVENTORY = _REPO_ROOT / "docs" / "critical-path-exclusion-inventory.md"
_SERVICES_DIR = _REPO_ROOT / "packages" / "ocean" / "services"

#: The security-relevant rules pyproject suppresses across `packages/ocean/**`. Kept here as the
#: audit's declared scope and checked against pyproject below, so the two cannot drift apart.
_AUDITED_RULES = ("S104", "S106", "S110", "S310", "S311", "S324", "S607", "S608")

# Closed vocabularies. A cell outside them is an un-triaged cell, which is the state this gate
# exists to forbid: "unknown" is not a disposition.
_OWNER_ROLES = frozenset({
    "ocean-service-owner",
    "ocean-platform-owner",
    "ocean-test-owner",
    "pulse-platform-owner",
})
_REACHABILITY = frozenset({"bus-publish", "bus-consume", "bus-publish+consume", "off-bus", "n/a"})
_RISKS = frozenset({"low", "medium", "high"})
#: `fix-required` is the readiness blocker. The spec clause — "a confirmed reachable injection or
#: leak blocks readiness until its focused fix merges" — is enforced by never letting a row rest
#: there: writing it down turns this gate red, and only the merged fix turns it green again.
_DISPOSITIONS = frozenset({"accepted", "deferred", "fix-required", "fixed"})

_EXCLUSION_COLUMNS = ("Path", "Exclusion", "Sites", "Owner role", "Reachability", "Risk", "Disposition", "Evidence")
_FINDING_COLUMNS = ("Path", "Finding", "Owner role", "Reachability", "Risk", "Disposition", "Reproducer")

# Synthetic sentinels. Not identifiers of anything: a shared nonsense prefix, a date no living
# person carries, and tokens chosen so that finding one in a log line is proof of a leak.
_SENTINEL = "ZZQX"
_SYNTH_SURNAME = "Zzqxsurname"
_SYNTH_GIVEN = "Zzqxgiven"
_SYNTH_DOB = "1801-01-01"
_SYNTH_SEX = "u"
_SYNTH_IDENTIFIER = "ZZQX-SYNTHETIC-IDENTIFIER-0000"
_SYNTH_CELL = "ZZQX-SYNTHETIC-TIMESTAMP-CELL"
_SYNTH_PAYLOAD = "ZZQX-SYNTHETIC-PAYLOAD-FRAGMENT"


# ---------------------------------------------------------------------------
# Inventory parsing
# ---------------------------------------------------------------------------


def _table_under(heading: str, columns: tuple[str, ...]) -> list[dict[str, str]]:
    """The single pipe table following `heading` in the inventory document."""
    text = _INVENTORY.read_text()
    parts = text.split(heading, 1)
    assert len(parts) == 2, f"{_INVENTORY.name} has no {heading!r} section"
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in parts[1].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(dict(zip(header, cells, strict=True)))
    assert header is not None, f"the {heading!r} section has no table"
    assert tuple(header) == columns, f"{heading} columns are {tuple(header)}, expected {columns}"
    assert rows, f"the {heading!r} table is empty"
    return rows


@pytest.fixture(scope="module")
def exclusions() -> list[dict[str, str]]:
    return _table_under("## Inventory", _EXCLUSION_COLUMNS)


@pytest.fixture(scope="module")
def findings() -> list[dict[str, str]]:
    return _table_under("## Reachable-path findings", _FINDING_COLUMNS)


def _path_of(row: dict[str, str]) -> str:
    return row["Path"].strip("`").split(":")[0]


# ---------------------------------------------------------------------------
# 1. Both tables are well-formed and triaged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", ["exclusions", "findings"])
def test_every_row_is_fully_triaged(table, request):
    """No blank cells, and every judgement cell drawn from its closed vocabulary."""
    for row in request.getfixturevalue(table):
        where = f"{row['Path']} / {row.get('Exclusion') or row.get('Finding')}"
        for column, value in row.items():
            assert value, f"{where}: column {column!r} is empty — an un-triaged row"
        assert row["Owner role"] in _OWNER_ROLES, f"{where}: owner role {row['Owner role']!r} is not a known role"
        assert row["Reachability"] in _REACHABILITY, f"{where}: reachability {row['Reachability']!r} is not known"
        assert row["Risk"] in _RISKS, f"{where}: risk {row['Risk']!r} is not one of {sorted(_RISKS)}"
        assert row["Disposition"] in _DISPOSITIONS, f"{where}: disposition {row['Disposition']!r} is not known"


@pytest.mark.parametrize("table", ["exclusions", "findings"])
def test_every_inventoried_path_exists(table, request):
    """A row naming a path that is gone describes debt that no longer exists."""
    for row in request.getfixturevalue(table):
        path = _path_of(row)
        target = _REPO_ROOT / path.removesuffix("/**")
        assert target.exists(), f"inventory row names {path!r}, which is not in the tree"


@pytest.mark.parametrize("table", ["exclusions", "findings"])
def test_no_confirmed_reachable_defect_is_open(table, request):
    """The readiness blocker.

    `fix-required` means the audit confirmed a reachable injection or leak. The spec makes that
    state block readiness until the focused fix merges, so this gate stays red for exactly as long
    as such a row is open: recording the finding turns it red, merging the fix and flipping the row
    to `fixed` turns it green.
    """
    rows = request.getfixturevalue(table)
    blocking = [
        f"{row['Path']} — {row.get('Evidence') or row.get('Reproducer')}"
        for row in rows
        if row["Disposition"] == "fix-required"
    ]
    assert not blocking, "confirmed reachable defects block readiness until their fixes merge:\n" + "\n".join(blocking)


def test_deferred_live_path_risks_name_an_executable_reproducer(findings):
    """A risk left open on a live path is only deferred if someone can re-run it.

    The spec's wording: deferred non-confirmed risks have an owner and an executable reproducer.
    The owner is the row's own column; the reproducer is a node id in this file.
    """
    for row in findings:
        if row["Disposition"] != "deferred" or row["Reachability"] == "off-bus":
            continue
        node = row["Reproducer"].strip("`")
        assert node.startswith(f"{Path(__file__).name}::"), (
            f"{row['Path']}: a deferred risk on a live path must name an executable reproducer in "
            f"{Path(__file__).name}, got {row['Reproducer']!r}"
        )
        name = node.split("::", 1)[1]
        assert name in globals(), f"{row['Path']}: reproducer {name!r} does not exist in this module"


# ---------------------------------------------------------------------------
# 2. The inventory matches the tree it describes
# ---------------------------------------------------------------------------


def _ruff() -> str:
    """The ruff the repository's own lint step uses. Absent ruff is a broken toolchain, not a skip."""
    candidate = Path(sys.executable).parent / "ruff"
    resolved = str(candidate) if candidate.exists() else shutil.which("ruff")
    assert resolved, "ruff is not installed; `task lint` and this gate both need it"
    return resolved


def _suppressed_sites() -> dict[tuple[str, str], int]:
    """Re-derive the suppressed security findings by linting `packages/ocean` without the ignores.

    `--isolated` is what does it: the suppressions live in pyproject's `per-file-ignores`, so
    linting under the repository config reports nothing and would make this gate vacuous.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, repo-local ruff
        [
            _ruff(),
            "check",
            "--isolated",
            "--target-version",
            "py310",
            "--select",
            ",".join(_AUDITED_RULES),
            "--no-fix",
            "--output-format",
            "json",
            "packages/ocean",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.stdout, f"ruff produced no findings document:\n{completed.stderr}"
    sites: dict[tuple[str, str], int] = {}
    for finding in json.loads(completed.stdout):
        path = Path(finding["filename"]).resolve().relative_to(_REPO_ROOT).as_posix()
        sites[(finding["code"], path)] = sites.get((finding["code"], path), 0) + 1
    return sites


def test_pyproject_suppresses_exactly_the_audited_rules():
    """The audit's scope and the configuration's scope are the same list."""
    config = yaml_safe_toml()
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]["packages/ocean/**"]
    suppressed = {rule for rule in ignores if re.fullmatch(r"S\d+", rule)}
    assert suppressed == set(_AUDITED_RULES), (
        f"pyproject suppresses the security rules {sorted(suppressed)} across packages/ocean/**, but "
        f"this audit covers "
        f"{sorted(_AUDITED_RULES)}; extend the audit and the inventory before extending the group"
    )


def test_inventory_covers_every_suppressed_security_site(exclusions):
    """Every (rule, file) ruff would report is inventoried, with the right site count, and no more.

    Both directions matter. A missing row is un-audited debt; a surplus row is an audit claiming to
    cover a finding that is no longer there.
    """
    derived = _suppressed_sites()
    inventoried = {
        (row["Exclusion"], _path_of(row)): int(row["Sites"]) for row in exclusions if row["Exclusion"] in _AUDITED_RULES
    }
    missing = sorted(set(derived) - set(inventoried))
    surplus = sorted(set(inventoried) - set(derived))
    assert not missing, f"suppressed security findings with no inventory row: {missing}"
    assert not surplus, f"inventory rows for findings ruff no longer reports: {surplus}"
    miscounted = {key: (inventoried[key], derived[key]) for key in derived if inventoried[key] != derived[key]}
    assert not miscounted, f"inventoried site counts disagree with ruff (inventoried, actual): {miscounted}"


def test_inventory_covers_the_typing_coverage_and_collection_exclusions(exclusions):
    """The non-lint exclusions the Taskfile encodes each have a row.

    These are the exclusions no linter reports: the ocean services are outside `TYPED_PATHS` and
    `COV_PATHS`, and the cross-service test tree is outside `TESTED_PATHS` (ADR-0002). They are
    read out of the Taskfile so a future re-inclusion has to come back through this gate.
    """
    taskfile = yaml.safe_load((_REPO_ROOT / "Taskfile.yml").read_text())
    variables = taskfile["vars"]
    inventoried = {(row["Exclusion"], _path_of(row)) for row in exclusions}

    assert "packages/ocean/services" not in variables["TYPED_PATHS"], (
        "the ocean services are now typechecked — retire the `mypy` inventory row rather than leaving it"
    )
    assert ("mypy", "packages/ocean/services/**") in inventoried, "the mypy exclusion of ocean's services has no row"

    assert "packages/ocean/services" not in variables["COV_PATHS"], (
        "the ocean services now carry coverage — retire the `coverage` inventory row rather than leaving it"
    )
    assert ("coverage", "packages/ocean/services/**") in inventoried, (
        "the coverage exclusion of ocean's services has no row"
    )

    tested = variables["TESTED_PATHS"]
    assert "packages/ocean/tests " not in f"{tested} ", (
        "the cross-service test tree is now collected wholesale — retire the `tests` inventory row"
    )
    assert ("tests", "packages/ocean/tests/**") in inventoried, "the ADR-0002 test-tree exclusion has no row"


def yaml_safe_toml() -> dict[str, Any]:
    """pyproject.toml, parsed. Split out so the reader above states one thing."""
    import tomllib

    return tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())


# ---------------------------------------------------------------------------
# 3. Reachability is computed from the bus topology
# ---------------------------------------------------------------------------


def _bus_reachability() -> dict[str, str]:
    """Each ocean service's reachability, derived from the bus itself.

    Consume side: `CONSUMER_DOMAINS` is the table behind both the Terraform rules and the local
    LocalStack topology, so a service in it has a rule and a queue delivering PULSE events to it.
    Publish side: importing `ocean_broker` is what a publish site does — there is one publisher and
    one addressing table, by ADR-0002.
    """
    from ocean_broker.catalog import CONSUMER_DOMAINS

    consumers = set(CONSUMER_DOMAINS)
    publishers = {
        service.name
        for service in sorted(_SERVICES_DIR.iterdir())
        if service.is_dir()
        and any("ocean_broker" in path.read_text() for path in sorted((service / "src").rglob("*.py")))
    }
    reachability: dict[str, str] = {}
    for service in sorted(_SERVICES_DIR.iterdir()):
        if not service.is_dir():
            continue
        publishes, consumes = service.name in publishers, service.name in consumers
        if publishes and consumes:
            reachability[service.name] = "bus-publish+consume"
        elif publishes:
            reachability[service.name] = "bus-publish"
        elif consumes:
            reachability[service.name] = "bus-consume"
        else:
            reachability[service.name] = "off-bus"
    return reachability


@pytest.mark.parametrize("table", ["exclusions", "findings"])
def test_service_reachability_matches_the_bus_topology(table, request):
    """A service's inventoried reachability is the one the catalog and its imports imply.

    This is the column that rots fastest and matters most: wiring an off-bus service onto the bus
    raises the risk of every exclusion it carries, and nobody editing the catalog would think to
    revisit a lint suppression. Here, they have to.
    """
    reachability = _bus_reachability()
    for row in request.getfixturevalue(table):
        parts = _path_of(row).split("/")
        if len(parts) < 5 or parts[:3] != ["packages", "ocean", "services"]:
            # A tree-wide row (`packages/ocean/services/**`) spans every service; only a row that
            # names one service can be checked against one service's reachability.
            continue
        service = parts[3]
        assert service in reachability, f"{row['Path']} names {service!r}, which is not an ocean service"
        assert row["Reachability"] == reachability[service], (
            f"{row['Path']}: inventoried as {row['Reachability']!r}, but the bus topology says "
            f"{reachability[service]!r} — re-audit this row against the path the service now sits on"
        )


def test_exactly_one_service_is_off_the_bus():
    """Pins the audit's headline scoping claim so a silent change forces a re-read.

    The audit's largest concentration of suppressed SQL construction is in `stacte-bridge`, and its
    disposition rests entirely on that service neither publishing to nor consuming from the bus. If
    that ever stops being true, the deferral stops being justified.
    """
    off_bus = sorted(name for name, kind in _bus_reachability().items() if kind == "off-bus")
    assert off_bus == ["stacte-bridge"], (
        f"the set of off-bus ocean services changed to {off_bus}; the inventory's deferrals for "
        "off-bus SQL construction were written against stacte-bridge alone"
    )


# ---------------------------------------------------------------------------
# 4. Query-boundary regression cases (synthetic, no database)
# ---------------------------------------------------------------------------


class _RecordingConnection:
    """A `psycopg.Connection` stand-in that records what would have been sent.

    Recording rather than executing is the whole point: the question is what reaches the server as
    *query text* versus what reaches it as a bound parameter, and that is decided before any
    connection exists.
    """

    def __init__(self) -> None:
        self.queries: list[tuple[str, object]] = []

    def execute(self, query: str, params: object = None):
        self.queries.append((query, params))
        return _EmptyCursor()


class _EmptyCursor:
    def fetchall(self) -> list[object]:
        return []

    def __iter__(self):
        return iter(())


_HOSTILE_IDENTIFIER = f"enrollment'; DROP TABLE ledger.current_state; -- {_SENTINEL}"


def test_ledger_enumeration_refuses_a_hostile_subject_type():
    """The catalog is the allowlist under the one query the ledger builds by concatenation.

    `enumerate_state` appends fragments to a SELECT, so the guarantee is not "it uses bound
    parameters" alone — it is that the only caller-supplied values reaching the string are first
    checked against the generated catalog. A hostile subject type is refused before a connection is
    touched, so no query text is built at all.
    """
    from pulse_ledger.reads import enumerate_state
    from pulse_ledger.validation import IllegalTransitionError

    conn = _RecordingConnection()
    with pytest.raises(IllegalTransitionError):
        enumerate_state(conn, _HOSTILE_IDENTIFIER)
    assert conn.queries == [], "a rejected subject type still reached the connection"


def test_ledger_enumeration_refuses_a_hostile_state_filter():
    """Same boundary on the state filter, which is the other value the catalog validates."""
    from pulse_ledger.reads import enumerate_state
    from pulse_ledger.validation import TRANSITIONS, IllegalTransitionError

    subject_type = sorted(TRANSITIONS)[0]
    conn = _RecordingConnection()
    with pytest.raises(IllegalTransitionError):
        enumerate_state(conn, subject_type, [_HOSTILE_IDENTIFIER])
    assert conn.queries == [], "a rejected state filter still reached the connection"


def test_ledger_enumeration_binds_the_page_cursor_rather_than_interpolating_it():
    """The one caller value with no allowlist is the page cursor, so it must be bound, not spliced.

    A subject key is opaque to the catalog — any string can be one — so the protection here is
    parameter binding rather than validation. Asserting the sentinel is absent from the query text
    and present in the parameters is what distinguishes the two.
    """
    from pulse_ledger.reads import enumerate_state
    from pulse_ledger.validation import TRANSITIONS

    subject_type = sorted(TRANSITIONS)[0]
    conn = _RecordingConnection()
    enumerate_state(conn, subject_type, after_subject_key=_HOSTILE_IDENTIFIER, limit=5)

    (query, params) = conn.queries[0]
    assert _SENTINEL not in query, f"the page cursor was interpolated into the query text: {query!r}"
    assert params["after_subject_key"] == _HOSTILE_IDENTIFIER, "the page cursor was not bound as a parameter"
    assert params["limit"] == 5


def test_ledger_enumeration_refuses_a_negative_page_size():
    """A negative limit is a caller arithmetic bug; the read refuses rather than emitting `LIMIT -1`."""
    from pulse_ledger.reads import NegativeLimitError, enumerate_state
    from pulse_ledger.validation import TRANSITIONS

    conn = _RecordingConnection()
    with pytest.raises(NegativeLimitError):
        enumerate_state(conn, sorted(TRANSITIONS)[0], limit=-1)
    assert conn.queries == []


def test_bus_rule_patterns_come_from_an_allowlisted_consumer_name():
    """The consume side's identifier boundary: a rule is only ever built for a catalogued consumer."""
    from ocean_broker.catalog import CONSUMER_DOMAINS, consumer_rule_pattern

    with pytest.raises(KeyError):
        consumer_rule_pattern(f"warehouse-sync' OR '1'='1 {_SENTINEL}")
    pattern = consumer_rule_pattern(sorted(CONSUMER_DOMAINS)[0])
    assert set(pattern) <= {"source", "detail-type"}


def test_twenty_projection_refuses_a_subject_key_the_filter_grammar_cannot_express():
    """The projection's filter grammar has no quoting, so reserved characters are refused, not escaped.

    This is the consume path with a genuine string-built query — Twenty's REST filter — and the
    guard is a refusal at envelope parse time. A subject key carrying a filter separator never
    reaches a request.
    """
    from twenty_projection.apply import FILTER_RESERVED, V1_BOARD, MalformedEventError, parse_envelope

    envelope = {
        "subject_type": V1_BOARD.subject_type,
        "subject_key": f"{_SENTINEL}[eq]:x,y",
        "event_id": "00000000-0000-0000-0000-000000000000",
        "seq": 1,
        "effective_at": "2026-01-01T00:00:00+00:00",
        "payload": {"to_state": "active", "program": "zzqx-program"},
    }
    assert FILTER_RESERVED & set(envelope["subject_key"]), "the fixture no longer carries a reserved character"
    with pytest.raises(MalformedEventError):
        parse_envelope(envelope, V1_BOARD)


# ---------------------------------------------------------------------------
# 5. Redaction regression cases (synthetic, no database)
# ---------------------------------------------------------------------------


def _synthetic_demographics():
    from identity.normalize import Demographics

    return Demographics(last_name=_SYNTH_SURNAME, first_name=_SYNTH_GIVEN, dob=_SYNTH_DOB, sex=_SYNTH_SEX)


def _synthetic_referral():
    from identity.matcher import ExternalIdentifier, Referral

    return Referral(
        demographics=_synthetic_demographics(),
        identifiers=(ExternalIdentifier(system="zzqx-synthetic-system", value=_SYNTH_IDENTIFIER),),
    )


def test_demographics_redact_through_every_rendering_a_log_line_can_reach():
    """`__repr__` is the only runtime defence, so every way a value could be rendered is checked.

    There is no logging filter anywhere in these packages: the redacting reprs *are* the boundary.
    That makes the interesting cases the indirect renderings — an f-string, a container's repr, a
    `%s` a stdlib formatter expands lazily — because each one calls a different dunder.
    """
    demographics = _synthetic_demographics()
    renderings = [
        repr(demographics),
        str(demographics),
        f"{demographics}",
        f"{demographics!r}",
        repr([demographics]),
        repr({"referral": demographics}),
        "%s" % (demographics,),  # noqa: UP031 - the lazy %-expansion a logging call performs
        "{}".format(demographics),  # noqa: UP032 - the point is the __format__ path, not the f-string
    ]
    for rendering in renderings:
        assert _SENTINEL not in rendering.upper(), f"a demographic value leaked through {rendering!r}"
        assert "REDACTED" in rendering


def test_a_demographics_holder_redacts_when_a_log_record_formats_it():
    """The real shape of the leak: a lazy `%s` argument rendered inside the logging machinery."""
    record = logging.LogRecord(
        name="zzqx",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="referral rejected: %s",
        args=(_synthetic_demographics(),),
        exc_info=None,
    )
    assert _SENTINEL not in record.getMessage().upper()


def test_normalization_rejections_name_the_field_and_never_the_value():
    """A rejection has to be safe to log — it is the one error a bad source row produces routinely."""
    from identity.normalize import Demographics, NormalizationError, composite_digest

    ambiguous = Demographics(
        last_name=_SYNTH_SURNAME, first_name=_SYNTH_GIVEN, dob=f"03/04/1990 {_SENTINEL}", sex=_SYNTH_SEX
    )
    with pytest.raises(NormalizationError) as raised:
        composite_digest(ambiguous)
    assert _SENTINEL not in str(raised.value).upper(), "the rejection echoed the offending value"
    assert raised.value.field == "dob"
    assert raised.value.rule_id


def test_matcher_holders_and_decisions_carry_no_demographic_value():
    """Nothing downstream of `resolve` holds PHI — checked on the objects `resolve` actually returns.

    The docstring claim is that a decision is reviewable without being sensitive. So the referral's
    repr is checked, and then the decision's: evidence names *fields*, and a match names a person
    id, and neither can be made to render a sentinel.
    """
    from identity.matcher import InMemoryLookup, Mint, resolve

    referral = _synthetic_referral()
    assert _SENTINEL not in repr(referral).upper(), "Referral.__repr__ leaked a demographic or identifier value"
    assert _SENTINEL not in repr([referral]).upper()

    decision = resolve(referral, InMemoryLookup())
    assert isinstance(decision, Mint), "an empty store must mint"
    assert _SENTINEL not in repr(decision).upper(), "the decision carried a value out of the matcher"
    assert decision.evidence.matched_fields, "evidence must still name the fields it searched"


def test_identifier_conflicts_name_the_system_and_holder_never_the_identifier():
    """The store's own rejection path, which a genesis harness hits with real-shaped data."""
    from identity.matcher import ExternalIdentifier, IdentifierAlreadyHeldError, InMemoryLookup, Person

    held = ExternalIdentifier(system="zzqx-synthetic-system", value=_SYNTH_IDENTIFIER)
    persons = [
        Person(person_id="zzqx-person-1", demographics=_synthetic_demographics(), identifiers=(held,)),
        Person(person_id="zzqx-person-2", demographics=_synthetic_demographics(), identifiers=(held,)),
    ]
    with pytest.raises(IdentifierAlreadyHeldError) as raised:
        InMemoryLookup(persons)
    message = str(raised.value)
    assert _SYNTH_IDENTIFIER not in message, "the conflict echoed the identifier value"
    assert "zzqx-synthetic-system" in message and "zzqx-person-1" in message


def test_mart_contract_rejections_do_not_echo_the_offending_cell():
    """The task-2.2 fix, kept honest.

    `mart_reader` validates the verdict mart's timestamp columns, and the message it raises is
    logged verbatim by `run.run_once`. It used to quote the offending cell — while the kit's own
    identical validator (`pulse_core.connector.rows.required_timestamp`) refuses to, for the stated
    reason that a drifted source column "could hold anything, including payload content". A mart
    row is not first-party data, so this reproducer drives a synthetic drifted cell all the way to
    the log line and asserts the cell never appears there.
    """
    from verdict_relay.mart_reader import MartContractError, _validated

    row = {
        "subject_id": "zzqx-subject-1",
        "verdict_type": "zzqx-verdict",
        "outcome": "zzqx-outcome",
        "reason": None,
        "rule_version": "v0",
        "lineage_ref": "zzqx-lineage",
        "as_of": "2026-01-01T00:00:00+00:00",
        "computed_at": _SYNTH_CELL,
    }
    with pytest.raises(MartContractError) as raised:
        _validated(0, row)
    assert _SYNTH_CELL not in str(raised.value), "the mart rejection echoed the offending cell value"
    assert "computed_at" in str(raised.value), "the rejection must still name the column"


# ---------------------------------------------------------------------------
# 6. Deferred-risk reproducers
#
# Each asserts today's behaviour, so the day the exposure is fixed its reproducer fails and the
# inventory row has to be re-dispositioned instead of being silently left behind.
# ---------------------------------------------------------------------------


def test_deferred_risk_transport_error_text_reaches_the_publish_failure_log():
    """Deferred: a transport exception's own message can carry the envelope into a log line.

    `EventBridgePublisher` logs `str(exc)` from the `put_events` call. A botocore parameter
    validation error embeds the offending parameter — which is the serialized envelope — in its
    message, so the envelope reaches the log by a route the publisher never inspects. The same
    string is persisted by the ledger relay into `ledger.outbox.last_error`. Reproduced here with
    a synthetic exception of that shape; no AWS, no network.
    """
    import asyncio

    from ocean_broker.publisher import EventBridgePublisher

    publisher = EventBridgePublisher(region="us-east-1", event_bus_name="zzqx-bus")

    class _EchoingClient:
        @staticmethod
        def put_events(**kwargs: object) -> dict[str, object]:
            message = f"Invalid parameter: Entries[0].Detail, value: {json.dumps(kwargs)}"
            raise ValueError(message)

    publisher._client = _EchoingClient()

    with structlog.testing.capture_logs() as captured:
        asyncio.run(publisher.publish("audit", {"event_id": "zzqx-1", "payload": {"note": _SYNTH_PAYLOAD}}))

    logged = " ".join(str(entry) for entry in captured)
    assert _SYNTH_PAYLOAD in logged, (
        "the transport-error echo no longer reaches the log — good news, but this deferred risk's "
        "inventory row must now be re-dispositioned"
    )


def test_deferred_risk_ledger_response_body_reaches_the_rejection_message():
    """Deferred: an unrecognised ledger response has 200 bytes of its body embedded in the error.

    `pulse_core.client` builds `UnexpectedResponseError` from the raw response body, and five
    first-party declarers log the resulting message. The ledger's own bodies quote only timestamps,
    so nothing leaks today — but the ledger is not the only thing that can answer an HTTP call, and
    a proxy or gateway body is not first-party text. Reproduced with a synthetic body.
    """
    from pulse_core.client import UnexpectedResponseError

    error = UnexpectedResponseError(status_code=599, body=f"upstream said {_SYNTH_PAYLOAD}")
    assert _SYNTH_PAYLOAD in str(error), (
        "the response body no longer reaches the exception message — good news, but this deferred "
        "risk's inventory row must now be re-dispositioned"
    )
