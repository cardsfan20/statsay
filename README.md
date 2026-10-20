# Statsay

Does your text say what your stats say? Statsay is a CI check that finds localized game text contradicting the gameplay data it describes. For example, a description that still says "Restores 50 HP" in English and Japanese after `heal` changed to 40.

Status: early development (M2 built). The design is in [Localization as Code — Spec Revision 3.md](Localization%20as%20Code%20—%20Spec%20Revision%203.md).

## What it does

- **Reads** game data from JSON arrays or RPG Maker MV/MZ database files. Nested values come in through `fields:` paths such as `effects[code=11].value2`, with fixed transforms (e.g. fraction → percent).
- **Reads localization** from CSV files (`key,en,ja,…`) or from text stored in the data itself (RPG Maker's `description`).
- **Binds** strings to entities by key convention (`item.{id}.description`) or explicitly, and reports coverage.
- **Extracts claims per locale:**
  - numbers, tied to fields with the spec's fixed confidence rule
  - vocabulary terms, tied to enum, flag or list fields

  Text is NFKC-normalized (`１５０` → 150) and engine control codes (`\C[2]`) are masked.
- **Reports:**
  - `value_mismatch` / `enum_term_mismatch`: text contradicts the data.
  - `locale_value_divergence`: locales disagree.
  - `watched_field_changed` (diff mode): data changed but a text that states nothing about it did not.
  - `unbound_claim` (info): a number not tied to any field.
- **Runs offline**; no model calls.

CI integrations, PR summaries and translator write-back come in M3.

## Try it

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python
.venv/Scripts/statsay check fixtures/toy-game
.venv/Scripts/python -m pytest
.venv/Scripts/python scripts/e1.py fixtures/toy-game      # E1 metrics and Gate 1 verdict
.venv/Scripts/python scripts/e1.py fixtures/rpgmaker-mz   # same, on an RPG Maker MZ database
.venv/Scripts/python scripts/wesnoth_did.py check 83d4b397f1de466c721e4e393b361c71fc4f5b6c   # real bug: Wesnoth #8549
```

The Wesnoth check downloads files at a pinned commit; see [fixtures/wesnoth-did/](fixtures/wesnoth-did/README.md).

`statsay check` exits with 1 when findings at or above `--fail-on` exist (default `error`), and with 2 on configuration errors. Use `--format json` for machine-readable output, and `--base-ref origin/main` (or `--base DIR`) for diff mode.
