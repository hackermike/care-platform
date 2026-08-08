#!/usr/bin/env bash
# Squash-merge a PR, delete its branch, and return to an up-to-date main.
#   ./dev-scripts/merge-pr.sh 12
# CI must be green (no --admin), matching the billing repo's discipline.
#
# Stacked PRs: deleting a branch that another open PR uses as its base makes
# GitHub *close* that PR, and a closed PR cannot be reopened or retargeted once
# its base is gone — the work has to be reopened as a new PR. So this script
# checks for dependents first and keeps the branch when it finds any.
set -euo pipefail
cd "$(dirname "$0")/.."

PR="${1:?usage: merge-pr.sh <pr-number>}"
REPO="${GH_REPO:-hackermike/care-platform}"

HEAD_BRANCH="$(gh pr view "${PR}" --repo "${REPO}" --json headRefName --jq .headRefName)"
DEPENDENTS="$(gh pr list --repo "${REPO}" --state open --base "${HEAD_BRANCH}" \
  --json number --jq '[.[].number] | join(", ")')"

if [ -n "${DEPENDENTS}" ]; then
  echo "Open PRs are based on ${HEAD_BRANCH}: ${DEPENDENTS}"
  echo "Retarget them to main first, or they will be closed when the branch goes."
  echo "  gh pr edit <n> --repo ${REPO} --base main"
  echo "Merging without deleting the branch."
  gh pr merge "${PR}" --repo "${REPO}" --squash
else
  gh pr merge "${PR}" --repo "${REPO}" --squash --delete-branch
fi

git checkout main
git pull --ff-only origin main
echo "Merged PR #${PR}; main is up to date."
git log --oneline -1
