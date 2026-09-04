#!/usr/bin/env python3
"""
Scaffold a new PULSE connector package from templates/connector/.

Renders the template tree into packages/<name>/ and prints the registration diff — the exact
edits the new package needs at every site in the repo that has to name it. This script renders
and prints; it does not apply the registrations. `task connector:new NAME=<x>` (devex-eight task
1.4) is what applies them.

Usage:
    uv run python scripts/connector_new.py --name claims-connector
    uv run python scripts/connector_new.py --name claims-connector --print-registrations
        prints the diff alone, on stdout, so `git apply -p1` can read it — and nothing else.
    uv run python scripts/connector_new.py --name claims-connector --dest /tmp/out --root .

NAME is the distribution name (kebab-case, e.g. `claims-connector`). The module name is its
snake_case form (`claims_connector`) and the environment-variable prefix its upper form
(`CLAIMS_CONNECTOR`). All three are derived; none is passed separately.

Exit codes:
    0  rendered (and/or printed) successfully
    2  unusable NAME, missing template, or a destination that already exists
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: A distribution name: lowercase, starts with a letter, words separated by a single `-` or `_`.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*([-_][a-z0-9]+)*$")

#: Rendered files lose this suffix. Template files carry it so no tool in the repo mistakes an
#: unrendered `{{NAME}}` tree for source: pytest never collects it, ruff never lints it, and the
#: `.tmpl` name says what it is. Same reason cat9's fixtures carry `.fixture` / `.golden`.
TEMPLATE_SUFFIX = ".tmpl"

TEMPLATE_DIR = Path("templates/connector")
DEFAULT_DEST_PARENT = Path("packages")


@dataclass(frozen=True)
class Names:
    """The three forms of a connector's name, all derived from the one the caller passed."""

    dist: str
    module: str
    upper: str

    @property
    def substitutions(self) -> dict[str, str]:
        """The template tokens, longest first so no token is a prefix of another's replacement."""
        return {"{{NAME}}": self.module, "{{DIST}}": self.dist, "{{UPPER}}": self.upper}


class ConnectorNewError(Exception):
    """Something the caller can fix: a bad name, a missing template, an occupied destination."""


def parse_name(raw: str) -> Names:
    """Derive every form of the name, or raise with what a usable name looks like."""
    name = raw.strip()
    if not NAME_PATTERN.match(name):
        msg = (
            f"NAME={raw!r} is not a usable package name. Use lowercase words separated by "
            f"hyphens, starting with a letter — for example `claims-connector`."
        )
        raise ConnectorNewError(msg)
    return Names(dist=name.replace("_", "-"), module=name.replace("-", "_"), upper=name.replace("-", "_").upper())


def render_text(text: str, names: Names) -> str:
    """Substitute every template token in `text`."""
    for token, value in names.substitutions.items():
        text = text.replace(token, value)
    return text


def template_files(template_dir: Path) -> list[Path]:
    """Every template file, as paths relative to `template_dir`, sorted.

    Sorted because this list reaches stdout and the golden gate compares it — an unsorted
    directory walk flakes between filesystems.
    """
    if not template_dir.is_dir():
        msg = f"template tree not found: {template_dir}"
        raise ConnectorNewError(msg)
    found = sorted(p.relative_to(template_dir) for p in template_dir.rglob("*") if p.is_file())
    if not found:
        msg = f"template tree is empty: {template_dir}"
        raise ConnectorNewError(msg)
    return found


def rendered_path(relative: Path, names: Names) -> Path:
    """Where one template file lands: tokens substituted, `.tmpl` stripped."""
    parts = [render_text(part, names) for part in relative.parts]
    rendered = Path(*parts)
    if rendered.name.endswith(TEMPLATE_SUFFIX):
        rendered = rendered.with_name(rendered.name[: -len(TEMPLATE_SUFFIX)])
    return rendered


def render(template_dir: Path, dest: Path, names: Names, *, force: bool = False) -> list[Path]:
    """Write the rendered package into `dest` and return the files written, sorted.

    Refuses a destination that already exists unless `force`: a half-overwritten package is worse
    than a stopped command, and the caller has not lost anything by being told to pick a name.
    """
    relatives = template_files(template_dir)
    if dest.exists() and not force:
        msg = f"destination already exists: {dest} (pass --force to overwrite)"
        raise ConnectorNewError(msg)

    written: list[Path] = []
    for relative in relatives:
        target = dest / rendered_path(relative, names)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_text((template_dir / relative).read_text(), names))
        written.append(target)
    return written


# --- Registration sites --------------------------------------------------------------------
#
# Nine edits across two files. Each function below takes the file's current text and returns it
# with the new package named, or unchanged when the package is already registered — so running
# this twice prints an empty diff rather than a duplicate entry.


