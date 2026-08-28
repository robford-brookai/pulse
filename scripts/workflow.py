#!/usr/bin/env python3
"""
Parse and validate the executable workflow block in WORKFLOW.md.

WORKFLOW.md declares its own YAML block the source of truth, with the prose walkthrough and the
mermaid diagram as projections of it. Nothing read that block until this script existed, so the
"source of truth" claim was honoured by hand or not at all.

Usage:
    python scripts/workflow.py lint              # offline structural checks
    python scripts/workflow.py lint --linear     # additionally check team, project and statuses live
    python scripts/workflow.py show              # dump the parsed block as JSON

The offline half is CI-safe: no network, no credentials, no npm globals. That split is deliberate.
Verifying that every status string exists in the pinned team's status set — which the edit_protocol
asks for — needs the Linear API, and per docs/contracts/consumes.md anything needing credentials
stays out of `task check`. So the YAML declares `linear.statuses`, the offline lint checks that
every status *used* is one of those declared, and `--linear` checks that the declared set still
matches the live team. Each half fails where it can actually be run.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

WORKFLOW_MD = Path("WORKFLOW.md")

REQUIRED_TOP_LEVEL = ("version", "linear", "state_resolution", "gates", "live_execution", "routing", "steps")
# `agent(fable, review-assist)` / `agent(per work-order model field)` — first argument only.
ACTOR_TIER_RE = re.compile(r"agent\(\s*([a-z0-9_-]+)")
GATE_TOKEN_RE = re.compile(r"\bG_[A-Z_]+\b")
VERSION_HEADER_RE = re.compile(r"\*\*Status:\*\*\s*v([0-9]+(?:\.[0-9]+)*)")


class WorkflowError(Exception):
    """WORKFLOW.md does not describe a runnable workflow."""


def load(path: Path = WORKFLOW_MD) -> tuple[dict, str]:
    """Return (the ade_workflow mapping, the full document text)."""
    if not path.exists():
        msg = f"{path} not found"
        raise WorkflowError(msg)
    text = path.read_text()

    blocks = [b for b in re.findall(r"```yaml\n(.*?)```", text, re.DOTALL) if "ade_workflow:" in b]
    if not blocks:
        msg = "no ```yaml block containing `ade_workflow:` — the source of truth is missing"
        raise WorkflowError(msg)
    if len(blocks) > 1:
        msg = f"{len(blocks)} yaml blocks declare `ade_workflow:`; exactly one may"
        raise WorkflowError(msg)

    try:
        parsed = yaml.safe_load(blocks[0])
    except yaml.YAMLError as exc:
        msg = f"the ade_workflow block is not valid YAML: {exc}"
        raise WorkflowError(msg) from exc

    workflow = (parsed or {}).get("ade_workflow")
    if not isinstance(workflow, dict):
        msg = "`ade_workflow` must be a mapping"
        raise WorkflowError(msg)
    return workflow, text


def _next_targets(step: dict) -> list[str]:
    """Step ids a step can hand off to. `next` is either an id or an outcome -> id mapping."""
    nxt = step.get("next")
    if nxt is None:
        return []
    if isinstance(nxt, str):
        return [nxt]
    if isinstance(nxt, dict):
        return [v for v in nxt.values() if isinstance(v, str)]
    return []


def _gate_names(value) -> list[str]:
    """Gate references, tolerating conditional suffixes and lists of gates."""
    items = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in items:
        names.extend(GATE_TOKEN_RE.findall(str(item)))
    return names


def _step_ids(steps: list) -> tuple[list[str], list[str]]:
    ids: list[str] = []
    errors: list[str] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or "id" not in step:
            errors.append(f"steps[{i}] has no `id`")
            continue
        ids.append(step["id"])
    duplicates = sorted({sid for sid in ids if ids.count(sid) > 1})
    if duplicates:
        errors.append(f"duplicate step ids: {', '.join(duplicates)}")
    return ids, errors


def _check_step_refs(steps: list, known: set[str], gates: set[str], tiers: list) -> list[str]:
    """A step may only hand off to a step that exists, or gate on a gate that exists."""
    errors: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or "id" not in step:
            continue
        sid = step["id"]
        errors += [
            f"step {sid}: `next` points at {t!r}, which is not a step id" for t in _next_targets(step) if t not in known
        ]
        errors += [
            f"step {sid}: references gate {g}, which is not defined in `gates`"
            for g in _gate_names(step.get("gate", []))
            if g not in gates
        ]
        # `agent(per work-order model field)` names no tier, so only flag tier-looking words.
        errors += [
            f"step {sid}: actor tier {t!r} is not in routing.tiers {tiers}"
            for t in ACTOR_TIER_RE.findall(str(step.get("actor", "")))
            if t not in tiers and t in {"sonnet", "opus", "fable", "haiku"}
        ]
    return errors


def _check_gates(gates: dict, known: set[str]) -> list[str]:
    errors: list[str] = []
    for name, gate in gates.items():
        if not isinstance(gate, dict):
            errors.append(f"gate {name} must be a mapping")
            continue
        errors += [
            f"gate {name}: `blocks` names {b!r}, which is not a step id"
            for b in gate.get("blocks") or []
            if b not in known
        ]
    return errors


def _check_live_execution(block: object, known: set[str]) -> list[str]:
    """`excluded_steps` is load-bearing — dispatch reads it to decide what never becomes a work order."""
    if not isinstance(block, dict):
        return ["live_execution must be a mapping"]
    return [
        f"live_execution: `excluded_steps` names {e!r}, which is not a step id. Known steps: {', '.join(sorted(known))}"
        for e in block.get("excluded_steps") or []
        if e not in known
    ]


def _check_routing(routing: dict) -> list[str]:
    tiers = routing.get("tiers") or []
    default = routing.get("default") or {}
    errors = [
        f"routing.default.{key} is {default.get(key)!r}, which is not in routing.tiers {tiers}"
        for key in ("model", "max_tier")
        if default.get(key) is not None and default.get(key) not in tiers
    ]
    if any(not isinstance(n, str) or not n.strip() for n in routing.get("serial_lane_always") or []):
        errors.append("routing.serial_lane_always entries must be non-empty strings")
    return errors


def check_structure(workflow: dict) -> list[str]:
    """Schema, step-id references, gate references, lane references, tier references."""
    errors: list[str] = []

    missing = [k for k in REQUIRED_TOP_LEVEL if k not in workflow]
    if missing:
        errors.append(f"ade_workflow is missing required keys: {', '.join(missing)}")

    steps = workflow.get("steps") or []
    if not isinstance(steps, list) or not steps:
        errors.append("`steps` must be a non-empty list")
        return errors

    ids, id_errors = _step_ids(steps)
    known = set(ids)
    gates = workflow.get("gates") or {}
    routing = workflow.get("routing") or {}

    return (
        errors
        + id_errors
        + _check_step_refs(steps, known, set(gates), routing.get("tiers") or [])
        + _check_gates(gates, known)
        + _check_live_execution(workflow.get("live_execution") or {}, known)
        + _check_routing(routing)
    )


def used_statuses(workflow: dict) -> set[str]:
    """Every Linear status string the workflow references.

    Matched against the declared set rather than scraped loosely: a status is only recognised
    where it appears as a whole phrase, so `Todo` inside `Triage -> Todo` counts once.
    """
    declared = set((workflow.get("linear") or {}).get("statuses") or [])
    if not declared:
        return set()

    haystack = yaml.safe_dump(
        {
            "state_resolution": workflow.get("state_resolution"),
            "status_ownership": (workflow.get("linear") or {}).get("status_ownership"),
            "linear_status": [s.get("linear_status") for s in workflow.get("steps") or [] if isinstance(s, dict)],
        },
        default_flow_style=False,
    )
    return {status for status in declared if re.search(rf"\b{re.escape(status)}\b", haystack)}


def _written_statuses(workflow: dict) -> set[str]:
    """Status phrases the workflow actually writes.

    Read from the two places the edit_protocol says must resolve against the team's status set:
    the bracketed lists in `state_resolution.order`, and each step's `linear_status`.
    """
    written: set[str] = set()
    for entry in (workflow.get("state_resolution") or {}).get("order") or []:
        for value in entry if isinstance(entry, dict) else []:
            written.update(re.findall(r"\[([^\]]+)\]", str(value)))
    for step in workflow.get("steps") or []:
        if isinstance(step, dict) and step.get("linear_status"):
            written.add(str(step["linear_status"]))
    return written


def check_statuses(workflow: dict) -> list[str]:
    """Every status string used must be one the `linear.statuses` set declares.

    The declared set is what `--linear` later verifies against the live team, so this offline
    check and the online one compose: used ⊆ declared, and declared == live.
    """
    linear = workflow.get("linear") or {}
    declared = linear.get("statuses")
    if not declared:
        return [
            "linear.statuses is not declared, so no status string can be validated offline. "
            "Add the pinned team's status set to the YAML — `--linear` verifies it against the live team."
        ]

    declared_set = set(declared)
    tokens = {
        stripped
        for phrase in _written_statuses(workflow)
        for token in re.split(r"->|,", phrase)
        if (stripped := token.strip())
    }

    errors: list[str] = [
        f"status {token!r} is used but not in linear.statuses {sorted(declared_set)}"
        for token in sorted(tokens)
        if token not in declared_set
    ]

    for band, owner in (linear.get("status_ownership") or {}).items():
        if not owner:
            errors.append(f"linear.status_ownership.{band} names no owner")

    return errors


def check_projections(workflow: dict, text: str) -> list[str]:
    """The prose and diagram are projections; they may not contradict the YAML.

    Deliberately a correspondence check, not a regeneration. The prose walkthrough is editorial
    English carrying judgement the YAML does not encode — generating it from the YAML would mean
    either losing that or pretending the YAML holds it. What *is* checkable is that neither
    projection names a step or gate the YAML does not have, and that neither omits one.
    """
    errors: list[str] = []
    ids = {s["id"] for s in workflow.get("steps") or [] if isinstance(s, dict) and "id" in s}
    gates = set(workflow.get("gates") or {})

    mermaid = re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL)
    if not mermaid:
        errors.append("no mermaid block — §4 is declared a projection of the YAML but is absent")
    else:
        diagram = mermaid[0]
        for sid in sorted(ids):
            if not re.search(rf"\b{re.escape(sid)}\b", diagram):
                errors.append(f"diagram omits step {sid!r}, which the YAML defines")
        for gate in sorted(GATE_TOKEN_RE.findall(diagram)):
            if gate not in gates:
                errors.append(f"diagram names gate {gate}, which the YAML does not define")

    # Prose is looser: it must not invent a gate, but is not required to mention every step.
    prose_match = re.search(r"## 3\. Prose walkthrough.*?(?=\n## )", text, re.DOTALL)
    if prose_match:
        for gate in sorted(set(GATE_TOKEN_RE.findall(prose_match.group(0)))):
            if gate not in gates:
                errors.append(f"prose names gate {gate}, which the YAML does not define")

    header = VERSION_HEADER_RE.search(text)
    if header and str(workflow.get("version")) != header.group(1):
        errors.append(
            f"header says v{header.group(1)} but the YAML says version {workflow.get('version')!r} — "
            "one of them is stale"
        )

    return errors


class LinearUnavailable(Exception):
    """The Linear client is absent or unreachable, so the live check could not run."""


def check_linear_live(workflow: dict) -> list[str]:
    """Verify the declared team, project and status set against the live workspace.

    Needs network and Linear auth, so never part of `task check`: CI has no credentials, and
    docs/contracts/consumes.md keeps anything that needs them out of that target.

    The project check earns its place. v2.0.1 pinned a project that did not exist — the status
    set had been verified against the live team and the project name beside it had not, and the
    mismatch only surfaced when someone tried to file an issue against it.

    Raises LinearUnavailable when the client is missing or unreachable. That is a *skip*, not a
    failure: the Linear CLI is optional tooling, and failing `task verify` because a machine
    lacks an optional dependency punishes the wrong thing. A Linear that answers and disagrees
    is a hard failure.
    """
    linear = workflow.get("linear") or {}
    team = linear.get("team")
    project = linear.get("project")
    declared = set(linear.get("statuses") or [])
    if not team:
        return ["linear.team is not declared, so the live workspace cannot be resolved"]
    if not declared:
        return ["linear.statuses is not declared, so there is nothing to verify against the live team"]

    query = "query($t:String!){ team(id:$t){ states{ nodes{ name } } projects{ nodes{ name } } } }"
    try:
        result = subprocess.run(  # noqa: S603
            ["linear", "api", "--query", query, "--var", f"t={team}"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        msg = f"Linear client unavailable ({exc})"
        raise LinearUnavailable(msg) from exc

    if result.returncode != 0:
        msg = f"Linear query failed: {result.stderr.strip() or result.stdout.strip()}"
        raise LinearUnavailable(msg)

    try:
        payload = json.loads(result.stdout)["data"]["team"]
        live = {n["name"] for n in payload["states"]["nodes"]}
        projects = {n["name"] for n in payload["projects"]["nodes"]}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        msg = f"could not parse the Linear response ({exc})"
        raise LinearUnavailable(msg) from exc

    errors = [f"linear.statuses declares {s!r}, which team {team} no longer has" for s in sorted(declared - live)]
    errors += [f"team {team} has status {s!r}, which linear.statuses does not declare" for s in sorted(live - declared)]
    if project and project not in projects:
        errors.append(f"linear.project is {project!r}, which team {team} does not have")
    return errors


def lint(path: Path, with_linear: bool) -> int:
    try:
        workflow, text = load(path)
    except WorkflowError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    errors = check_structure(workflow)
    linear_scope = ""
    # The later checks index into the same structures, so a malformed block would only produce
    # noise on top of the real failure.
    if not errors:
        errors += check_statuses(workflow)
        errors += check_projections(workflow, text)
        if with_linear:
            try:
                errors += check_linear_live(workflow)
                linear_scope = ", live Linear"
            except LinearUnavailable as exc:
                # Skipped, and said out loud. Silence here would read as "the live check passed".
                print(f"SKIPPED live Linear check: {exc}", file=sys.stderr)
                linear_scope = ", live Linear SKIPPED"

    if errors:
        print(f"{path}: {len(errors)} problem(s)", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    steps = len(workflow.get("steps") or [])
    gates = len(workflow.get("gates") or {})
    print(
        f"{path} v{workflow.get('version')} ok — {steps} steps, {gates} gates "
        f"(structure, statuses, projections{linear_scope})"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse and validate WORKFLOW.md's executable block")
    parser.add_argument("command", choices=["lint", "show"], help="lint the block, or dump it as JSON")
    parser.add_argument("--file", type=Path, default=WORKFLOW_MD, help="path to WORKFLOW.md")
    parser.add_argument(
        "--linear",
        action="store_true",
        help="also verify linear.statuses against the live team (needs network and Linear auth)",
    )
    args = parser.parse_args()

    if args.command == "show":
        try:
            workflow, _ = load(args.file)
        except WorkflowError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(workflow, indent=2, default=str))
        return 0

    return lint(args.file, with_linear=args.linear)


if __name__ == "__main__":
    raise SystemExit(main())
