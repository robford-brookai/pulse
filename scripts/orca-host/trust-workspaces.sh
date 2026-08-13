#!/usr/bin/env bash
# trust-workspaces.sh — mark Orca worktrees as trusted for Claude Code.
#
# Runs ON the host. Claude Code trusts projects per absolute path, so a worktree
# created after the last run starts untrusted, and an untrusted workspace has
# its permissions.allow entries silently IGNORED. On an unattended host that
# surfaces as an agent stalling on a permission prompt nobody is there to
# answer, so re-run this after creating worktrees.
#
#   aws ssm send-command --instance-ids "$ID" \
#     --document-name AWS-RunShellScript \
#     --parameters commands="$(cat trust-workspaces.sh)"

set -euo pipefail

sudo -u ubuntu python3 - <<'PY'
import glob, json, os

path = os.path.expanduser("~/.claude.json")
config = json.load(open(path)) if os.path.exists(path) else {}
projects = config.setdefault("projects", {})

targets = ["/home/ubuntu/workspace/pulse"] + glob.glob("/home/ubuntu/orca/workspaces/*/*")

added = 0
for target in targets:
    entry = projects.setdefault(target, {})
    if not entry.get("hasTrustDialogAccepted"):
        entry["hasTrustDialogAccepted"] = True
        added += 1

json.dump(config, open(path, "w"), indent=2)
print(f"{len(targets)} workspaces known, {added} newly trusted")
PY
