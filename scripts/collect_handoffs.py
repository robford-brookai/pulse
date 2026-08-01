#!/usr/bin/env python3
"""
Collect HANDOFF.md files from Orca worktrees into a central directory.

Orca creates worktrees as subdirectories. This script scans a configurable
directory for HANDOFF.md files and copies them to handoffs/<change>/.

Usage:
    python scripts/collect_handoffs.py --change <change-name>

Environment:
    ORCA_WORKTREES_DIR  Directory where Orca stores worktrees.
                        Defaults to the git worktree list output.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_worktrees() -> list[Path]:
    """Get worktree paths via git worktree list."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("Error: could not list git worktrees", file=sys.stderr)
        return []

    worktrees = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.split(" ", 1)[1])
            if path.exists():
                worktrees.append(path)

    return worktrees


def collect_handoffs(worktrees: list[Path], change: str, output_dir: Path) -> list[Path]:
    """Find HANDOFF.md in each worktree and copy to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    collected = []

    for wt in worktrees:
        handoff = wt / "HANDOFF.md"
        if not handoff.exists():
            continue

        # Name the file after the worktree directory
        name = wt.name
        dest = output_dir / f"{name}.md"
        shutil.copy2(handoff, dest)
        collected.append(dest)
        print(f"Collected: {dest}")

    return collected


def summarize_handoffs(handoffs: list[Path], change: str) -> str:
    """Produce a summary for the doc-updater agent."""
    if not handoffs:
        return f"No HANDOFF.md files found for change '{change}'."

    lines = [
        f"# Handoff Summary: {change}",
        "",
        f"Collected {len(handoffs)} handoff(s).",
        "",
        "## Files",
        "",
    ]
    for h in handoffs:
        lines.append(f"- [{h.name}]({h})")

    lines += [
        "",
        "## Doc-Updater Instructions",
        "",
        "1. Read each handoff file above.",
        "2. For each spec-relevant update, edit the corresponding file in:",
        f"   `openspec/changes/{change}/specs/`",
        "3. Run `openspec validate " + change + "` to check format.",
        "4. Run `openlore drift` to check for new drift.",
        "5. Ignore implementation details — only apply plan-relevant changes.",
        "6. If a handoff contains `## Design Drift`, flag for human review.",
        "",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Collect HANDOFF.md files from Orca worktrees")
    parser.add_argument("--change", required=True, help="OpenSpec change name")
    parser.add_argument(
        "--output",
        default="handoffs",
        help="Output directory for collected handoffs (default: handoffs)",
    )
    parser.add_argument(
        "--worktrees-dir",
        default=os.environ.get("ORCA_WORKTREES_DIR"),
        help="Directory containing Orca worktrees (default: auto-detect via git)",
    )
    args = parser.parse_args()

    if args.worktrees_dir:
        wt_root = Path(args.worktrees_dir)
        # Sorted: iterdir() order is filesystem-dependent, which would make the collected
        # file order and the SUMMARY.md listing differ between machines.
        worktrees = sorted(d for d in wt_root.iterdir() if d.is_dir()) if wt_root.exists() else []
    else:
        worktrees = find_worktrees()

    if not worktrees:
        print("No worktrees found. Are you running this from the repo root?")
        sys.exit(1)

    output_dir = Path(args.output) / args.change
    handoffs = collect_handoffs(worktrees, args.change, output_dir)

    if handoffs:
        summary = summarize_handoffs(handoffs, args.change)
        summary_path = Path(args.output) / args.change / "SUMMARY.md"
        summary_path.write_text(summary)
        print(f"\nSummary written to {summary_path}")
        print(f"\nNext step: task sync-docs CHANGE={args.change}")
    else:
        print("\nNo HANDOFF.md files found in any worktree.")


if __name__ == "__main__":
    main()
