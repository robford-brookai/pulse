#!/usr/bin/env python3
"""Flip tasks.md checkboxes for tasks whose PR has merged, from the branch's own history.

A checked box is a merged task — dispatch reads that state to release the next wave, so the flip
is load-bearing. The first real change hand-typed 25 `chore: check off` commits to carry it. This
target derives the flips instead: merge subjects already name their task id per the
`(X.Y[, TEAM-n])` convention (the dispatch template writes the id into the work-order title, and
the PR title inherits it), so the history is the record and the checkbox is its projection.

Usage:
    python scripts/checkoff_tasks.py --change <id>            # flip in the working tree, report
    python scripts/checkoff_tasks.py --change <id> --commit   # also commit tasks.md alone

The scan starts at the commit that added the change's tasks.md, so other changes' history never
reaches the match. A subject id that tasks.md does not know is a hard error and nothing is
written: a silent skip would hide either a typoed subject or a task deleted from the plan.

The commit this writes is main_access-eligible by construction — checkbox state only, one file,
and the message names the merges it records and says why it bypassed review. `task check` green
before pushing remains the operator's condition, as it is for every direct push.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

# `(6.7)`, `(8.2, DNA-774)` — the id must be the parenthesised subject tag, so a bare `3.1 ...`
# prefix or a prose mention never matches. Checkoff's own commit subjects carry no parens.
SUBJECT_ID_RE = re.compile(r"\((\d+\.\d+)(?:,\s*[A-Z]+-\d+)?\)")
TASK_LINE_RE = re.compile(r"^(-\s+\[)([ xX])(\]\s+)(\d+\.\d+)\b")


def subject_task_ids(subject: str) -> set[str]:
    """Task ids a commit subject claims, per the `(X.Y[, TEAM-n])` convention."""
    return set(SUBJECT_ID_RE.findall(subject))


def flip(content: str, ids: set[str]) -> tuple[str, list[str], list[str]]:
    """Check the boxes for `ids`. Returns (new content, flipped ids, unknown ids).

    Only the checkbox character changes — an already-checked id is a no-op, which is what makes
    rerunning after every merge session safe.
    """
    known: set[str] = set()
    flipped: list[str] = []
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        match = TASK_LINE_RE.match(line)
        if not match:
            continue
        prefix, state, suffix, key = match.groups()
        known.add(key)
        if key in ids and state == " ":
            lines[i] = TASK_LINE_RE.sub(f"{prefix}x{suffix}{key}", line, count=1)
            flipped.append(key)
    return "".join(lines), flipped, sorted(ids - known)


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    return result.stdout.strip()


def sources_for_commits(shas: list[str], cwd: Path | None = None) -> dict[str, list[str]]:
    """Task id -> source lines, for explicitly named commits only.

    The coordinator path: it just watched a specific PR merge and passes that SHA, so nothing
    else in history is consulted — no scan, no scoping question, no cross-change ambiguity.
    """
    sources: dict[str, list[str]] = {}
    for sha in shas:
        line = _git("log", "-1", "--format=%h%x09%s", sha, cwd=cwd)
        short, _, subject = line.partition("\t")
        for task_id in subject_task_ids(subject):
            sources.setdefault(task_id, []).append(f"{short} {subject}")
    return sources


def merged_ids(tasks_md: Path) -> dict[str, list[str]]:
    """Task id -> the `<sha> <subject>` lines that recorded its merge.

    Scoped to history since tasks.md first appeared, so sibling changes' subjects — which reuse
    the same X.Y numbering — never leak into the match.
    """
    added = _git("log", "--diff-filter=A", "--follow", "--format=%H", "--reverse", "--", str(tasks_md))
    first = added.splitlines()[0] if added else ""
    log_range = f"{first}..HEAD" if first else "HEAD"
    sources: dict[str, list[str]] = {}
    for line in _git("log", "--format=%h%x09%s", log_range).splitlines():
        sha, _, subject = line.partition("\t")
        for task_id in subject_task_ids(subject):
            sources.setdefault(task_id, []).append(f"{sha} {subject}")
    return sources


def next_steps(change: str) -> str:
    """The pre-filled follow-up, so a coordinator agent constructs no command itself."""
    return (
        "Next steps (pre-filled):\n"
        "  task check                                 # main_access condition before pushing\n"
        f"  task dispatch CHANGE={change}             # the flip may have opened a wave\n"
        f"  task collect CHANGE={change}              # if that flip completed the wave"
    )


def commit_message(flipped: list[str], sources: dict[str, list[str]]) -> str:
    lines = [f"chore: check off {', '.join(flipped)} — recorded from merged history", ""]
    lines += ["Mechanical state update per main_access: checkbox flips only, derived from:"]
    lines += sorted({src for task_id in flipped for src in sources.get(task_id, [])})
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Flip tasks.md checkboxes for merged tasks")
    parser.add_argument("--change", required=True, help="OpenSpec change id")
    parser.add_argument("--commit", action="store_true", help="commit the flip (tasks.md alone)")
    parser.add_argument(
        "--commit-sha",
        action="append",
        default=[],
        metavar="SHA",
        help="record only these merge commits (repeatable) instead of scanning history",
    )
    args = parser.parse_args()

    tasks_md = Path("openspec/changes") / args.change / "tasks.md"
    if not tasks_md.exists():
        print(f"Error: {tasks_md} not found", file=sys.stderr)
        return 1

    sources = sources_for_commits(args.commit_sha) if args.commit_sha else merged_ids(tasks_md)
    content = tasks_md.read_text()
    new_content, flipped, unknown = flip(content, set(sources))
    if unknown:
        print(
            f"Error: merged subjects reference task ids not in {tasks_md}: {', '.join(unknown)}. "
            "Nothing written — fix the subject convention or the plan first.",
            file=sys.stderr,
        )
        return 2

    if not flipped:
        print("Nothing to check off — every merged task is already recorded.")
        return 0

    tasks_md.write_text(new_content)
    message = commit_message(flipped, sources)
    print(f"Checked off: {', '.join(flipped)}")
    if args.commit:
        _git("add", str(tasks_md))
        _git("commit", "-m", message, "--", str(tasks_md))
        print("Committed (tasks.md alone).")
    else:
        print("Not committed. Suggested message:\n" + message)
    print(next_steps(args.change))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
