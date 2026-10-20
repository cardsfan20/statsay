# RPG Maker MZ fixture

A small Japanese-source game in the MZ database format (see [docs/rpgmaker-fit-note.md](../../docs/rpgmaker-fit-note.md)), with planted mutations for E1. The content is original; only the file layout follows RPG Maker.

## Layout

| Path | Contents |
| --- | --- |
| `data/Items.json` | 8 slots after the leading `null`: 7 items plus one unused, nameless slot. Japanese descriptions sit next to `effects` |
| `data/Skills.json` | Attack (no description) and Fire (MP cost and a damage formula) |
| `locales/en.csv` | English translations, as a translation plugin might export them, keyed `item.{id}.description` |
| `statsay.yaml` | `rpgmaker` data sources, `data` localization for Japanese, derived `fields:` paths, claims |
| `expected/clean.json` | Coverage and findings for the unmutated fixture |
| `mutations.json` | 7 data-only, 2 text-only and 6 negative-control mutations |

## What it exercises

| Entry | Case |
| --- | --- |
| Potion, Hi-Potion | `effects[code=11].value2`; Hi-Potion's number and anchor are split across the hand-wrapped line in both languages |
| Magic Water | `effects[code=12].value1` stored as a fraction, scaled to a percentage (0.5 → 50) |
| Elixir | Fractions of 1 (full recovery) with no number in the text; only diff mode can flag changes |
| Antidote | Control codes around the term (`\C[2]毒\C[0]`), in both languages |
| Panacea | Several `code=22` effects, so `cures` is a list |
| Power Seed | `effects[code=42].value1`, scope 11 (user) |
| Slot 8 | Unused nameless slot, skipped |
| Fire | Raw `mpCost` field; `damage.formula` watched as a formula, never evaluated |
| Attack | No description, so it shows as unbound in coverage |

Run `python scripts/e1.py fixtures/rpgmaker-mz` to score it.
