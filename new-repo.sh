#!/usr/bin/env bash
set -euo pipefail

# new-repo.sh — create a new repo from the ADE template and bootstrap it
# Usage: ./new-repo.sh <repo-name> <package-name> <description> [visibility]

TEMPLATE="robford-brookai/repo-ade"

REPO_NAME="${1:?Usage: new-repo.sh <repo-name> <package-name> <description> [visibility]}"
PACKAGE_NAME="${2:?Missing package name}"
DESCRIPTION="${3:?Missing description}"
VISIBILITY="${4:---private}"

# Validate before `gh repo create`, never after: a bad package name discovered during bootstrap
# would leave an orphaned remote repo behind that someone has to go and delete by hand.

if ! printf '%s' "$REPO_NAME" | grep -Eq '^[a-z0-9][a-z0-9._-]*$'; then
  echo "Invalid repo name: '$REPO_NAME'" >&2
  echo "Use lowercase letters, digits, hyphens — e.g. pulse-check1" >&2
  exit 1
fi

# The package name becomes a directory under src/ and an import path, so it must be a valid
# Python identifier. Hyphens are the common mistake: `src/pulse-check1` cannot be imported.
if ! printf '%s' "$PACKAGE_NAME" | grep -Eq '^[a-z_][a-z0-9_]*$'; then
  echo "Invalid package name: '$PACKAGE_NAME'" >&2
  echo "A Python package name takes lowercase letters, digits and underscores, and cannot" >&2
  echo "start with a digit. Hyphens are not importable." >&2
  echo "  suggestion: $(printf '%s' "$REPO_NAME" | sed 's/[-.]/_/g')" >&2
  exit 1
fi

# Catching the no-op rename matters because bootstrap.sh derives the old name from `ls src/`:
# passing the template's own package silently produces a project still called repo_ade.
TEMPLATE_PACKAGE=$(basename "$(find "$(dirname "$0")/src" -mindepth 1 -maxdepth 1 -type d -not -name '__pycache__' | head -1)")
if [ "$PACKAGE_NAME" = "$TEMPLATE_PACKAGE" ]; then
  echo "Package name '$PACKAGE_NAME' is the template's own package." >&2
  echo "Pass the NEW project's package name, or the generated repo keeps the template's." >&2
  echo "  suggestion: $(printf '%s' "$REPO_NAME" | sed 's/[-.]/_/g')" >&2
  exit 1
fi

gh repo create "$REPO_NAME" --template "$TEMPLATE" "$VISIBILITY" --clone
cd "$REPO_NAME"

chmod +x bootstrap.sh
./bootstrap.sh "$REPO_NAME" "$PACKAGE_NAME" "$DESCRIPTION"

OWNER=$(gh repo view --json owner --jq .owner.login)
SLUG="$OWNER/$REPO_NAME"

echo ""
echo "Configuring $SLUG"

# Squash-only: one work order, one commit (AGENTS.md), so merge commits and rebases
# would both break the one-task-one-commit correspondence.
gh repo edit "$SLUG" \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge \
  || echo "  WARN: could not set merge strategy — run the command above manually"

# Branch protection must be sent as a JSON body. `gh api -f` is --raw-field: every value goes
# as a string, so `-f restrictions=null` sends "null" where the API demands JSON null, and
# `-f enforce_admins=true` sends "true" instead of a boolean. The request is then rejected as
# malformed, which is easy to misread as a permissions problem.
# enforce_admins stays false: main is protected by a separate org/account-level config, and
# enforcing here would block the admin pushes that bootstrap and template:sync rely on.
PROTECTION_JSON='{"required_status_checks":{"strict":true,"contexts":["quality"]},"enforce_admins":false,"required_pull_request_reviews":{"required_approving_review_count":0},"restrictions":null}'

# Zero required approvals is deliberate: CI is the reviewer. Raise it for repos with human review.
if PROTECT_ERR=$(printf '%s' "$PROTECTION_JSON" |
    gh api -X PUT "repos/$SLUG/branches/main/protection" --input - 2>&1 >/dev/null); then
  echo "  branch protection enabled (required check: quality)"
else
  echo "  WARN: branch protection not set: ${PROTECT_ERR%%$'\n'*}"
  echo "  Retry with:"
  echo "    printf '%s' '$PROTECTION_JSON' | gh api -X PUT repos/$SLUG/branches/main/protection --input -"
fi

# The scaffold is not done until CI has passed once. Branch protection references the
# check by job name, and a rename silently disables the merge gate — this is what proves
# the workflow is actually wired, which local gates cannot tell you.
#
# Match the run to the bootstrap commit by headSha. `gh run list --limit 1` returns whatever
# ran most recently, which right after generation is the repo-creation run from the template's
# own Initial commit — a run that is green regardless of what bootstrap produced. Watching it
# reports success while the commit you actually care about is failing.
echo ""
echo "Waiting for CI on the bootstrap commit..."
HEAD_SHA=$(git rev-parse HEAD)
RUN_ID=""
for _ in $(seq 1 30); do
  RUN_ID=$(gh run list --limit 20 --json databaseId,headSha \
    --jq "[.[] | select(.headSha==\"$HEAD_SHA\")][0].databaseId" 2>/dev/null || true)
  [ -n "$RUN_ID" ] && [ "$RUN_ID" != "null" ] && break
  RUN_ID=""
  sleep 2
done

if [ -z "$RUN_ID" ]; then
  echo "  WARN: no CI run appeared for ${HEAD_SHA:0:8} within 60s. Check manually:"
  echo "    gh run list --repo $SLUG"
elif gh run watch "$RUN_ID" --exit-status >/dev/null 2>&1; then
  echo "  CI green on main (${HEAD_SHA:0:8})"
else
  echo "  WARN: CI failed for ${HEAD_SHA:0:8}. Inspect with:"
  echo "    gh run view --repo $SLUG $RUN_ID --log-failed"
  echo "  A generated repo that ships red CI teaches everyone that red CI is normal — fix it in"
  echo "  the template ($TEMPLATE), not here."
fi
