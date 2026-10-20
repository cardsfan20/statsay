#!/usr/bin/env bash
# Run `statsay check` for CI: diff mode against the PR base, SARIF and a Markdown
# summary written to files, the summary appended to the job page. The exit code is
# reported as a step output instead of failing here, so reports are published first.
#
# Inputs (environment): INPUT_PATH, INPUT_BASE_REF, INPUT_FAIL_ON, INPUT_BASELINE,
# PR_BASE (the pull request's base branch, if any), GITHUB_OUTPUT, GITHUB_STEP_SUMMARY.
set -uo pipefail

args=(check "${INPUT_PATH:-.}" --sarif statsay.sarif --summary statsay-summary.md
      --fail-on "${INPUT_FAIL_ON:-error}")

base="${INPUT_BASE_REF:-}"
if [ -z "$base" ] && [ -n "${PR_BASE:-}" ]; then
  base="origin/${PR_BASE}"
fi
if [ -n "$base" ]; then
  # Make sure the base commit is present, even in a shallow checkout.
  git fetch --no-tags --quiet --depth=1 origin "${base#origin/}" 2>/dev/null || true
  args+=(--base-ref "$base")
fi
if [ -n "${INPUT_BASELINE:-}" ]; then
  args+=(--baseline "$INPUT_BASELINE")
fi

echo "statsay ${args[*]}"
statsay "${args[@]}"
status=$?

if [ -f statsay-summary.md ] && [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  cat statsay-summary.md >> "$GITHUB_STEP_SUMMARY"
fi
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "exit-code=$status" >> "$GITHUB_OUTPUT"
  [ -f statsay.sarif ] && echo "sarif=statsay.sarif" >> "$GITHUB_OUTPUT"
fi
exit 0
