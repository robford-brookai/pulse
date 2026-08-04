#!/usr/bin/env python3
"""
Project an OpenSpec change's tasks.md into Linear: one parent issue, one sub-issue per task.

Usage:
    python scripts/linear_sync.py --change <id>            # plan only, mutates nothing
    python scripts/linear_sync.py --change <id> --apply    # create and update issues

Direction of truth is one-way. `tasks.md` and the work-order files are canonical; Linear is where
humans watch, comment and approve. A sub-issue edited by hand is drift and gets overwritten on the
next sync. Nothing is ever read back out of Linear into the repo.

Dry run is the default because this writes to a shared system. `--apply` is the only way to mutate,
and the plan it prints first is the same plan it executes.

Three rules from WORKFLOW.md's `sync_linear` step, all of which are easy to get wrong:

* **Team and project are passed explicitly on every mutation**, read from WORKFLOW.md's `linear`
  block — never inferred from whatever workspace the API key happens to belong to.
* **stateId is resolved once per run and passed explicitly on create**, so a team's triage intake
  cannot swallow a new sub-issue before anyone sees it.
* **Sync owns the unstarted band, plus one narrow terminal write.** It sets Todo on create and
  heals Triage -> Todo on update. It also moves an already-existing sub-issue straight to Done
  when its task is checked off in tasks.md — sync is the trigger for that transition, immediate
  with the checkoff rather than deferred to merge/archive. It never writes In Progress, Blocked,
  In Review or Canceled, and it never touches the *parent* issue's status: that stays humans'
  at merge/archive, per `linear.status_ownership`.

Out-of-lane tasks (`destructive_ops`, `operational_discovery`) are **not** synced. They run on the
Open Engine queue in team CCC under its own receipt-token protocol with its own status vocabulary,
and half-implementing that protocol here would produce issues nobody's tooling recognises. They are
listed at the end of the plan so they are visible rather than silently dropped.

Auth: LINEAR_API_KEY in the environment. No key means plan-only; `--apply` without one is an error
rather than a silent no-op.
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType


def _sibling(name: str) -> ModuleType:
    """Import another script in this directory by path.

    The glue scripts are CLI entry points rather than an installed package, so they cannot be
    imported normally. Loading by location keeps the dependency explicit and avoids mutating
    sys.path for every other process that ends up importing this one.
    """
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if not spec or not spec.loader:
        msg = f"cannot load {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch_tasks = _sibling("dispatch_tasks.py")
workflow_mod = _sibling("workflow.py")

API_URL = "https://api.linear.app/graphql"
UNSTARTED = "Todo"
DONE = "Done"
TRIAGE = "Triage"
# Sync may write these and nothing else. In Progress, Blocked, In Review, Canceled are owned
# elsewhere; Done is writable only via complete_sub, on an already-existing sub-issue whose
# task is checked off — never on the parent issue.
SYNC_WRITABLE = frozenset({UNSTARTED, DONE})


class SyncError(Exception):
    """The sync cannot proceed."""


def resolve_tasks_md(change: str) -> Path:
    """Find a change's tasks.md whether it's active or already archived.

    `openspec archive` moves tasks.md to `openspec/changes/archive/<date>-<change>/`, but the
    Linear-side identity of the change (parent issue title, `[CHANGE] <change>`) never changes —
    so callers must keep passing the plain change name, never the archive path, or sync creates
    a duplicate parent instead of finding the existing one.
    """
    active = Path("openspec/changes") / change / "tasks.md"
    if active.exists():
        return active
    matches = sorted(Path("openspec/changes/archive").glob(f"*-{change}/tasks.md"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        msg = f"multiple archived tasks.md match `{change}`: {[str(m) for m in matches]}"
        raise SyncError(msg)
    msg = f"no tasks.md found for `{change}` (checked {active} and openspec/changes/archive/*-{change}/)"
    raise SyncError(msg)


class LinearClient:
    """Minimal GraphQL client. stdlib only, so this adds no dependency to the workspace."""

    def __init__(self, api_key: str, url: str = API_URL) -> None:
        self._api_key = api_key
        self._url = url

    def query(self, document: str, variables: dict) -> dict:
        payload = json.dumps({"query": document, "variables": variables}).encode()
        request = urllib.request.Request(  # noqa: S310 - constant https endpoint
            self._url,
            data=payload,
            headers={"Authorization": self._api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            msg = f"Linear request failed: {exc}"
            raise SyncError(msg) from exc
        if body.get("errors"):
            msg = f"Linear returned errors: {body['errors']}"
            raise SyncError(msg)
        return body.get("data") or {}


def parent_title(change: str) -> str:
    return f"[CHANGE] {change}"


def task_key_of(title: str) -> str | None:
    """The leading `1.2` in a sub-issue title — how a Linear issue is matched back to a task."""
    match = re.match(r"^(\d+\.\d+)\b", title.strip())
    return match.group(1) if match else None


def work_order_body(change: str, task: dict, work_orders: Path) -> str:
    """The dispatched work-order body, which WORKFLOW.md makes the sub-issue description."""
    path = work_orders / change / f"{task['task_id']}.md"
    if not path.exists():
        msg = (
            f"no work order at {path}. WORKFLOW.md makes the dispatched work-order body the "
            f"sub-issue description, so run `task dispatch CHANGE={change}` before syncing."
        )
        raise SyncError(msg)
    return path.read_text()


def issue_title(task: dict) -> str:
    """A task's title as a Linear issue title: annotations stripped, key present exactly once.

    Two things that look trivial and are not. Annotation blocks are dropped by matching
    `[... : ...]` rather than by cutting at the first backtick — a title like
    ``Import `ocean` at `7bc9d2c` `` is mostly inline code, and splitting on the backtick
    silently truncates it to one word. And most titles already begin with their key, so
    prefixing unconditionally yields "1.2 1.2 Import ...".
    """
    title = re.sub(r"`?\[[^\]]*:[^\]]*\]`?", "", task["title"])
    title = re.sub(r"\s+", " ", title).strip(" -—")
    key = task["key"]
    if not title.startswith(f"{key} "):
        title = f"{key} {title}"
    return title[:250]


def desired_subissues(change: str, tasks: list[dict], work_orders: Path) -> list[dict]:
    """One entry per dispatchable task, in file order."""
    return [
        {
            "key": task["key"],
            "title": issue_title(task),
            "description": work_order_body(change, task, work_orders),
            "done": task["done"],
        }
        for task in tasks
        if task["dispatchable"]
    ]


def plan(desired: list[dict], existing: dict, parent_exists: bool, change: str) -> list[dict]:
    """Diff desired state against Linear, as a list of operations.

    Pure: no network, no clock. The plan printed in a dry run is byte-for-byte the plan applied
    with --apply, so reviewing one is reviewing the other.
    """
    operations: list[dict] = []
    if not parent_exists:
        operations.append({"kind": "create_parent", "title": parent_title(change)})

    for item in desired:
        found = existing.get(item["key"])
        if found is None:
            operations.append({"kind": "create_sub", "key": item["key"], "title": item["title"]})
            continue
        if found.get("description") != item["description"] or found.get("title") != item["title"]:
            operations.append({"kind": "update_sub", "key": item["key"], "id": found["identifier"]})
        # Sync owns the unstarted band: heal the triage edge, touch nothing else in that band.
        if found.get("status") == TRIAGE:
            operations.append({
                "kind": "heal_status",
                "key": item["key"],
                "id": found["identifier"],
                "state": UNSTARTED,
            })
        # The one terminal write sync owns: checkoff completes an existing sub-issue immediately,
        # rather than waiting on merge/archive. Skipped once already Done or Canceled, so re-runs
        # are a no-op.
        if item["done"] and found.get("status") not in {DONE, "Canceled"}:
            operations.append({
                "kind": "complete_sub",
                "key": item["key"],
                "id": found["identifier"],
                "from_status": found.get("status"),
                "state": DONE,
            })

    orphans = sorted(set(existing) - {d["key"] for d in desired})
    operations += [{"kind": "orphan", "key": k, "id": existing[k]["identifier"]} for k in orphans]
    return operations


def assert_status_writes_are_legal(operations: list[dict], statuses: list[str]) -> None:
    """Belt and braces on the one rule whose violation is invisible until it has already happened.

    Writing `In Progress`, `Blocked`, `In Review` or `Canceled` from a sync would silently steal a
    status band from the agents, Orca, or humans that own it, and the damage looks like an agent
    misbehaving rather than a tool overreaching. `Done` is legal only via `complete_sub`, which
    `plan()` only ever produces for an already-existing sub-issue whose task is checked off.
    """
    illegal = [
        op for op in operations if op.get("state") and op["state"] not in SYNC_WRITABLE and op["state"] in statuses
    ]
    if illegal:
        msg = f"sync tried to write a status it does not own: {illegal}. Only {sorted(SYNC_WRITABLE)} is permitted."
        raise SyncError(msg)


PARENT_QUERY = """
query($team:String!,$q:String!){
  issues(filter:{team:{key:{eq:$team}}, title:{eq:$q}}, first:1){
    nodes{ id identifier title
      children(first:250){ nodes{ id identifier title description state{ name } } } }
  }
}
"""

STATES_QUERY = """
query($team:String!){ team(key:$team){ id states{ nodes{ id name } } projects{ nodes{ id name } } } }
"""

CREATE_MUTATION = """
mutation($input:IssueCreateInput!){ issueCreate(input:$input){ success issue{ id identifier } } }
"""

UPDATE_MUTATION = """
mutation($id:String!,$input:IssueUpdateInput!){ issueUpdate(id:$id, input:$input){ success } }
"""


def fetch_context(client: LinearClient, team: str, project: str) -> dict:
    """Team id, the Todo state id, and the project id — all resolved once per run."""
    data = client.query(STATES_QUERY, {"team": team})
    team_node = data.get("team")
    if not team_node:
        msg = f"team {team!r} not found in this workspace"
        raise SyncError(msg)

    states = {n["name"]: n["id"] for n in team_node["states"]["nodes"]}
    if UNSTARTED not in states:
        msg = f"team {team} has no {UNSTARTED!r} status; sync cannot place new issues in the unstarted band"
        raise SyncError(msg)
    if DONE not in states:
        msg = f"team {team} has no {DONE!r} status; sync cannot complete checked-off sub-issues"
        raise SyncError(msg)

    projects = {n["name"]: n["id"] for n in team_node["projects"]["nodes"]}
    if project and project not in projects:
        msg = f"project {project!r} not found in team {team}. WORKFLOW.md's linear.project is stale."
        raise SyncError(msg)

    return {
        "team_id": team_node["id"],
        "todo_state_id": states[UNSTARTED],
        "done_state_id": states[DONE],
        "project_id": projects.get(project) if project else None,
        "states": states,
    }


def fetch_existing(client: LinearClient, team: str, change: str) -> tuple[bool, dict]:
    data = client.query(PARENT_QUERY, {"team": team, "q": parent_title(change)})
    nodes = (data.get("issues") or {}).get("nodes") or []
    if not nodes:
        return False, {}
    parent = nodes[0]
    existing = {}
    for child in parent["children"]["nodes"]:
        key = task_key_of(child["title"])
        if key:
            existing[key] = {
                "identifier": child["identifier"],
                "id": child["id"],
                "title": child["title"],
                "description": child.get("description") or "",
                "status": (child.get("state") or {}).get("name"),
            }
    return True, existing


def _render_op(op: dict) -> str:
    if op["kind"] == "create_parent":
        return f"  create parent   {op['title']}"
    if op["kind"] == "create_sub":
        return f"  create sub      {op['key']:<6} {op['title'][:80]}"
    if op["kind"] == "update_sub":
        return f"  update sub      {op['key']:<6} {op['id']} (description drifted from the work order)"
    if op["kind"] == "heal_status":
        return f"  heal status     {op['key']:<6} {op['id']} Triage -> {UNSTARTED}"
    if op["kind"] == "complete_sub":
        return f"  complete sub    {op['key']:<6} {op['id']} {op['from_status']} -> {DONE} (checked off in tasks.md)"
    return f"  ORPHAN          {op['key']:<6} {op['id']} — no longer in tasks.md, left alone"


def render_plan(operations: list[dict], out_of_lane: list[dict]) -> str:
    lines = []
    if not operations:
        lines.append("Linear is already in sync — nothing to do.")
    else:
        counts: dict[str, int] = {}
        for op in operations:
            counts[op["kind"]] = counts.get(op["kind"], 0) + 1
        lines.append("Plan: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
        lines.append("")
        lines += [_render_op(op) for op in operations]

    if out_of_lane:
        lines += ["", f"Not synced — Open Engine queue, team CCC ({len(out_of_lane)}):"]
        lines += [f"  {t['key']:<6} [{t['lane']}] {t['title'][:70]}" for t in out_of_lane]
        lines.append("  File these under that queue's own protocol; their statuses are not DNA's.")
    return "\n".join(lines)


def apply_plan(client: LinearClient, operations: list[dict], desired: list[dict], ctx: dict, change: str) -> int:
    by_key = {d["key"]: d for d in desired}
    parent_id = None
    applied = 0

    for op in operations:
        base = {"teamId": ctx["team_id"]}
        if ctx["project_id"]:
            base["projectId"] = ctx["project_id"]

        if op["kind"] == "create_parent":
            data = client.query(
                CREATE_MUTATION,
                {
                    "input": {
                        **base,
                        "title": op["title"],
                        "stateId": ctx["todo_state_id"],
                        "description": f"Parent issue for OpenSpec change `{change}`. "
                        "The repo is the record; this projection is one-directional.",
                    }
                },
            )
            parent_id = data["issueCreate"]["issue"]["id"]
            applied += 1
        elif op["kind"] == "create_sub":
            item = by_key[op["key"]]
            client.query(
                CREATE_MUTATION,
                {
                    "input": {
                        **base,
                        "title": item["title"],
                        "description": item["description"],
                        "stateId": ctx["todo_state_id"],
                        **({"parentId": parent_id} if parent_id else {}),
                    }
                },
            )
            applied += 1
        elif op["kind"] == "update_sub":
            item = by_key[op["key"]]
            # No stateId: an update must not move an issue an agent may already have started.
            client.query(
                UPDATE_MUTATION, {"id": op["id"], "input": {"title": item["title"], "description": item["description"]}}
            )
            applied += 1
        elif op["kind"] == "heal_status":
            client.query(UPDATE_MUTATION, {"id": op["id"], "input": {"stateId": ctx["todo_state_id"]}})
            applied += 1
        elif op["kind"] == "complete_sub":
            client.query(UPDATE_MUTATION, {"id": op["id"], "input": {"stateId": ctx["done_state_id"]}})
            applied += 1
    return applied


def _target(block: dict) -> tuple[str, str]:
    """Team and project, read from WORKFLOW.md and passed explicitly on every mutation.

    Never inferred from the API key's default workspace — that is how issues land in the wrong
    team and nobody notices until someone goes looking for them.
    """
    linear = block.get("linear") or {}
    team = linear.get("team")
    if not team:
        msg = "WORKFLOW.md's linear block declares no team"
        raise SyncError(msg)
    return str(team), str(linear.get("project") or "")


def _api_key(require: bool) -> str:
    key = os.environ.get("LINEAR_API_KEY", "")
    if require and not key:
        msg = "--apply needs LINEAR_API_KEY in the environment"
        raise SyncError(msg)
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync an OpenSpec change's tasks into Linear")
    parser.add_argument("--change", required=True)
    parser.add_argument("--apply", action="store_true", help="perform the mutations (default is plan only)")
    parser.add_argument("--work-orders", type=Path, default=Path("work_orders"))
    args = parser.parse_args()

    try:
        team, project = _target(workflow_mod.load()[0])
        tasks = dispatch_tasks.parse_tasks(resolve_tasks_md(args.change))
        dispatch_tasks.validate(tasks)
        desired = desired_subissues(args.change, tasks, args.work_orders)
        out_of_lane = [t for t in tasks if not t["dispatchable"]]

        api_key = _api_key(require=args.apply)
        if not api_key:
            print(f"No LINEAR_API_KEY — planning against an empty workspace (team {team}, project {project}).\n")
            operations = plan(desired, {}, parent_exists=False, change=args.change)
            print(render_plan(operations, out_of_lane))
            return 0

        client = LinearClient(api_key)
        ctx = fetch_context(client, team, project)
        parent_exists, existing = fetch_existing(client, team, args.change)
        operations = plan(desired, existing, parent_exists, args.change)
        assert_status_writes_are_legal(operations, list(ctx["states"]))

        print(render_plan(operations, out_of_lane))
        if not args.apply:
            print("\nDry run. Re-run with APPLY=1 to write these to Linear.")
            return 0
        applied = apply_plan(client, operations, desired, ctx, args.change)
        print(f"\nApplied {applied} operation(s) to team {team}.")
    except (SyncError, dispatch_tasks.DispatchError, workflow_mod.WorkflowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
