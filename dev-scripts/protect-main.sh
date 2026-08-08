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
#   - the `test` check must pass, against an up-to-date branch
#   - no force pushes, no branch deletion
#   - review threads must be resolved before merging
#
# REQUIRED_APPROVALS defaults to 0. On a solo project 1 would mean you can never
# merge anything: GitHub does not let you approve your own pull request, and
# `enforce_admins` removes the bypass. That is a lockout, not a control. What
# actually keeps an outside contributor from merging is that merging needs write
# access at all — which a fork does not confer.
#
# Set it to 1 the day a second maintainer exists, which is also when CODEOWNERS
# review starts meaning something:
#   REQUIRED_APPROVALS=1 ./dev-scripts/protect-main.sh
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${GH_REPO:-hackermike/care-platform}"

if [ "$(gh api "repos/${REPO}" --jq .private)" = "true" ]; then
  echo "WARNING: ${REPO} is private. Branch protection needs a public repo or a"
  echo "paid plan; this will very likely fail with 403." >&2
fi

REQUIRED_APPROVALS="${REQUIRED_APPROVALS:-0}"
# Code-owner review only means something once approvals are actually required.
if [ "${REQUIRED_APPROVALS}" -gt 0 ]; then CODEOWNERS=true; else CODEOWNERS=false; fi

cat > /tmp/protection.json <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["test"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": ${CODEOWNERS},
    "required_approving_review_count": ${REQUIRED_APPROVALS}
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

gh api -X PUT "repos/${REPO}/branches/main/protection" --input /tmp/protection.json > /dev/null
rm -f /tmp/protection.json

echo "Protected main on ${REPO} (required approvals: ${REQUIRED_APPROVALS})."
echo
echo "Then set, in Settings -> Actions -> General -> Fork pull request workflows:"
echo "  'Require approval for all external contributors' — otherwise a fork's PR"
echo "  runs your workflows before you have read the diff."
