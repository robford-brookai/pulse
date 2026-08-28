#!/usr/bin/env python3
"""
Parse an OpenSpec change's tasks.md and emit individual work-order files.

Each work-order is a self-contained markdown file that an Orca agent
can receive as its prompt. Work-orders are written to work_orders/<change>/.

Usage:
    python scripts/dispatch_tasks.py --change <change-name>

The script does NOT create Orca worktrees directly. It prints the Orca CLI
command for each releasable work-order (flags verified against
onorca.dev/docs/cli/reference and the installed binary, 2026-07-31). Requires
`orca serve` or the Orca app to be running.

Release is gated three ways, per WORKFLOW.md v2 and docs/process/dispatch-template.md §4:

* **Lane.** `destructive_ops` and `operational_discovery` declare
  `excluded_steps: [dispatch, ...]`. Those tasks get NO work-order file — they run on the
  Open Engine queue as operator runbooks, and a file that exists is a file Orca can claim.
* **Wave.** A task releases only once every task it depends on is checked off. Waves are
  *derived* from the dependency graph, never trusted from a hand-written label; a declared
  `wave:` that disagrees with the graph is an error, because the label is the thing that rots.
* **Serial.** A `parallel: no` task releases alone — nothing else from the change in flight.

Annotations are read from the task's title and body, in the
docs/process/dispatch-template.md §2 form, extended with the WORKFLOW.md v2 lane vocabulary:

    - [ ] 2.1 Do the thing  [model: opus | deps: 1.3 | lane: repo_change | wave: 1]
          `serial: catalog_generated_surfaces` — why it cannot share a wave.

Every key is optional. A task with no annotations is a plain `repo_change`, wave 0,
parallel task — which is what makes this backward compatible with an unannotated tasks.md.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# docs/process/dispatch-template.md §2. `lane` is the WORKFLOW.md v2 addition.
DEFAULTS = {
    "model": "sonnet",
    "max": "opus",
    "parallel": "yes",
    "lane": "repo_change",
}

# WORKFLOW.md v2 `lanes`. Both non-default lanes exclude the dispatch step, so neither
# may produce a work-order file. Their runner is the Open Engine queue (team CCC).
EXCLUDED_LANES = {"destructive_ops", "operational_discovery"}
KNOWN_LANES = {"repo_change"} | EXCLUDED_LANES

ANNOTATION_RE = re.compile(r"\[([^\[\]]*?:[^\[\]]*?)\]")
SERIAL_RE = re.compile(r"serial:\s*([^\n`]+)")
# Leading "1.2" / "10.1" in a task title — the stable key deps refer to.
TASK_KEY_RE = re.compile(r"^(\d+\.\d+)\b")


class DispatchError(Exception):
    """A tasks.md defect that must stop dispatch rather than be worked around."""


# --- G_HARDENING -------------------------------------------------------------------------------
#
# WORKFLOW.md declares `G_HARDENING blocks: [execute]` and nothing enforced it. Two worktrees were
# launched straight through it before anyone noticed, and the audit that followed (DNA-777) found
# Orca spawning every agent with --dangerously-skip-permissions. A gate that only exists in prose
# is not a gate.

HARDENING_RECEIPT = Path(".orca/hardening-receipt.json")
ADOPTION_GATE = ("H1", "H2", "H3", "H4")  # H5 is standing policy, H6-H7 per-session discipline
RECEIPT_MAX_AGE_DAYS = 90
# Every one of these is a real default shipped for some agent in Orca's agentDefaultArgs.
BYPASS_TOKENS = (
    "dangerously",
    "yolo",
    "auto-approve",
    "bypass",
    "--unrestricted",
    "trust-all-tools",
    "yes-always",
    "allow-all",
)
ORCA_PROFILE = Path.home() / "Library/Application Support/Orca/profiles/local-default/orca-data.json"


def live_agent_bypass(agent: str, profile: Path | None = None) -> str | None:
    """The bypass argument Orca will actually launch `agent` with, if any.

    Checked live rather than trusted from the receipt, because a receipt records what was true
    when someone looked. This is the setting that silently re-arms every worktree, so it is worth
    reading at the moment of dispatch. Returns None when it cannot be read at all — absence of
    the profile is not evidence of safety, but neither is it grounds to block a machine that
    simply stores its config elsewhere.
    """
    # Resolved at call time, not bound as a default: a default argument freezes the module
    # attribute at import, which makes ORCA_PROFILE impossible to override.
    profile = profile or ORCA_PROFILE
    try:
        settings = json.loads(profile.read_text()).get("settings", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    args = (settings.get("agentDefaultArgs") or {}).get(agent)
    if not isinstance(args, str):
        return None
    return args if any(token in args for token in BYPASS_TOKENS) else None


def hardening_problems(agent: str, today: date, receipt_path: Path | None = None) -> list[str]:
    """Why G_HARDENING does not currently permit dispatch. Empty means it does."""
    receipt_path = receipt_path or HARDENING_RECEIPT
    problems: list[str] = []

    bypass = live_agent_bypass(agent)
    if bypass:
        problems.append(
            f"H4 live: Orca launches `{agent}` with {bypass!r}. Every worktree this releases would "
            "run unattended with permissions off. Fix agentDefaultArgs before dispatching."
        )

    try:
        receipt = json.loads(receipt_path.read_text())
    except FileNotFoundError:
        problems.append(
            f"no G_HARDENING receipt at {receipt_path}. Run the Appendix A checklist and record it — "
            "the gate is per-workstation, so the file is gitignored and not inherited from anyone else."
        )
        return problems
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"{receipt_path} is unreadable ({exc})")
        return problems

    audited = receipt.get("audited")
    try:
        age = (today - date.fromisoformat(str(audited))).days
    except (TypeError, ValueError):
        problems.append(f"receipt has no usable `audited` date (got {audited!r})")
    else:
        if age > RECEIPT_MAX_AGE_DAYS:
            problems.append(f"receipt is {age} days old (limit {RECEIPT_MAX_AGE_DAYS}); re-run the checklist")

    problems += _adoption_gate_problems(receipt, today)
    return problems


def _adoption_gate_problems(receipt: dict, today: date) -> list[str]:
    """H1-H4 must each pass, or carry a justified, unexpired exception.

    `accepted` exists because some checks cannot pass without giving up a feature that is
    genuinely wanted — H2 asks for a localhost-only daemon, and the phone client needs the
    daemon reachable. The alternative was routing those through `--skip-hardening` on every
    dispatch, which turns a deliberate exception into background noise nobody reads. An
    exception here has to name a reason and a date it gets looked at again.
    """
    checks = receipt.get("checks") or {}
    exceptions = receipt.get("exceptions") or {}
    issue = receipt.get("issue", "the receipt issue")
    problems: list[str] = []
    unmet: list[str] = []

    for check in ADOPTION_GATE:
        state = checks.get(check, "missing")
        if state == "pass":
            continue
        if state != "accepted":
            unmet.append(f"{check}={state}")
            continue

        exception = exceptions.get(check) or {}
        if not exception.get("justification"):
            problems.append(f"{check} is 'accepted' but records no justification — say why, or fix it")
            continue
        try:
            review_by = date.fromisoformat(str(exception.get("review_by")))
        except (TypeError, ValueError):
            problems.append(f"{check} is 'accepted' but has no usable `review_by` date — an exception must expire")
            continue
        if review_by < today:
            problems.append(f"{check} exception lapsed on {review_by} and needs re-reviewing. See {issue}")

    if unmet:
        problems.append(f"adoption gate not met: {', '.join(unmet)}. See {issue}")
    return problems


def _parse_annotations(text: str) -> dict:
    """Pull `key: value` pairs out of every `[...]` block in the task text.

    Only bracket groups containing a colon are considered, so ordinary markdown links and
    inline code survive untouched.
    """
    found: dict[str, str] = {}
    for block in ANNOTATION_RE.findall(text):
        for field in block.split("|"):
            if ":" not in field:
                continue
            key, _, value = field.partition(":")
            key, value = key.strip().lower(), value.strip().strip("`")
            if key and value:
                found[key] = value
    return found


def _parse_deps(raw: str) -> list[str]:
    if raw.lower() in {"none", "-", "—", ""}:
        return []
    return [d.strip().strip("`") for d in raw.split(",") if d.strip()]


def parse_tasks(tasks_md: Path) -> list[dict]:
    """Parse tasks.md into a list of task dicts.

    Expects GitHub-flavored markdown task lists:
        - [ ] Task title
          Description lines...

    Also handles milestone headers (## Milestone N).
    """
    if not tasks_md.exists():
        print(f"Error: {tasks_md} not found", file=sys.stderr)
        sys.exit(1)

    content = tasks_md.read_text()
    tasks = []
    current_milestone = "default"
    current_task = None

    for line in content.splitlines():
        # Milestone header
        milestone_match = re.match(r"^##\s+(.+)$", line)
        if milestone_match:
            current_milestone = milestone_match.group(1).strip()
            continue

        # Task line
        task_match = re.match(r"^-\s+\[[ xX]\]\s+(.+)$", line)
        if task_match:
            # Save previous task
            if current_task:
                tasks.append(current_task)

            current_task = {
                "milestone": current_milestone,
                "title": task_match.group(1).strip(),
                "body": [],
                "done": "[x" in line or "[X" in line,
            }
        elif current_task and line.strip() and not line.startswith("#"):
            current_task["body"].append(line)

    if current_task:
        tasks.append(current_task)

    for i, task in enumerate(tasks, 1):
        _annotate(task, index=i)

    return tasks


def _annotate(task: dict, index: int) -> None:
    """Attach routing metadata to a parsed task, in place."""
    text = "\n".join([task["title"], *task["body"]])
    declared = _parse_annotations(text)

    key_match = TASK_KEY_RE.match(task["title"])
    task["key"] = key_match.group(1) if key_match else f"task-{index:03d}"
    task["task_id"] = f"task-{index:03d}"

    task["declared"] = declared
    task["model"] = declared.get("model", DEFAULTS["model"])
    task["max_tier"] = declared.get("max", DEFAULTS["max"])
    task["lane"] = declared.get("lane", DEFAULTS["lane"])
    task["deps"] = _parse_deps(declared.get("deps", ""))
    task["declared_wave"] = declared.get("wave")

    serial_match = SERIAL_RE.search(text)
    task["serial_reason"] = serial_match.group(1).strip() if serial_match else None
    # Either spelling marks the serial lane: the template's `parallel: no`, or WORKFLOW v2's
    # `serial: <justification>`.
    task["parallel"] = declared.get("parallel", DEFAULTS["parallel"]).lower() != "no"
    if task["serial_reason"]:
        task["parallel"] = False

    task["dispatchable"] = task["lane"] not in EXCLUDED_LANES


def validate(tasks: list[dict]) -> None:
    """Fail on the tasks.md defects G_MECE is supposed to catch.

    Raising here is the point. The failure this replaces was silent: dispatch emitted a work
    order for an MSK teardown because nothing ever asked what lane it was in.
    """
    by_key = {t["key"]: t for t in tasks}
    errors: list[str] = []

    for task in tasks:
        label = f"{task['task_id']} ({task['key']})"

        if task["lane"] not in KNOWN_LANES:
            errors.append(f"{label}: unknown lane {task['lane']!r}, expected one of {sorted(KNOWN_LANES)}")

        # G_MECE: deps_reference_existing_tasks
        for dep in task["deps"]:
            if dep not in by_key:
                errors.append(f"{label}: deps references {dep!r}, which is not a task in this file")

        # G_MECE: serial_flags_justified
        if not task["parallel"] and not task["serial_reason"]:
            errors.append(
                f"{label}: is serial (parallel: no) but states no reason. "
                "Add `serial: <why>` — almost always a generated surface or a shared root file."
            )

    if errors:
        raise DispatchError("tasks.md is not dispatchable:\n  - " + "\n  - ".join(errors))

    # Surfaces a dependency cycle here rather than letting it escape into the caller's own
    # compute_waves call, where it would abort mid-report with a traceback.
    compute_waves(tasks)

    # A declared wave is a human release grouping, coarser than dependency depth — one wave may
    # hold an internally ordered chain, and `2a`/`2b`/`2c` deliberately split one depth across
    # several. So the cross-check is monotonicity, not equality: nothing may be scheduled into a
    # wave earlier than something it depends on. That still catches the label going stale, which
    # is the only failure a label can actually have. Run after the dep check above, which
    # guarantees every reference resolves.
    inversions = [
        f"{t['task_id']} ({t['key']}) is wave {t['declared_wave']!r} "
        f"but depends on {dep} in later wave {by_key[dep]['declared_wave']!r}"
        for t in tasks
        if t["declared_wave"] is not None
        for dep in t["deps"]
        if by_key[dep]["declared_wave"] is not None
        and _wave_rank(by_key[dep]["declared_wave"]) > _wave_rank(t["declared_wave"])
    ]
    if inversions:
        raise DispatchError(
            "declared waves contradict the dependency graph:\n  - "
            + "\n  - ".join(inversions)
            + "\n\nThe graph is the truth; fix the label or fix the deps."
        )


def _wave_rank(value) -> tuple[float, str]:
    """Order wave labels: `0` < `1` < `2a` < `2b` < `3`, and anything unnumbered sorts last.

    Unnumbered labels are terminal groupings like `post-merge`, which by construction come after
    every numbered wave.
    """
    text = str(value).strip()
    number = re.match(r"(\d+)", text)
    if not number:
        return (float("inf"), text)
    return (float(number.group(1)), text[number.end() :])


def compute_waves(tasks: list[dict]) -> dict[str, int]:
    """Longest-path depth of each task over the dependency graph.

    Wave 0 is everything with no dependencies. A cycle is a hard error — Orca would otherwise
    deadlock waiting for a task that can never release.
    """
    by_key = {t["key"]: t for t in tasks}
    depth: dict[str, int] = {}
    visiting: set[str] = set()

    def resolve(key: str, trail: list[str]) -> int:
        if key in depth:
            return depth[key]
        if key in visiting:
            cycle = "dependency cycle: " + " -> ".join([*trail, key])
            raise DispatchError(cycle)
        visiting.add(key)
        deps = [d for d in by_key[key]["deps"] if d in by_key]
        depth[key] = 1 + max((resolve(d, [*trail, key]) for d in deps), default=-1)
        visiting.discard(key)
        return depth[key]

    for task in tasks:
        resolve(task["key"], [])
    return depth


def releasable(tasks: list[dict]) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    """Split dispatchable, unfinished tasks into (released now, held with reasons).

    A task releases when every task it depends on is checked off. A dependency on an
    out-of-lane task holds it just the same — that work is real, it simply happens on another
    queue, and pretending otherwise is how a teardown ends up in a worktree.

    If any releasable task is serial, only that task releases: the serial lane runs alone.
    """
    by_key = {t["key"]: t for t in tasks}
    ready: list[dict] = []
    held: list[tuple[dict, list[str]]] = []

    for task in tasks:
        if task["done"] or not task["dispatchable"]:
            continue
        blockers = []
        for dep in task["deps"]:
            dep_task = by_key.get(dep)
            if dep_task is None or dep_task["done"]:
                continue
            where = "" if dep_task["dispatchable"] else f" [{dep_task['lane']}, other queue]"
            blockers.append(f"{dep}{where}")
        if blockers:
            held.append((task, blockers))
        else:
            ready.append(task)

    serial = [t for t in ready if not t["parallel"]]
    if serial:
        first = serial[0]
        held = [(t, ["serial lane: " + first["key"] + " runs alone"]) for t in ready if t is not first] + held
        ready = [first]

    return ready, held


def emit_work_orders(tasks: list[dict], change: str, output_dir: Path) -> list[Path]:
    """Write one work-order file per dispatchable task.

    Out-of-lane tasks are skipped. Task IDs stay positional, so skipping one does not renumber
    the rest — a work order's name is a stable handle people paste into issues.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for i, task in enumerate(tasks, 1):
        # Tolerate dicts built by hand (tests, ad-hoc callers) that never went through parse_tasks.
        if not task.get("dispatchable", True):
            continue
        task_id = task.get("task_id", f"task-{i:03d}")
        filename = f"{task_id}.md"
        filepath = output_dir / filename

        lines = [
            f"# Work Order: {task['title']}",
            "",
            f"**Change**: {change}",
            f"**Milestone**: {task['milestone']}",
            f"**Task ID**: {task_id}",
            "",
            "## Objective",
            "",
            task["title"],
            "",
        ]

        if task["body"]:
            lines += ["## Context", ""]
            lines += task["body"]
            lines.append("")

        # Only for annotated tasks, so an unannotated tasks.md emits exactly what it always did.
        if task.get("declared"):
            lines += [
                "## Routing",
                "",
                f"- **Model**: {task['model']} (escalation ceiling: {task['max_tier']})",
                f"- **Lane**: {task['lane']}",
                f"- **Depends on**: {', '.join(task['deps']) if task['deps'] else 'nothing'}",
                f"- **Parallel**: {'yes' if task['parallel'] else 'no — serial lane, runs alone'}",
            ]
            if task["serial_reason"]:
                lines.append(f"- **Serial because**: {task['serial_reason']}")
            lines.append("")

        lines += [
            "## Requirements",
            "",
            "1. Read the spec file: `openspec/changes/" + change + "/specs/` for requirements and scenarios.",
            "2. Write tests first (red-green-refactor).",
            "3. Implement the minimum to satisfy the spec scenario.",
            "4. Run `task lint && task test` before finishing.",
            "5. Write `HANDOFF.md` in the worktree root with any spec-relevant updates.",
            "",
            "## Agent Instructions",
            "",
            '- Call `orient("' + task["title"] + '")` via OpenLore MCP if available.',
            "- Do NOT edit files in `openspec/`.",
            "- One commit per task.",
            "- If the spec is wrong, write to HANDOFF.md and stop.",
            "",
        ]

        filepath.write_text("\n".join(lines))
        paths.append(filepath)

    return paths


def _enforce_hardening(args) -> None:
    """G_HARDENING blocks execute, and dispatch is what makes execute possible — so this is where
    it has to bite. Work orders are still written; only the release is withheld, because the plan
    is useful to read while the gate is being closed."""
    hardening = hardening_problems(args.agent, date.today())
    if hardening and not args.skip_hardening:
        print(f"G_HARDENING blocks dispatch for `{args.change}`:", file=sys.stderr)
        for problem in hardening:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nAppendix A of docs/process/dispatch-template.md defines the checklist. "
            "Re-run it, update .orca/hardening-receipt.json, and dispatch again.\n"
            "--skip-hardening releases anyway and says so — for a deliberate, receipted exception.",
            file=sys.stderr,
        )
        sys.exit(1)
    if hardening:
        print(f"WARNING: releasing with G_HARDENING unmet ({len(hardening)} problem(s)):", file=sys.stderr)
        for problem in hardening:
            print(f"  - {problem}", file=sys.stderr)
        print("", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Dispatch OpenSpec tasks as Orca work-orders")
    parser.add_argument("--change", required=True, help="OpenSpec change name")
    parser.add_argument(
        "--output",
        default="work_orders",
        help="Output directory for work-order files (default: work_orders)",
    )
    parser.add_argument(
        "--agent",
        default="claude",
        help="Orca agent id to launch in each worktree (default: claude)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help=(
            "Orca repo selector (id:<id>, name:<name>, or path:<path>). "
            "Defaults to path:<cwd>. Orca only infers the repo when called from "
            "inside an Orca-managed worktree, so the selector is emitted explicitly."
        ),
    )
    parser.add_argument(
        "--skip-hardening",
        action="store_true",
        help=(
            "Release even though G_HARDENING is not satisfied. Prints what was skipped. "
            "For a deliberate, receipted exception — not for getting past a red gate."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help=(
            "Run the mechanical G_MECE checks and stop — no hardening gate, no work-order "
            "emission. The replan path: an agent validates a tasks.md amendment before opening "
            "the PR. No gate here ever needs a human comment."
        ),
    )
    parser.add_argument(
        "--all-waves",
        action="store_true",
        help=(
            "Print Orca commands for every dispatchable task, ignoring the wave and serial "
            "gates. Escape hatch for inspecting the full plan — not the normal path."
        ),
    )
    args = parser.parse_args()

    tasks_md = Path("openspec/changes") / args.change / "tasks.md"
    tasks = parse_tasks(tasks_md)

    if not tasks:
        print(f"No tasks found in {tasks_md}")
        sys.exit(0)

    try:
        validate(tasks)
    except DispatchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.validate_only:
        print(f"G_MECE mechanical checks pass for `{args.change}` ({len(tasks)} tasks).")
        print(
            "Next steps (pre-filled):\n"
            f"  openspec validate {args.change}        # or `task replan CHANGE={args.change}`, which ran both\n"
            "  open the amendment PR — review-and-merge is the only human step\n"
            f"  task linear:sync CHANGE={args.change}  # after the PR merges\n"
            f"  task dispatch CHANGE={args.change}"
        )
        sys.exit(0)

    _enforce_hardening(args)

    output_dir = Path(args.output) / args.change
    paths = emit_work_orders(tasks, args.change, output_dir)

    ready, held = releasable(tasks)
    waves = compute_waves(tasks)
    pending = [t for t in tasks if t["dispatchable"] and not t["done"]]
    selected = pending if args.all_waves else ready

    print(f"Emitted {len(paths)} work-orders to {output_dir}/")
    _report_out_of_lane([t for t in tasks if not t["dispatchable"]])
    print()

    if not selected:
        print("Nothing to release.")
        _report_held(held, waves, heading="Held:")
        print()
        print("Check off a task in tasks.md when its commit merges — that is what opens the next wave.")
        return

    if not args.all_waves and len(ready) == 1 and not ready[0]["parallel"]:
        print(f"Serial lane: releasing {ready[0]['key']} alone. Nothing else from this change may be in flight.")
        print()

    print(
        f"Releasing {len(selected)} of {len(pending)} dispatchable tasks "
        "(requires `orca serve` or the Orca app running):"
    )
    print()
    _report_commands(selected, waves, output_dir, args.repo or f"path:{Path.cwd()}", args.agent)

    if not args.all_waves:
        _report_held(held, waves, heading=f"Held until their dependencies are checked off ({len(held)}):")

    print("After all worktrees complete, run:")
    print(f"  task collect CHANGE={args.change}")
    print(f"  task sync-docs CHANGE={args.change}")


def _report_out_of_lane(out_of_lane: list[dict]) -> None:
    if not out_of_lane:
        return
    print()
    print(f"Out of lane — no work order written, runner is the Open Engine queue ({len(out_of_lane)}):")
    for task in out_of_lane:
        print(f"  {task['key']:<6} [{task['lane']}] {task['title'][:72]}")
    print("  These need a G_APPROVAL comment and an operator. They never enter a worktree.")


def _report_held(held: list[tuple[dict, list[str]]], waves: dict[str, int], heading: str) -> None:
    if not held:
        return
    print(heading)
    for task, blockers in held:
        print(f"  {task['key']:<6} wave {waves[task['key']]}  blocked by {', '.join(blockers)}")
    print()


def _report_commands(
    selected: list[dict], waves: dict[str, int], output_dir: Path, repo_selector: str, agent: str
) -> None:
    for task in selected:
        p = output_dir / f"{task['task_id']}.md"
        print(f"  # {task['key']} — wave {waves[task['key']]} — model {task['model']}")
        print(
            f"  orca worktree create --name {p.stem} --repo {repo_selector}"
            f' --agent {agent} --prompt "$(cat {p})" --setup run --json'
        )
        print()


if __name__ == "__main__":
    main()
