#!/usr/bin/env bash
# Squash-merge a PR, delete its branch, and return to an up-to-date main.
#   ./dev-scripts/merge-pr.sh 12
# CI must be green (no --admin), matching the billing repo's discipline.
set -euo pipefail
cd "$(dirname "$0")/.."

PR="${1:?usage: merge-pr.sh <pr-number>}"
REPO="${GH_REPO:-hackermike/care-platform}"

gh pr merge "${PR}" --repo "${REPO}" --squash --delete-branch
git checkout main
git pull --ff-only origin main
echo "Merged PR #${PR}; main is up to date."
git log --oneline -1
