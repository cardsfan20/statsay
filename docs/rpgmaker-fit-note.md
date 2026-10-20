# RPG Maker MZ fit note

Checked 2026-10-20 against the public database of [samuelcardillo/MMORPGMaker-MV](https://github.com/samuelcardillo/MMORPGMaker-MV) (`data/Items.json`, `Skills.json`, `System.json`; GPL-2.0, inspected and run locally, nothing copied). `System.json` has the MZ-only `advanced` block, so the files are in MZ format. The database is in French (`locale: fr_FR`) and looks like the stock MZ sample database: Potion 500, Hi-Potion 1 500, seeds +3. One project only.

## Layout (confirmed)

- Each database file is a JSON array whose first element is `null`; entry `n` has `id: n`.
- Unused slots are entries with an empty `name` and `description`. Statsay skips them.
- Items and skills keep the player-facing `description` in the same object as their effects. For the source language, the entity itself is the binding.
- `effects` is a list of `{code, dataId, value1, value2}`. Matches the engine source checked earlier: 11/12/13 recover HP/MP/TP (`value1` fraction of max, `value2` flat); 21/22 add/remove state (`dataId` = state id); 42 grow parameter (`dataId` = parameter, `value1` = amount).
- `damage` is `{type, elementId, formula, variance, critical}`. `formula` is JavaScript the engine runs with `eval`. Statsay watches it but never evaluates it.
- `scope` is a number; Potion (one ally) has 7. The other scope codes are from memory and still need checking.
- Descriptions are wrapped onto two lines by hand with `\n`, often mid-sentence. They may contain control codes (`\C[n]`, `\I[n]`, `\V[n]`).

## What the real data showed

- **Hand-written numbers are common in items.** 12 of 20 described items state a number. All 11 that Statsay can tie to a field match the data. This supports M1's numeric focus for RPG Maker games, at least for games built on the stock database.
- **Skills mostly state game-rule constants**, e.g. "Utilisable jusqu'à 2 fois à la suite" (buff stacking) and "pendant 5 tours". These aren't in the data, so they come out as `unbound_claim` info (25 in this database). Real stat claims in skills are rare.
- **Three extractor problems found and fixed:**
  - A line break was treated as a clause break, which would cut a number off from its anchor on the next line. Line breaks now count as wrapping.
  - French writes "1 500" with a no-break space as the thousands separator; it was read as 1 and 500. No-break and thin spaces between digits now group digits.
  - The spec's "one number, one numeric field" fallback tied "2 fois" to `mpCost` and produced 22 false errors. The fallback now applies only to fields with no anchors configured for the locale.
- **After the fixes:** 0 errors, 0 warnings and 25 info on the whole database (159 bound strings).

## Translations (not verified)

RPG Maker has no built-in localization. Translation plugins export database text to CSV or JSON (Sang Hendrix's Non-Destructive Localization, ToshA_Localization, opendigitalworld's Multi-Language System). Statsay reads such a CSV if its keys follow a pattern like `item.{id}.description`. Each plugin's actual key scheme still needs checking; that is pilot work for M3.

## Fit

Good. The source-language binding is free, effect values are machine-readable through `fields:` paths, and item descriptions quote those values literally. Open points: plugin key schemes, the remaining scope codes, and deciding whether to suppress known game-rule phrases ("N fois", "N tours") so they don't show up as info noise.
