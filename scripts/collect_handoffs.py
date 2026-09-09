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
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: Section names templates/HANDOFF.md declares for spec-relevant content — the receipt this
#: script inlines into SUMMARY.md. Metadata fields (Worktree/Change/Task ID/Date) and "Notes for
#: Doc-Updater" are operational, not a receipt of what happened, and stay out of the summary.
_RECEIPT_HEADINGS = {
    "spec updates",
    "added requirements",
    "modified requirements",
    "removed requirements",
    "design drift",
    "new scenarios",
}

_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


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


def commits_ahead(wt: Path, base_ref: str) -> int | None:
    """How many commits this worktree has that the base does not.

    Returns None when that cannot be determined — the path is not a git worktree, or the base ref
    does not resolve. "Cannot tell" is deliberately not "zero": a worktree we cannot inspect must
    never be reported as delinquent on the strength of a failed git call.
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(wt), "rev-list", "--count", f"{base_ref}..HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def delinquent_worktrees(worktrees: list[Path], base_ref: str, repo_root: Path) -> list[tuple[Path, int]]:
    """Worktrees that committed work and left no receipt.

    `AGENTS.md` requires a HANDOFF.md from every worktree, and nothing enforced it. A worktree
    with commits and no HANDOFF looked exactly like one that had not started yet, so a task could
    finish, produce a commit, and vanish from the record without anyone noticing.

    The distinction is commits: no commits and no HANDOFF is simply not started. Commits and no
    HANDOFF is a missing receipt, and that is a failure.
    """
    delinquent = []
    for wt in worktrees:
        if wt.resolve() == repo_root.resolve() or (wt / "HANDOFF.md").exists():
            continue
        ahead = commits_ahead(wt, base_ref)
        if ahead:
            delinquent.append((wt, ahead))
    return delinquent


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


def _strip_comments(text: str) -> str:
    """Drop HTML comments (the template's placeholder prose) so an untouched section reads as
    empty rather than as content."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _sections(text: str) -> list[tuple[str | None, list[str]]]:
    """Split a HANDOFF body into (heading_line, body_lines) pairs, in document order. Content
    before the first heading is one section keyed on `None`."""
    result: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            result.append((heading, body))
            heading, body = line, []
        else:
            body.append(line)
    result.append((heading, body))
    return result


def extract_receipt_sections(handoff_text: str) -> str:
    """Pull the receipt-bearing sections out of one HANDOFF: Spec Updates (and its Added/
    Modified/Removed Requirements subsections), Design Drift, and New Scenarios — the section
    names templates/HANDOFF.md declares for spec-relevant content. Everything else (the metadata
    fields, Notes for Doc-Updater) is operational rather than a receipt of what happened, and is
    left out. A kept section whose body is empty once the template's own placeholder comment is
    stripped is omitted too, rather than emitted as a heading with nothing under it.
    """
    kept: list[str] = []
    for heading, body in _sections(handoff_text):
        if heading is None:
            continue
        title = heading.lstrip("#").strip().lower()
        if title not in _RECEIPT_HEADINGS:
            continue
        if not _strip_comments("\n".join(body)).strip():
            continue
        kept.append(heading)
        kept.extend(body)
    return "\n".join(kept).strip()


def summarize_handoffs(handoffs: list[Path], change: str) -> str:
    """Produce a summary for the doc-updater agent.

    Inlines each collected HANDOFF's receipt-bearing sections under a heading per task, rather
    than linking to the per-task file — that file lives under handoffs/<change>/ which .gitignore
    excludes everything but SUMMARY.md from, so a link to it is dangling in every fresh clone.
    SUMMARY.md is the only thing that survives; it has to carry the content itself.
    """
    if not handoffs:
        return f"No HANDOFF.md files found for change '{change}'."

    lines = [
        f"# Handoff Summary: {change}",
        "",
        f"Collected {len(handoffs)} handoff(s).",
        "",
    ]
    for h in handoffs:
        lines.append(f"## {h.stem}")
        lines.append("")
        content = extract_receipt_sections(h.read_text())
        lines.append(content if content else "_No spec-relevant updates recorded._")
        lines.append("")

    lines += [
        "## Doc-Updater Instructions",
        "",
        "1. For each spec-relevant update inlined above, edit the corresponding file in:",
        f"   `openspec/changes/{change}/specs/`",
        "2. Run `openspec validate " + change + "` to check format.",
        "3. Run `openlore drift` to check for new drift.",
        "4. Ignore implementation details — only apply plan-relevant changes.",
        "5. A `## Design Drift` section above means flag for human review.",
        "",
    ]

    return "\n".join(lines)


def find_ignored_links(text: str, base_dir: Path) -> list[str]:
    """Markdown link targets in `text` that git would refuse to track from `base_dir`.

    This is the dangling-receipt bug in a new outfit: a link into a gitignored path reads fine on
    the workstation that wrote it and breaks for anyone who clones fresh. summarize_handoffs no
    longer emits such links, but this is a backstop against a future regression reintroducing one
    — never emit a link this cannot vouch for.
    """
    offenders = []
    for target in _LINK_RE.findall(text):
        if "://" in target or target.startswith("mailto:"):
            continue
        candidate = Path(target) if Path(target).is_absolute() else base_dir / target
        try:
            result = subprocess.run(  # noqa: S603
                ["git", "-C", str(candidate.parent), "check-ignore", "--quiet", candidate.name],  # noqa: S607
                capture_output=True,
                check=False,
            )
        except OSError:
            continue
        if result.returncode == 0:
            offenders.append(target)
    return offenders


def summary_is_ignored(summary_path: Path) -> bool:
    """True when git would ignore the summary — the silent-loss failure this guards against.

    handoffs/<change>/SUMMARY.md is the tracked receipt record per WORKFLOW v2.1.0; a repo whose
    .gitignore still carries the old directory-level `handoffs/` pattern would take the write and
    then never commit it, and nothing downstream would notice the record was missing. Outside a
    git repo (cat9 collects into plain temp dirs) nothing can be ignored, so that is a pass.
    """
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(summary_path.parent), "check-ignore", "--quiet", summary_path.name],  # noqa: S607
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


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
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Ref a worktree's commits are counted against (default: origin/main)",
    )
    parser.add_argument(
        "--allow-missing-handoff",
        action="store_true",
        help=(
            "Report worktrees that committed work without a HANDOFF.md, but do not fail. "
            "For collecting mid-wave, when tasks are legitimately still running."
        ),
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
        offenders = find_ignored_links(summary, summary_path.parent)
        if offenders:
            print(
                f"\nError: the summary links to gitignored path(s): {', '.join(offenders)}. "
                "Inline the receipt content instead of linking to a file that will never be "
                "committed.",
                file=sys.stderr,
            )
            sys.exit(1)
        summary_path.write_text(summary)
        print(f"\nSummary written to {summary_path}")
        if summary_is_ignored(summary_path):
            print(
                f"\nError: {summary_path} is gitignored, so the receipt record cannot enter the "
                "repo. Narrow .gitignore to ignore handoffs/ CONTENTS (handoffs/**) and negate "
                "handoffs/*/SUMMARY.md — a directory-level pattern blocks the negation.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("Commit it with the change — SUMMARY.md is the tracked receipt record.")
    else:
        print("\nNo HANDOFF.md files found in any worktree.")

    delinquent = delinquent_worktrees(worktrees, args.base_ref, Path.cwd())
    if delinquent:
        print(
            f"\n{len(delinquent)} worktree(s) committed work and left no HANDOFF.md:",
            file=sys.stderr,
        )
        for wt, ahead in delinquent:
            print(f"  {wt.name}: {ahead} commit(s) ahead of {args.base_ref}, no receipt", file=sys.stderr)
        print(
            "\nAGENTS.md requires a HANDOFF.md from every worktree. Without one there is no record "
            "of what was done or whether the spec held, and the work is invisible to doc_update.\n"
            "Write the missing receipt, or pass --allow-missing-handoff if the task is still running.",
            file=sys.stderr,
        )
        if not args.allow_missing_handoff:
            sys.exit(1)

    if handoffs:
        print(f"\nNext step: task sync-docs CHANGE={args.change}")


if __name__ == "__main__":
    main()
