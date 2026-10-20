# Cataclysm-DDA: armor material claims

A natural-bug reconstruction for term claims, and a false-positive test on real prose. [CDDA #53277](https://github.com/CleverRaven/Cataclysm-DDA/issues/53277): the electric blanket is described as "made of polyester" while its material is `cotton`. The issue was open from December 2021 until [PR #77272](https://github.com/CleverRaven/Cataclysm-DDA/pull/77272) changed the material to `nylon` (CDDA's generic synthetic fabric) in October 2024.

Cataclysm-DDA is CC-BY-SA, so no CDDA data is committed. `scripts/cdda_materials.py` downloads `tool_armor.json`, every file under `data/json/items/armor/` and `materials.json` at a pinned commit, resolves `copy-from` (with `extend`/`delete` for materials), and runs two vocabularies:

- **B (hand-written), `statsay.yaml`:** 12 textile families, written before the first run. "polyester" counts as nylon, because CDDA has no polyester material. That synonym is a human judgment, and the bug can only be caught with it.
- **A (generated):** every material id mapped to its display name, with no human choices.

`expected.json` (also written before the first run) requires the blanket finding at the bug commit and forbids it after the fix.

## Results (2026-10-20)

| Commit | Items | Vocabulary B | Vocabulary A |
| --- | --- | --- | --- |
| `5d32050` (PR #77272 base, bug present) | 2,787 | 120 findings on 111 items, including both blanket items. Matches `expected.json` | 690 findings on 645 items |
| `8f4168b` (PR #77272 merged) | 2,787 | 118: exactly the two blanket findings gone. Matches `expected.json` | 690 (unchanged; A never flagged the blanket, since "polyester" isn't a material name) |
| `bd94c7a` (master, 2026-10-20) | 2,813 | 98 findings on 95 items | not run |

**Vocabulary A is unusable.** "steel" in the text vs `lc_steel` in the data accounts for most of it, plus prose words that happen to be material names ("water", "sunlight", "battery", "blood"). Term vocabularies need a human, which is why term claims only warn until a vocabulary is marked `validated`.

**Vocabulary B, classified by hand** (120 findings at `5d32050`):

| Class | Findings | What it is |
| --- | --- | --- |
| Plausible contradiction | 34 | See below |
| Vocabulary gap | 44 | `kevlar_layered`/`kevlar_rigid` vs "Kevlar", `mut_fur` vs "fur", "faux-fur" (hyphen) not matching "faux fur" |
| Comparison or contrast | 25 | "more protection than your average cotton jacket", "in lieu of metal or leather armor", "Like real fur, but…" |
| Loose synonym | 11 | Nylon/spandex garments whose material is `lycra`; "cotton canvas" |
| Minor component | 6 | "tied in place with leather straps" on steel armor |

The 34 plausible contradictions are 7 distinct issues, many repeated across size variants:

| Issue | Findings | Status at master |
| --- | --- | --- |
| Electric blanket "polyester" vs cotton (the known bug) | 2 | Fixed by PR #77272 |
| XL faux-fur survivor hood says "real fur lining"; its non-XL twin says faux fur | 1 | Text rewritten later |
| Faux-fur survivor boots "Kevlar-armored", no Kevlar in materials | 3 | Text rewritten later |
| Nylon gambeson pants "made of a huge number of canvas layers" | 3 | Still present |
| Winter survivor suit "insulated leather jumpsuit", no leather in materials | 4 | Still present |
| Demi and mitten gauntlets "leather gloves with chainmail", steel only | 20 | Still present (may be a deliberate simplification) |
| Golf bag "canvas and plastic", material nylon | 1 | Still present |

At master, a new candidate appears after the survivor-gear rework: the faux-fur hoods say "lined with faux fur" but list real `fur` (3 findings).

## Vocabulary B v2: aliases, hyphens and contrast cues (M3)

`statsay-v2.yaml` uses three M3 features instead of the converter's family folding:
- `aliases` (e.g. `kevlar` also satisfied by `kevlar_layered`, `fur` by `mut_fur`)
- hyphen/space equivalence ("faux-fur" matches "faux fur")
- English `contrast_cues` ("than", "instead of", "rather than", "in lieu of", "unlike", "compared to", "as opposed to")

It was written after seeing v1's results, so it is not a blind test.

| At `5d32050` | Findings | Items | Plausible contradictions kept | Precision |
| --- | --- | --- | --- | --- |
| v1 as committed | 120 | 111 | 34 | 28% |
| v1 with hyphen equivalence only | 112 | 108 | 34 | 30% |
| v2 | 57 | 56 | 34 | 60% |

The blanket finding is still required at the bug commit and forbidden after the fix, for both v1 and v2. The 23 findings v2 still gets wrong:

| Findings | Cause |
| --- | --- |
| 7 | "nylon" sportswear whose material is `lycra` (a blend) |
| 6 | Minor parts such as leather straps |
| 5 | Loose wording on faux-fur items ("lined with fur", "imitation fur") |
| 4 | Comparisons the cues miss ("not as warm as natural fur", "Like real fur") |
| 1 | The utility kilt's "woolen kilt … cotton canvas" (2 findings) |

## What this means

- **Recall:** the one known bug is caught, at the right commit, by a vocabulary written beforehand. The catch depends on one synonym a human had to add.
- **Precision:** 34 of 120 vocabulary-B findings (28%) are plausible contradictions, worth a human look. Without the fixable vocabulary gaps, 34 of 76 (45%). Most of the remaining noise is contrast ("than", "instead of", "in lieu of").
- **Size variants:** they repeat findings. Grouping identical texts in the PR summary (M3) would turn 34 findings into 7 items to review.
- **Not done:** none of the open candidates were reported upstream.
