#!/usr/bin/env bash
# Create or update one Statsay comment on a pull request, found by a hidden marker.
# Needs GH_TOKEN with pull-requests: write, REPO (owner/name) and PR (number).
set -euo pipefail

marker='<!-- statsay -->'
[ -f statsay-summary.md ] || { echo "no statsay-summary.md; nothing to post"; exit 0; }
body="$(printf '%s\n%s' "$marker" "$(cat statsay-summary.md)")"

existing="$(gh api "repos/${REPO}/issues/${PR}/comments" --paginate \
  --jq ".[] | select(.body | startswith(\"${marker}\")) | .id" | tail -n 1)"
if [ -n "$existing" ]; then
  gh api --silent -X PATCH "repos/${REPO}/issues/comments/${existing}" -f body="$body"
  echo "updated comment ${existing}"
else
  gh api --silent "repos/${REPO}/issues/${PR}/comments" -f body="$body"
  echo "created a comment"
fi
