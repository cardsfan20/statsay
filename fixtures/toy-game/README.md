# Toy game fixture

Ground truth for evaluation E1 (mutation fixtures) and the test data for M1. A clean toy game whose EN/JA item descriptions all agree with the data, plus planted mutations, each listing the exact findings the tool should report.

## Layout

| Path | Contents |
| --- | --- |
| `data/items.json` | 13 items; watched fields `heal`, `mp`, `duration`, `attack_up`, `revive_percent`, `scope`; unwatched `price` |
| `locales/strings.csv` | `key,en,ja`; names and descriptions, plus one tutorial hint |
| `config.yaml` | Bindings and claim rules in the spec's proposed syntax |
| `expected/clean.json` | Coverage and findings for the unmutated fixture |
| `mutations.json` | 10 data-only, 2 text-only and 10 negative-control mutations with expected findings |

## What the clean fixture exercises

| Item | Case |
| --- | --- |
| `potion` | Plain number + scope term; also bound to `tutorial.potion_hint` by an explicit binding |
| `hi_potion` | Full-width digits in JA (`１５０`), needs NFKC |
| `mega_potion`, `group_ether` | `all_allies` vocabulary |
| `brew` | Number inside a name ("Level 3"), must not be read as the heal claim |
| `regen_tonic` | Two numbers per string, assigned by nearest anchor ("5 HP per second for 10 seconds") |
| `power_draught` | Percent claim; full-width `％` in JA |
| `revival_feather` | Percent claim next to "HP", on an entity with no `heal` field |
| `elixir` | No numbers at all ("Fully restores") |
| `ration` | EN quotes the number; JA paraphrases (「少し回復」) |
| `smoke_bomb` | No numeric fields |
| `antidote` | Unbound: its key `item.antidote.desc` breaks the convention |

## How to read `expected`

- A mutation's `expected` lists findings **in addition to** those in `expected/clean.json`. Negative controls expect none.
- Findings marked `"diff_only": true` appear only in diff mode (base = clean fixture, head = mutated copy). All others appear on the current revision alone, and in diff mode too.
- `watched_field_changed` fires only for a string that has **no claim** for the changed field. When a claim exists, `value_mismatch` decides.
- `locale_value_divergence` fires whenever two locales' high-confidence claims for the same field differ, even if `value_mismatch` also fires.
- `unbound_claim` applies only to bound strings. Numbers in unbound strings (e.g. `antidote`, or a `ui.*` key) are not checked.

## Using it

```sh
python scripts/fixture.py validate fixtures/toy-game          # consistency checks
python scripts/fixture.py apply fixtures/toy-game D01 out/D01 # write a mutated copy
```

`validate` checks that every mutation applies to the clean files (each edit's `from` must match), that expected keys exist, and that the data and CSV files are in canonical form so mutated copies diff to just the changed lines. Keep the files LF-only and UTF-8 without BOM.

## Not covered yet

Kanji numerals (五十, 半分), ranges ("10–20"), multipliers ("x2"), plurals, units needing conversion (frames, fractions), and nested data. The last two arrive with the RPG Maker adapter in M2.