def _insert_into_array(text: str, array_header: str, entry: str) -> str:
    """Insert `entry` as the last element of the TOML array opened by `array_header`."""
    # Quoted, so `packages/billing` is not read as already present in `packages/billing-connector`.
    if f'"{entry}"' in text:
        return text
    lines = text.splitlines(keepends=True)
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(array_header))
    except StopIteration:
        return text
    close = next(i for i in range(start, len(lines)) if lines[i].rstrip("\n") == "]")
    lines.insert(close, f'    "{entry}",\n')
    return "".join(lines)


def _insert_after_last_matching(text: str, pattern: re.Pattern[str], new_line: str) -> str:
    """Insert `new_line` directly after the last line matching `pattern`."""
    if new_line.strip() in text:
        return text
    lines = text.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if pattern.match(line)]
    if not matches:
        return text
    lines.insert(matches[-1] + 1, new_line)
    return "".join(lines)


def _append_to_taskfile_var(text: str, var: str, addition: str) -> str:
    """Append ` addition` to the end of the `var:` line in the Taskfile's vars block."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith(f"  {var}:"):
            # Whole-token comparison: `packages/billing` must not read as already present just
            # because `packages/billing-connector` is on the line.
            if addition in line.split(":", 1)[1].split():
                return text
            lines[i] = f"{line.rstrip()} {addition}\n"
            return "".join(lines)
    return text


def _deploy_stanza_stubs(names: Names) -> str:
    """The image and deploy targets, commented out.

    Commented rather than live because both need a Docker daemon and a target credential, and an
    uncommented target that cannot run is worse than no target: `cat4_command_contract.sh` would
    then assert a command nobody can execute. Uncomment them when the connector has a Dockerfile.
    """
    return (
        f"  # {names.dist}:image:\n"
        f"  #   desc: Build the {names.dist} service image and tag it TAG (needs Docker)\n"
        f"  #   # Build context is the repo root — pulse-core is a workspace sibling installed\n"
        f"  #   # from a sibling path, not from PyPI. Never reached from `check`: it needs a\n"
        f"  #   # Docker daemon and, on an arm64 dev machine, an emulated amd64 build.\n"
        f"  #   requires:\n"
        f"  #     vars: [TAG]\n"
        f"  #   cmds:\n"
        f"  #     - docker buildx build --platform linux/amd64"
        f" -f packages/{names.dist}/Dockerfile -t {names.dist}:{{{{.TAG}}}} .\n"
        f"\n"
        f"  # {names.dist}:deploy:\n"
        f"  #   desc: Roll the {names.dist} deployment to TAG on TARGET"
        f" (needs that target's credential)\n"
        f"  #   # Dumb by design, same posture as billing-connector:deploy: push the image\n"
        f"  #   # `{names.dist}:image` already built, then re-point TARGET at TAG. No\n"
        f"  #   # generation logic here. Never reached from `check`: it needs credentials.\n"
        f"  #   requires:\n"
        f"  #     vars: [TAG, TARGET]\n"
        f"  #   cmds:\n"
        f"  #     - docker push {names.dist}:{{{{.TAG}}}}\n"
        f"\n"
    )


def _insert_deploy_stubs(text: str, names: Names) -> str:
    """Insert the stubs after the last `*:deploy:` stanza, where the deploy targets already live."""
    # Matches a live stanza as well as a commented stub: a package that already has real image
    # and deploy targets must not be handed stubs for them.
    if f"{names.dist}:image:" in text:
        return text
    lines = text.splitlines(keepends=True)
    deploys = [i for i, line in enumerate(lines) if re.match(r"^  [\w:.-]+:deploy:\s*$", line)]
    if not deploys:
        return text
    # Walk past that stanza's body: the next line at two-space indent starting a word or a `#`
    # opens the following target or area header.
    cursor = deploys[-1] + 1
    while cursor < len(lines) and not re.match(r"^  \S", lines[cursor]):
        cursor += 1
    lines.insert(cursor, _deploy_stanza_stubs(names))
    return "".join(lines)


def register_pyproject(text: str, names: Names) -> str:
    """Workspace member, workspace source, and the tests' `assert` exemption."""
    text = _insert_into_array(text, "members = [", f"packages/{names.dist}")
    text = _insert_after_last_matching(
        text,
        re.compile(r"^[\w.-]+ = \{ workspace = true \}$"),
        f"{names.dist} = {{ workspace = true }}\n",
    )
    return _insert_after_last_matching(
        text,
        re.compile(r'^"packages/[\w./*-]+/tests/\*\*" = \["S101"\]$'),
        f'"packages/{names.dist}/tests/**" = ["S101"]\n',
    )


