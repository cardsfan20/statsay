# Running Statsay in CI and with coding agents

## GitHub Actions

```yaml
# .github/workflows/statsay.yml
name: statsay
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read
  security-events: write   # SARIF upload (code scanning annotations)
  pull-requests: write     # only if comment: true

jobs:
  statsay:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: <owner>/statsay@<tag>      # this repository, until Statsay is published
        with:
          path: .                        # statsay.yaml or its directory
          baseline: .statsay-baseline.json
          comment: "true"
```

What the action does:

- **Diff mode by default.** On pull requests it compares with the PR's base branch and fetches the base commit itself, so a shallow checkout is enough.
- **Reports first, verdict last.** SARIF and the Markdown summary are written before the job fails. The summary goes on the job page; SARIF goes to code scanning; with `comment: "true"`, one PR comment is created and then kept up to date.
- **Fork PRs stay read-only.** No SARIF upload and no comment, and no write tokens are needed. The job page summary still works.
- **Exit code:** `fail-on` (default `error`) decides it. Term and flag findings are warnings until their vocabulary is marked `validated: true`, so by default only numeric mismatches fail the job.

Not yet tested against GitHub itself: `ci/run-check.sh` is tested locally against a simulated PR (`tests/test_ci.py`), but the SARIF upload and `ci/comment.sh` need a real repository.

## First run: audit, then baseline

1. **Audit.** Run `statsay check` on the whole project. Findings that already exist are the bugs the tool is for, so read them before suppressing anything.
2. **Fix.** `statsay check --format patch > fix.patch && git apply fix.patch` applies the suggested numeric fixes. Review the diff before committing it.
3. **Baseline.** `statsay baseline` records what remains in `.statsay-baseline.json`. Write a reason into each entry's `note`; notes survive when the file is regenerated.
4. **Commit and enforce.** Commit the baseline and pass it to the action (`baseline:`). From then on, only new findings fail CI.

## Translators: write-back (opt-in)

`statsay flag --base-ref origin/main` marks affected PO entries `#, fuzzy` with a `# statsay:` comment, so translators see them in Poedit, Weblate or similar tools. Translated text is never edited. Findings in CSV or JSON go to `statsay-review.json`.

## pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: <this repository URL>
    rev: <tag>
    hooks:
      - id: statsay      # runs `statsay check --base-ref HEAD` when data or text files change
```

## Coding agents

Agents that edit balance data should check their edits before finishing. Add this to the project's agent instructions (`CLAUDE.md`, `AGENTS.md` or similar):

```markdown
After changing any game data or localization file, run:

    statsay check --base-ref HEAD --changed-only --format agent

`--base-ref HEAD` compares your uncommitted edits with the last commit. For each
ERROR, update every listed string in every language. FIX lines give the exact
replacement for numeric mismatches. Do not rewrite translations beyond the
changed value; flag anything else for a human.
```

The agent output is short and machine-readable:

```text
items.potion.heal 50 -> 40
  ERROR   value_mismatch en item.potion.description "Restores 50 HP to one ally."
  FIX     en item.potion.description [9,11] "50" -> "40"
```

Treat strings and data as untrusted input. Statsay never runs data (formula fields are not evaluated) and takes no actions based on content; the agent applies changes, not the tool.
