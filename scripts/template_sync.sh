#!/usr/bin/env bash
set -euo pipefail

# template_sync.sh — show or apply ADE template changes since this repo was generated.
#
# Usage:
#   scripts/template_sync.sh diff    # what changed upstream since .ade-template-version
#   scripts/template_sync.sh apply   # apply those changes to infrastructure paths only
#
# A GitHub template clone has no upstream remote and no shared history — `gh repo create
# --template` starts a fresh commit graph. bootstrap.sh therefore records the template commit
# it was generated from in .ade-template-version, and this script fetches the template
# directly to diff against that recorded point.
#
# This is deliberately narrower than copier's `copier update`: it touches infrastructure the
# template owns and never the files a repo makes its own.

TEMPLATE_URL="${ADE_TEMPLATE_URL:-https://github.com/robford-brookai/repo-ade.git}"
VERSION_FILE=".ade-template-version"

# Template-owned infrastructure. Everything else — README, CLAUDE.md, AGENTS.md, pyproject,
# src/, docs/, openspec/, uv.lock — belongs to the repo once generated and is never touched.
SYNC_PATHS=(
  ".github"
  ".pre-commit-config.yaml"
  "Taskfile.yml"
  "bootstrap.sh"
  "scripts"
  "tests/scaffold"
)

MODE="${1:?Usage: template_sync.sh <diff|apply>}"

if [ ! -f "$VERSION_FILE" ]; then
  echo "No $VERSION_FILE found." >&2
  echo "This repo was not generated from the ADE template, or predates version stamping." >&2
  echo "To adopt: record the template commit you are level with, e.g." >&2
  echo "  git ls-remote $TEMPLATE_URL main | cut -f1 > $VERSION_FILE" >&2
  exit 1
fi

REF=$(tr -d '[:space:]' < "$VERSION_FILE")
if [ -z "$REF" ]; then
  echo "$VERSION_FILE is empty" >&2
  exit 1
fi

echo "Fetching $TEMPLATE_URL ..."
git fetch --quiet "$TEMPLATE_URL" main

if ! git cat-file -e "${REF}^{commit}" 2>/dev/null; then
  echo "Recorded template commit $REF is not reachable upstream." >&2
  echo "The template's history may have been rewritten. Compare manually against FETCH_HEAD." >&2
  exit 1
fi

UPSTREAM=$(git rev-parse FETCH_HEAD)
if [ "$REF" = "$UPSTREAM" ]; then
  echo "Already level with the template ($REF)."
  exit 0
fi

# --- package rename awareness -------------------------------------------------------------
#
# bootstrap.sh renames the package on generation, so upstream says `pkg_pulse` where this repo
# says its own slug. A raw text diff has no idea that identifier is a variable: every hunk that
# touches it conflicts, and resolving toward upstream leaks the template's package name into a
# repo where that path does not exist. Rewriting the patch first makes those hunks apply by
# context, which is the whole reason `git apply` can succeed here at all.
#
# This is the one substitution copier gets for free by re-rendering from recorded answers. It is
# also why the template URL is deliberately NOT rewritten: `repo-ade` in the clone URL is correct
# in every generated repo, and substituting it would point the repo at itself.

package_slug_of() {
  # Sole directory under src/ in a given tree-ish ("" means the working tree).
  local treeish=$1
  if [ -z "$treeish" ]; then
    find src -mindepth 1 -maxdepth 1 -type d -not -name '__pycache__' -exec basename {} \; | head -1
  else
    git ls-tree --name-only "$treeish" src/ | sed 's|^src/||; s|/$||' | head -1
  fi
}

TEMPLATE_SLUG=$(package_slug_of "$UPSTREAM" || true)
LOCAL_SLUG=$(package_slug_of "" || true)

rewrite_patch() {
  # Rewrites both diff headers (a/src/<slug>/...) and content lines.
  if [ -n "$TEMPLATE_SLUG" ] && [ -n "$LOCAL_SLUG" ] && [ "$TEMPLATE_SLUG" != "$LOCAL_SLUG" ]; then
    sed "s/${TEMPLATE_SLUG}/${LOCAL_SLUG}/g"
  else
    cat
  fi
}

case "$MODE" in
  diff)
    PATCH=$(mktemp)
    trap 'rm -f "$PATCH"' EXIT
    git diff "$REF" "$UPSTREAM" -- "${SYNC_PATHS[@]}" | rewrite_patch > "$PATCH"
    echo "Template changes ${REF:0:8}..${UPSTREAM:0:8} (infrastructure paths only):"
    if [ -n "$TEMPLATE_SLUG" ] && [ "$TEMPLATE_SLUG" != "$LOCAL_SLUG" ]; then
      echo "Rewriting package name ${TEMPLATE_SLUG} -> ${LOCAL_SLUG}."
    fi
    echo ""
    git apply --stat "$PATCH"
    echo ""
    echo "Apply with: task template:sync"
    ;;
  apply)
    PATCH=$(mktemp)
    trap 'rm -f "$PATCH"' EXIT
    git diff "$REF" "$UPSTREAM" -- "${SYNC_PATHS[@]}" | rewrite_patch > "$PATCH"
    if [ ! -s "$PATCH" ]; then
      echo "No infrastructure changes to apply; recording $UPSTREAM."
      echo "$UPSTREAM" > "$VERSION_FILE"
      exit 0
    fi
    if [ -n "$TEMPLATE_SLUG" ] && [ "$TEMPLATE_SLUG" != "$LOCAL_SLUG" ]; then
      echo "Rewriting package name ${TEMPLATE_SLUG} -> ${LOCAL_SLUG}."
    fi
    # --3way is the fallback: a rewritten patch normally applies by context, and only an
    # genuinely divergent file falls through to a three-way merge. When it does, conflict
    # markers are left in the working tree rather than the hunk being silently dropped.
    if git apply --3way "$PATCH"; then
      echo "$UPSTREAM" > "$VERSION_FILE"
      echo "Applied. Review the diff, then run: task check"
    else
      echo "" >&2
      echo "Conflicts. Resolve them, then record the new version yourself:" >&2
      echo "  echo $UPSTREAM > $VERSION_FILE" >&2
      exit 1
    fi
    ;;
  *)
    echo "Unknown mode: $MODE (expected diff or apply)" >&2
    exit 1
    ;;
esac
