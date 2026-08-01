#!/usr/bin/env python3
"""
Parse an OpenSpec change's tasks.md and emit individual work-order files.

Each work-order is a self-contained markdown file that an Orca agent
can receive as its prompt. Work-orders are written to work_orders/<change>/.

Usage:
    python scripts/dispatch_tasks.py --change <change-name>

The script does NOT create Orca worktrees directly. It prints the Orca CLI
command for each work-order (flags verified against onorca.dev/docs/cli/reference
and the installed binary, 2026-07-31). Requires `orca serve` or the Orca app
to be running.
"""

import argparse
import re
import sys
from pathlib import Path


def parse_tasks(tasks_md: Path) -> list[dict]:
    """Parse tasks.md into a list of {id, title, body} dicts.

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

    return tasks


def emit_work_orders(tasks: list[dict], change: str, output_dir: Path) -> list[Path]:
    """Write one work-order file per task."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for i, task in enumerate(tasks, 1):
        task_id = f"task-{i:03d}"
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
    args = parser.parse_args()

    tasks_md = Path("openspec/changes") / args.change / "tasks.md"
    tasks = parse_tasks(tasks_md)

    if not tasks:
        print(f"No tasks found in {tasks_md}")
        sys.exit(0)

    output_dir = Path(args.output) / args.change
    paths = emit_work_orders(tasks, args.change, output_dir)

    print(f"Emitted {len(paths)} work-orders to {output_dir}/")
    print()
    repo_selector = args.repo or f"path:{Path.cwd()}"

    print("Orca dispatch commands (requires `orca serve` or the Orca app running):")
    print()
    for p in paths:
        print(
            f"  orca worktree create --name {p.stem} --repo {repo_selector}"
            f' --agent {args.agent} --prompt "$(cat {p})" --setup run --json'
        )
        print()

    print("After all worktrees complete, run:")
    print(f"  task collect CHANGE={args.change}")
    print(f"  task sync-docs CHANGE={args.change}")


if __name__ == "__main__":
    main()
