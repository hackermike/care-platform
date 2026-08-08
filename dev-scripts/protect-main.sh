#!/usr/bin/env bash
# Apply branch protection to main.
#
# GitHub only allows this on a public repo or a paid plan — on a free private
# repo the API returns 403, which is why `main` is currently unprotected. Run
# this immediately after making the repository public.
#
#   ./dev-scripts/protect-main.sh
#
# What it enforces:
#   - changes reach main only through a pull request
#   - at least one approving review, and stale approvals are dismissed on push
#   - CODEOWNERS review required (see /CODEOWNERS)
#   - the `test` check must pass
#   - no force pushes, no branch deletion
#   - the rules apply to admins too, so there is no quiet bypass
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${GH_REPO:-hackermike/care-platform}"

if [ "$(gh api "repos/${REPO}" --jq .private)" = "true" ]; then
  echo "WARNING: ${REPO} is private. Branch protection needs a public repo or a"
  echo "paid plan; this will very likely fail with 403." >&2
fi

gh api -X PUT "repos/${REPO}/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["test"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

echo "Protected main on ${REPO}."
echo
echo "Also set, in Settings -> Actions -> General:"
echo "  'Require approval for all external contributors' — so a fork's PR"
echo "  cannot run workflows until you approve them."