def register_taskfile(text: str, names: Names) -> str:
    """The four path variables, plus the commented image and deploy stanzas."""
    text = _append_to_taskfile_var(text, "LINT_PATHS", f"packages/{names.dist}")
    text = _append_to_taskfile_var(text, "TYPED_PATHS", f"packages/{names.dist}/src")
    text = _append_to_taskfile_var(text, "TESTED_PATHS", f"packages/{names.dist}/tests")
    text = _append_to_taskfile_var(text, "COV_PATHS", f"--cov=packages/{names.dist}/src")
    return _insert_deploy_stubs(text, names)


#: Every registration site, as (repo-relative path, transform). The order is the order the diff
#: prints in, and `docs/connectors/authoring.md` lists the same sites in the same order.
REGISTRATIONS = (
    (Path("pyproject.toml"), register_pyproject),
    (Path("Taskfile.yml"), register_taskfile),
)


def _registration_changes(root: Path, names: Names) -> list[tuple[Path, str, str]]:
    """(path, before, after) for every registration site whose content would change."""
    changes: list[tuple[Path, str, str]] = []
    for relative, transform in REGISTRATIONS:
        path = root / relative
        if not path.is_file():
            continue
        before = path.read_text()
        after = transform(before, names)
        if before != after:
            changes.append((path, before, after))
    return changes


def registration_diff(root: Path, names: Names) -> str:
    """The unified diff of every registration edit, or "" when nothing needs changing."""
    chunks: list[str] = []
    for path, before, after in _registration_changes(root, names):
        relative = path.relative_to(root)
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )
    return "".join(chunks)


def apply_registrations(root: Path, names: Names) -> list[Path]:
    """Write every registration edit to disk; return the files actually changed, sorted.

    `task connector:new` (devex-eight task 1.4) is the only caller: 1.3's script renders and
    reports, this is what edits the repo.
    """
    changes = _registration_changes(root, names)
    for path, _, after in changes:
        path.write_text(after)
    return sorted(path for path, _, _ in changes)


def _report_print_registrations(root: Path, names: Names) -> int:
    # The diff alone, so `git apply` can read it off stdout. Empty when nothing needs changing.
    print(registration_diff(root, names), end="")
    return 0


def _report_apply_registrations(root: Path, names: Names) -> int:
    changed = apply_registrations(root, names)
    if changed:
        print(f"Registered {names.dist} at {len(changed)} site(s):")
        for path in changed:
            print(f"  {path.relative_to(root)}")
        print()
        print("Next: uv sync --all-packages")
    else:
        print(f"{names.dist} is already registered at every site; nothing to apply.")
    return 0


def _report_registration_diff(root: Path, names: Names) -> int:
    diff = registration_diff(root, names)
    if diff:
        print(f"Registration diff — the edits {names.dist} still needs (not applied):")
        print()
        print(diff, end="")
        print()
        print(f"Apply it with `task connector:new NAME={names.dist}`, then `uv sync --all-packages`.")
    else:
        print(f"{names.dist} is already registered at every site; no registration diff to apply.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="connector_new.py",
        description="Scaffold a PULSE connector package and print its registration diff.",
    )
    parser.add_argument("--name", required=True, help="distribution name, e.g. claims-connector")
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help=f"where the package tree is written (default: {DEFAULT_DEST_PARENT}/<name>)",
    )
    parser.add_argument("--root", type=Path, default=Path(), help="repo root the registration diff is computed against")
    parser.add_argument("--template", type=Path, default=None, help=f"template tree (default: <root>/{TEMPLATE_DIR})")
    parser.add_argument("--force", action="store_true", help="overwrite an existing destination")
    parser.add_argument(
        "--print-registrations",
        action="store_true",
        help="print the registration diff only; render nothing",
    )
    parser.add_argument(
        "--apply-registrations",
        action="store_true",
        help="write the registration edits into pyproject.toml and Taskfile.yml, instead of only "
        "printing the diff — what `task connector:new` (devex-eight task 1.4) runs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.print_registrations and args.apply_registrations:
        print("error: --print-registrations and --apply-registrations are mutually exclusive", file=sys.stderr)
        return 2

    try:
        names = parse_name(args.name)
        template_dir = args.template or args.root / TEMPLATE_DIR
        dest = args.dest or args.root / DEFAULT_DEST_PARENT / names.dist

        if not args.print_registrations:
            written = render(template_dir, dest, names, force=args.force)
            print(f"Rendered {names.dist} ({names.module}) into {dest}:")
            for path in written:
                print(f"  {path}")
            print()
    except ConnectorNewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_registrations:
        return _report_print_registrations(args.root, names)
    if args.apply_registrations:
        return _report_apply_registrations(args.root, names)
    return _report_registration_diff(args.root, names)


if __name__ == "__main__":
    raise SystemExit(main())
