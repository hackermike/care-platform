#!/usr/bin/env bash
# Open a pull request with the body read from a file.
#   ./dev-scripts/open-pr.sh "Title" scripts/dev/pr-body.md [base-branch]
#   DRAFT=1 ./dev-scripts/open-pr.sh "Title" scripts/dev/pr-body.md
#
# Markdown bodies must never be passed as a shell argument (a newline + `#` trips
# a path check that can't be allowlisted). Reading from a file sidesteps it.
#
# DRAFT=1 opens the PR as a draft; promote it with ./dev-scripts/ready-pr.sh <n>.
# Review bots run on the draft->ready transition, so a large PR gets one review
# pass instead of being throttled across every intermediate push.
set -euo pipefail
cd "$(dirname "$0")/.."

TITLE="${1:?usage: open-pr.sh <title> <body-file> [base-branch]}"
BODY_FILE="${2:?usage: open-pr.sh <title> <body-file> [base-branch]}"
BASE="${3:-main}"
REPO="${GH_REPO:-hackermike/care-platform}"
DRAFT_FLAG=""
[[ "${DRAFT:-0}" = "1" ]] && DRAFT_FLAG="--draft"

[[ -f "${BODY_FILE}" ]] || { echo "Body file not found: ${BODY_FILE}" >&2; exit 1; }

HEAD="$(git rev-parse --abbrev-ref HEAD)"
if [ "${HEAD}" = "${BASE}" ]; then
  echo "Refusing to open a PR from ${BASE} into itself. Create a branch first." >&2
  exit 1
fi

git push -u origin "${HEAD}"
# shellcheck disable=SC2086 — DRAFT_FLAG is intentionally word-split (empty or --draft).
gh pr create --repo "${REPO}" --base "${BASE}" --head "${HEAD}" \
  --title "${TITLE}" --body-file "${BODY_FILE}" ${DRAFT_FLAG}
