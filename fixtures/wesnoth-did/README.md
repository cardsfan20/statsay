# Wesnoth: Descent into Darkness AMLAs

A natural-bug reconstruction for E2: [Wesnoth #8549](https://github.com/wesnoth/wesnoth/issues/8549) (duplicate of [#7767](https://github.com/wesnoth/wesnoth/issues/7767)). Malin Keshar's "+1 shadow wave damage" AMLA granted +2. It shipped in stable release 1.16.11 and was fixed in the data by [PR #7770](https://github.com/wesnoth/wesnoth/pull/7770) (`increase_damage=2` → `1`).

Wesnoth is GPL-licensed, so no Wesnoth text is committed here. `scripts/wesnoth_did.py` downloads two files at a pinned commit and converts them:

- `data/campaigns/Descent_Into_Darkness/utils/amlas.cfg` → `data/amlas.json`. One entity per `[advancement]`, with `damage`, `<attack>_damage`, `movement` and `resistance` fields.
- `po/wesnoth-did/ja.po` → the `ja` column of `locales/strings.csv`. Fuzzy and context-specific entries are skipped.

The converter handles only the WML subset these AMLAs use. It is not a general WML adapter.

## Files

| File | Contents |
| --- | --- |
| `statsay.yaml` | Bindings and anchors, written before Statsay was first run on this data |
| `expected.json` | Findings per pinned commit, also written before the first run |

## Run

```sh
python scripts/wesnoth_did.py check 83d4b397f1de466c721e4e393b361c71fc4f5b6c   # 1.16.11, with the bug
python scripts/wesnoth_did.py check 8cc930666e47931b3e3436790ceeb210d4144200   # after PR #7770
python scripts/wesnoth_did.py build <commit> out/wesnoth                        # inspect the converted input
```

The test `tests/test_wesnoth.py` runs both checks when `STATSAY_NETWORK=1` is set.

## Results (2026-10-20)

| Commit | AMLAs | Findings |
| --- | --- | --- |
| `83d4b39` (1.16.11) | 30 | 2 errors: `value_mismatch` en "+1 shadow wave damage" and ja 「影の波動のダメージ +1」, data says 2. Matches `expected.json` |
| `8cc9306` (fix) | 33 | None. Matches `expected.json` |
| `9f54f6a` (1.18.8) | 33 | None |
| `ecfcc25` (1.19.28) | 33 | None |

Of 60 strings at 1.16.11, 24 carry numbers tied to a field (26 high-confidence claims). Statsay flagged the 2 wrong strings and none of the other 22.
