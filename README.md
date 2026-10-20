# Statsay

Does your text say what your stats say? Statsay is a CI check that finds localized game text contradicting the gameplay data it describes. For example, a description that still says "Restores 50 HP" in English and Japanese after `heal` changed to 40.

Status: early development (milestone M1). The design is in [Localization as Code — Spec Revision 3.md](Localization%20as%20Code%20—%20Spec%20Revision%203.md).

## What M1 does

- Reads game data from a JSON array of objects and localization from a CSV file (`key,en,ja,…`).
- Binds strings to entities by key convention (`item.{id}.description`) or explicitly.
- Extracts numbers per locale and ties them to data fields with the spec's fixed confidence rule. Text is NFKC-normalized first, so `１５０` reads as 150.
- Reports:
  - `value_mismatch`: text claims a different value than the data. An error at high confidence, a warning otherwise.
  - `locale_value_divergence`: locales disagree on a value.
  - `unbound_claim` (info): a number in a bound string that isn't tied to any field.
  - Binding coverage.
- Runs offline; no model calls.

Diff mode, term/enum claims, RPG Maker and CI integrations come in later milestones.

## Try it

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python
.venv/Scripts/statsay check fixtures/toy-game
.venv/Scripts/python -m pytest
.venv/Scripts/python scripts/e1.py fixtures/toy-game   # E1 metrics and Gate 1 verdict
.venv/Scripts/python scripts/wesnoth_did.py check 83d4b397f1de466c721e4e393b361c71fc4f5b6c   # real bug: Wesnoth #8549
```

The Wesnoth check downloads files at a pinned commit; see [fixtures/wesnoth-did/](fixtures/wesnoth-did/README.md).

`statsay check` exits with 1 when findings at or above `--fail-on` exist (default `error`), and with 2 on configuration errors. Use `--format json` for machine-readable output.
