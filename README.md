# Statsay

Does your text say what your stats say? Statsay is a CI check that finds localized game text contradicting the gameplay data it describes. For example, a description that still says "Restores 50 HP" in English and Japanese after `heal` changed to 40.

Status: early development (v0.2). Feedback and issues are welcome at [github.com/cardsfan20/statsay](https://github.com/cardsfan20/statsay/issues).

## Quick start

```sh
pip install git+https://github.com/cardsfan20/statsay
cd your-game
statsay init                      # look at the project, write statsay.yaml, run a first check
statsay check --format summary    # review what it found
```

`statsay init` recognizes RPG Maker MV/MZ projects, and JSON data with CSV or PO localization files.
- **RPG Maker:** descriptions are read from the database, effect values and equipment parameters become fields, and the game's own terms from `System.json` (HP/MP names, parameter names) become anchor words.
- **Anchor mining:** for any project, init learns anchor words from your data. If "Restores 500 HP" sits next to an item whose `heal` is 500, then "HP" is an anchor for `heal`.

Review the generated `statsay.yaml`, then see [docs/ci.md](docs/ci.md) to run it on every pull request.

## What it does

- **Reads** game data from JSON arrays or RPG Maker MV/MZ database files. Nested values come in through `fields:` paths such as `effects[code=11].value2` or `params.2`, with fixed transforms (e.g. fraction → percent).
- **Reads localization** from CSV files (`key,en,ja,…`), gettext PO files, or text stored in the data itself (RPG Maker's `description`).
- **Binds** strings to entities by key convention (`item.{id}.description`) or explicitly, and reports coverage.
- **Extracts claims per locale:**
  - numbers, tied to fields by a fixed, testable rule: the nearest anchor word in the same clause, with labels like "HP+50" or 「攻撃力：15」 owning their number, and percentages only matching percent fields
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

## Does it work?

### On real projects, with the config `statsay init` writes

Six public RPG Maker games from GitHub, each checked with the `statsay.yaml` that `statsay init` generated, unedited. Only each game's database files were downloaded (at the pinned commit); nothing from them is included here.

| Project (commit) | Engine, language | Strings | Numbers checked (agree with data) | Errors (look real) | Warnings (look real) | `init` time |
| --- | --- | --- | --- | --- | --- | --- |
| [RPGMakerMZ_touhouhuzinden](https://github.com/takahiro093090-A417/RPGMakerMZ_touhouhuzinden) (`6a056f0`) | MZ, Japanese | 1,147 | 12 (10) | 1 (1) | 53 (1) | 1.8 s |
| [EndlessDeathMarch](https://github.com/musiccycle/EndlessDeathMarch) (`2b8935d`) | MV, Japanese | 150 | 91 (90) | 1 (1) | 0 | 0.6 s |
| [second-arrival](https://github.com/jefanko/second-arrival) (`2c78a48`) | MV, English | 809 | 516 (513) | 3 (2) | 5 (2) | 0.9 s |
| [One-Piece-Game](https://github.com/dcarmichael18/One-Piece-Game) (`d70bab8`) | MV, English | 194 | 12 (12) | 0 | 1 (1) | 0.6 s |
| [proceria](https://github.com/xatay/proceria) (`b027ee9`), blind | MZ, English | 152 | 8 (8) | 0 | 1 (1) | 0.7 s |
| [Smith](https://github.com/Alkrin/Smith) (`27ef393`), blind | MZ, English | 435 | 11 (11) | 0 | 0 | 0.8 s |

What the errors (which fail CI) found:
- **Four of five look like real contradictions:**
  - EndlessDeathMarch armor 7 says 「知識力：25」 while its data gives 30.
  - touhouhuzinden item 101 says 「最大HPを1000上昇する」 while its effect grants 100.
  - second-arrival weapon 9 says "WIS+20 SPD+10" while both stats are 30.
- **The fifth is a false alarm,** caused by a badly mined anchor word.

Warnings are mostly noise on these projects (about 5 of 60 look real, e.g. "Paralyzes all enemies" on a single-target skill). The noise comes from:
- states applied by plugins or common events rather than database effects
- conditions such as 「状態なら」 ("if in that state")
- words that contain a state name (防御 inside 防御力)

Warnings don't fail CI unless you choose `--fail-on warning`.

How to read this:
- **Not fully blind:** the first four projects were used while developing `init`, and eleven general fixes to init and the number extractor came out of them. proceria and Smith were run once afterwards, without any changes.
- **"Look real"** is my reading of the text against the data; none of these were confirmed by, or reported to, the authors.
- **Numbers checked** varies a lot: many descriptions state things the database doesn't hold as plain values (damage formulas, turn counts, plugin effects). Those numbers are reported as info, not errors.
- **Single language:** all six games have one language, so cross-language checks weren't exercised here.
- **Init's limits:** it doesn't add one-off explicit bindings, and it doesn't guess term vocabularies for non-RPG Maker projects.

### On known real bugs

- **[Wesnoth #8549](https://github.com/wesnoth/wesnoth/issues/8549):** an AMLA said "+1 shadow wave damage" and gave +2, shipped in stable 1.16.11. Statsay flags exactly the English and Japanese strings at that commit and nothing after the fix ([details](fixtures/wesnoth-did/README.md)).
- **[Cataclysm-DDA #53277](https://github.com/CleverRaven/Cataclysm-DDA/issues/53277):** an electric blanket "made of polyester" was cotton in the data, and the issue stayed open for three years. Statsay flags it at the bug commit and not after the fix ([details](fixtures/cdda-materials/README.md)).

### On planted bugs

Two fixture games with planted data changes, text changes and negative controls (`scripts/evaluate.py`):
- **With hand-written configs:** every planted bug is found, with no false alarms.
- **With configs written by `statsay init`:** 11 of 15 planted bugs on the toy game (the misses are term and flag claims, which init doesn't guess for generic projects) and 7 of 9 on the RPG Maker game. No false alarms on clean fixtures or negative controls.

## Development

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest
.venv/Scripts/python scripts/evaluate.py fixtures/toy-game      # precision/recall on planted bugs
.venv/Scripts/python scripts/evaluate.py fixtures/rpgmaker-mz   # same, on an RPG Maker MZ database
.venv/Scripts/python scripts/wesnoth_did.py check 83d4b397f1de466c721e4e393b361c71fc4f5b6c   # real bug: Wesnoth #8549
.venv/Scripts/python scripts/cdda_materials.py check 5d320508149b28da05fc4d45e4a8f2d1c7547ef6  # real bug: CDDA #53277
```

The real-bug checks download files at pinned commits.

`statsay check` exits with 1 when new findings at or above `--fail-on` exist (default `error`), and with 2 on configuration errors. Options:
- `--base-ref origin/main` (or `--base DIR`) for diff mode
- `--format summary|sarif|agent|patch|json` for other outputs
- `--baseline FILE` to suppress reviewed findings

Use `statsay baseline` to record reviewed findings and `statsay flag` for translator write-back.
