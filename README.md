# Statsay

Does your text say what your stats say? Statsay is a CI check that finds localized game text contradicting the gameplay data it describes. For example, a description that still says "Restores 50 HP" in English and Japanese after `heal` changed to 40.

Status: early development (v0.1). Feedback and issues are welcome at [github.com/cardsfan20/statsay](https://github.com/cardsfan20/statsay/issues).

## What it does

- **Reads** game data from JSON arrays or RPG Maker MV/MZ database files. Nested values come in through `fields:` paths such as `effects[code=11].value2`, with fixed transforms (e.g. fraction → percent).
- **Reads localization** from CSV files (`key,en,ja,…`) or from text stored in the data itself (RPG Maker's `description`).
- **Binds** strings to entities by key convention (`item.{id}.description`) or explicitly, and reports coverage.
- **Extracts claims per locale:**
  - numbers, tied to fields by a fixed, testable confidence rule (nearest anchor word in the same clause)
  - vocabulary terms, tied to enum, flag or list fields

  Text is NFKC-normalized (`１５０` → 150) and engine control codes (`\C[2]`) are masked.
- **Reports:**
  - `value_mismatch` / `enum_term_mismatch`: text contradicts the data.
  - `locale_value_divergence`: locales disagree.
  - `watched_field_changed` (diff mode): data changed but a text that states nothing about it did not.
  - `unbound_claim` (info): a number not tied to any field.
- **Runs offline**; no model calls.

- **CI and agents** (see [docs/ci.md](docs/ci.md)):
  - a grouped PR summary, SARIF with suggested fixes, a patch (`git apply`) and a short agent format
  - `--changed-only`
  - an audit-then-baseline workflow
  - a GitHub Action and a pre-commit hook
- **Translator write-back** (opt-in): `statsay flag` marks affected PO entries `#, fuzzy` with a comment and never edits translations.

## Try it

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python
.venv/Scripts/statsay check fixtures/toy-game
.venv/Scripts/python -m pytest
.venv/Scripts/python scripts/evaluate.py fixtures/toy-game      # precision/recall on planted bugs
.venv/Scripts/python scripts/evaluate.py fixtures/rpgmaker-mz   # same, on an RPG Maker MZ database
.venv/Scripts/python scripts/wesnoth_did.py check 83d4b397f1de466c721e4e393b361c71fc4f5b6c   # real bug: Wesnoth #8549
.venv/Scripts/python scripts/cdda_materials.py check 5d320508149b28da05fc4d45e4a8f2d1c7547ef6  # real bug: CDDA #53277
```

The real-bug checks download files at pinned commits; see [fixtures/wesnoth-did/](fixtures/wesnoth-did/README.md) and [fixtures/cdda-materials/](fixtures/cdda-materials/README.md).

`statsay check` exits with 1 when new findings at or above `--fail-on` exist (default `error`), and with 2 on configuration errors. Options:
- `--base-ref origin/main` (or `--base DIR`) for diff mode
- `--format summary|sarif|agent|patch|json` for other outputs
- `--baseline FILE` to suppress reviewed findings

Use `statsay baseline` to record reviewed findings and `statsay flag` for translator write-back.
