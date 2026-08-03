"""Every alembic tree in the repo has one head and no revision id used twice.

Parallel work is what breaks this. Tasks 4.1 and 4.4 ran in separate worktrees off the same
base and each added a migration numbered `0002` with `down_revision = "0001"`. Nothing caught
it: the filenames differed so git saw no conflict, each branch was internally consistent so
both PRs went green, and alembic does not treat a duplicate revision id as an error —
`RevisionMap._revision_map` calls `util.warn("Revision 0002 is present more than once")` and
then overwrites the first entry with the second. That warning is a plain `UserWarning`, and
this repo's `filterwarnings` only escalates `ResourceWarning` and
`PytestUnraisableExceptionWarning`, so it would have scrolled past in CI output.

Had both merged, `conftest.py`'s `command.upgrade(cfg, "head")` would have applied only one of
the two migrations, and the loser's tests would have failed against a schema missing its
objects — reading as broken tests rather than as a collision.

This is a repo-level `test_*.py` rather than a `tests/scaffold/cat*` gate on purpose:
`python_files = ["test_*.py", "cat[0-9]_*.py"]` matches a single digit, so a `cat10_` file
would be collected by nothing and pass silently forever.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every alembic root in the repo, discovered rather than listed, so a new package's tree is
#: covered the moment it ships an alembic.ini instead of whenever someone remembers this file.
INFRA_DIRS = sorted(
    path.parent
    for path in REPO_ROOT.glob("packages/*/infra/postgres/alembic.ini")
    if (path.parent / "versions").is_dir()
)

#: `revision = "0002"` — the assignment alembic reads, not a mention in prose or a docstring.
REVISION_ASSIGNMENT = re.compile(r"^revision\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)


def _ids() -> list[str]:
    return [str(d.relative_to(REPO_ROOT)) for d in INFRA_DIRS]


def test_the_repo_has_alembic_trees_to_check() -> None:
    """Guard the guard: a glob that silently matches nothing is not a test."""
    assert INFRA_DIRS, "found no packages/*/infra/postgres/alembic.ini — has the layout moved?"


@pytest.mark.parametrize("infra", INFRA_DIRS, ids=_ids())
def test_no_revision_id_is_declared_by_two_migrations(infra: Path) -> None:
    """Two files claiming one id: alembic only warns, then silently drops one migration."""
    by_id: dict[str, list[str]] = {}
    for script in sorted((infra / "versions").glob("*.py")):
        match = REVISION_ASSIGNMENT.search(script.read_text())
        assert match, f"{script.name} declares no revision id"
        by_id.setdefault(match.group(1), []).append(script.name)

    duplicates = {rev: names for rev, names in by_id.items() if len(names) > 1}
    assert not duplicates, (
        f"revision id declared more than once in {infra.relative_to(REPO_ROOT)}: {duplicates}."
        " Renumber the later migration and point its down_revision at the earlier one."
    )


@pytest.mark.parametrize("infra", INFRA_DIRS, ids=_ids())
def test_the_migration_sequence_has_exactly_one_head(infra: Path) -> None:
    """Two heads mean two branches merged without a merge revision; `upgrade head` then fails."""
    # script_location in the committed ini is `.`, which only resolves when alembic runs from
    # that directory — the package's own migration tests override it the same way.
    cfg = Config(str(infra / "alembic.ini"))
    cfg.set_main_option("script_location", str(infra))
    heads = ScriptDirectory.from_config(cfg).get_heads()

    assert len(heads) == 1, (
        f"{infra.relative_to(REPO_ROOT)} has {len(heads)} heads ({heads});"
        " a merge revision is owed, or a down_revision points at the wrong parent."
    )


@pytest.mark.parametrize("infra", INFRA_DIRS, ids=_ids())
def test_every_migration_is_reachable_from_head(infra: Path) -> None:
    """A file on disk that the graph cannot walk to never runs, and nothing else says so."""
    cfg = Config(str(infra / "alembic.ini"))
    cfg.set_main_option("script_location", str(infra))
    walked = {rev.revision for rev in ScriptDirectory.from_config(cfg).walk_revisions()}
    on_disk = {
        match.group(1)
        for script in (infra / "versions").glob("*.py")
        if (match := REVISION_ASSIGNMENT.search(script.read_text()))
    }

    assert on_disk == walked, (
        f"{infra.relative_to(REPO_ROOT)}: revisions on disk but not reachable from head: {sorted(on_disk - walked)}"
    )
