from statsay.extract import HIGH, LOW, extract_number_claims, extract_term_claims, normalize

HEAL = {"heal": ("HP",)}
REGEN_EN = {"heal": ("HP",), "duration": ("second", "seconds")}
REGEN_JA = {"heal": ("HP",), "duration": ("秒",)}


def summary(text, anchors):
    return [(c.value, c.fields, c.confidence) for c in extract_number_claims(text, anchors)]


def test_anchored_number_is_high_confidence():
    assert summary("Restores 50 HP to one ally.", HEAL) == [(50, ("heal",), HIGH)]
    assert summary("味方単体のHPを50回復する。", HEAL) == [(50, ("heal",), HIGH)]


def test_full_width_digits_are_normalized_and_spans_point_into_original_text():
    text = "味方単体のHPを１５０回復する。"
    [claim] = extract_number_claims(text, HEAL)
    assert claim.value == 150
    assert text[claim.span[0]:claim.span[1]] == "１５０"


def test_nearest_anchor_wins_between_two_fields():
    assert summary("Restores 5 HP per second for 10 seconds.", REGEN_EN) == [
        (5, ("heal",), HIGH), (10, ("duration",), HIGH),
    ]
    assert summary("10秒間、毎秒HPを5回復する。", REGEN_JA) == [
        (10, ("duration",), HIGH), (5, ("heal",), HIGH),
    ]


def test_equal_distance_to_two_fields_is_a_low_confidence_tie():
    anchors = {"attack_up": ("%",), "revive_percent": ("%",)}
    assert summary("Grants 20% now.", anchors) == [(20, ("attack_up", "revive_percent"), LOW)]


def test_number_in_a_name_is_not_tied_when_another_number_sits_between():
    claims = summary("A Level 3 brew that restores 80 HP to one ally.", HEAL)
    assert claims == [(3, (), None), (80, ("heal",), HIGH)]


def test_clause_break_blocks_an_anchor():
    claims = summary("レベル3の薬湯。味方単体のHPを80回復する。", HEAL)
    assert claims == [(3, (), None), (80, ("heal",), HIGH)]


def test_single_number_with_single_field_needs_no_anchor():
    assert summary("Heals 25.", {"heal": ()}) == [(25, ("heal",), HIGH)]
    assert summary("Heals 25, twice: 10.", {"heal": ()}) == [(25, (), None), (10, (), None)]


def test_ranges_and_multipliers_are_low_confidence():
    assert summary("Restores 10-20 HP.", HEAL) == [(10, (), None), (20, ("heal",), LOW)]
    assert summary("Restores x2 HP.", HEAL) == [(2, ("heal",), LOW)]


def test_anchor_words_respect_ascii_word_boundaries():
    assert summary("Gains 5 HPS.", {"heal": ("HP",), "speed": ()}) == [(5, (), None)]
    assert summary("Restores 5 hp.", HEAL) == [(5, ("heal",), HIGH)]


def test_thousands_separator_and_decimals():
    assert summary("Restores 1,000 HP.", HEAL) == [(1000, ("heal",), HIGH)]
    assert summary("Restores 1.5 HP.", HEAL) == [(1.5, ("heal",), HIGH)]


def test_normalize_keeps_offsets():
    norm, origin = normalize("ＨＰ５０")
    assert norm == "HP50"
    assert origin == [0, 1, 2, 3, 4]


BATTLE_EN = {"battle_use": {"false": ("cannot target air", "cannot be used in battle"),
                            "true": ("target air", "can be used in battle")}}


def terms(text, vocabulary):
    return [(c.values, c.confidence) for c in extract_term_claims(text, vocabulary)]


def test_longest_term_wins_so_negations_beat_the_phrase_they_contain():
    assert terms("Fires torpedoes. Cannot target air.", BATTLE_EN) == [({"battle_use": "false"}, HIGH)]
    assert terms("Can target air units.", BATTLE_EN) == [({"battle_use": "true"}, HIGH)]


def test_each_term_occurrence_is_a_claim():
    cures = {"cures": {"poison": ("poison",), "sleep": ("sleep",)}}
    assert terms("Cures poison and sleep.", cures) == [({"cures": "poison"}, HIGH), ({"cures": "sleep"}, HIGH)]


def test_terms_respect_ascii_word_boundaries_but_not_japanese_ones():
    assert terms("A poisonous brew.", {"cures": {"poison": ("poison",)}}) == []
    assert terms("毒と睡眠を治す。", {"cures": {"poison": ("毒",), "sleep": ("睡眠",)}}) == [
        ({"cures": "poison"}, HIGH), ({"cures": "sleep"}, HIGH),
    ]


def test_term_shared_by_two_fields_is_low_confidence():
    vocabulary = {"element": {"fire": ("fire",)}, "resist": {"fire": ("fire",)}}
    assert terms("Deals fire damage.", vocabulary) == [({"element": "fire", "resist": "fire"}, LOW)]


def test_term_span_points_into_original_text():
    text = "味方全体のHPを回復"
    [claim] = extract_term_claims(text, {"scope": {"all_allies": ("味方全体",)}})
    assert text[claim.span[0]:claim.span[1]] == "味方全体"
