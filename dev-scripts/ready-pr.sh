#!/usr/bin/env bash
# Move a draft PR to ready for review.
#   ./dev-scripts/ready-pr.sh 12
#
# Draft-then-ready is deliberate: review bots (CodeRabbit) run on the transition
# rather than on every intermediate push, so one large PR gets one review pass
# instead of being throttled across many small ones.
set -euo pipefail
cd "$(dirname "$0")/.."

NUMBER="${1:?usage: ready-pr.sh <pr-number>}"
REPO="${GH_REPO:-hackermike/care-platform}"

gh pr ready "${NUMBER}" --repo "${REPO}"
echo "PR #${NUMBER} is ready for review."
