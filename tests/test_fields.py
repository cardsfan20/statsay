import json

import pytest

from statsay import StatsayError
from statsay.adapters import load_entities
from statsay.config import DataSource, load_config
from statsay.fields import derive, _ABSENT
from conftest import RPGMAKER

ITEM = {"effects": [{"code": 11, "value1": 0.5, "value2": 40}, {"code": 22, "dataId": 4},
                    {"code": 22, "dataId": 10}],
        "damage": {"formula": "a.atk * 4"}}


def field(name):
    return load_config(RPGMAKER).fields[name]


def test_filtered_path_reads_one_value():
    assert derive(ITEM, field("heal")) == 40


def test_fraction_is_scaled_to_percent_without_float_noise():
    assert derive({"effects": [{"code": 12, "value1": 0.3}]}, field("mp_rate")) == 30


def test_several_matches_give_a_list_and_none_leave_the_field_absent():
    assert derive(ITEM, field("cures")) == [4, 10]
    assert derive(ITEM, field("atk_up")) is _ABSENT


def test_formula_is_copied_not_evaluated():
    assert derive({"damage": {"formula": "1 + 1"}}, field("damage_formula")) == "1 + 1"


def test_rpgmaker_loader_skips_null_and_nameless_slots(tmp_path):
    path = tmp_path / "Items.json"
    path.write_text(json.dumps([None, {"id": 1, "name": "Potion"}, {"id": 2, "name": ""}]), encoding="utf-8")
    entities = load_entities(DataSource("items", path, format="rpgmaker"))
    assert list(entities) == ["1"]


def test_claims_on_a_formula_field_are_rejected(tmp_path):
    (tmp_path / "statsay.yaml").write_text("""
data_sources: [{id: skills, path: Skills.json, format: rpgmaker}]
localization: [{format: data, source: skills, field: description, key: "skill.{id}.description", locale: ja}]
bindings: [{convention: "skill.{id}.description", source: skills, watched_fields: [f]}]
fields: {f: {source: skills, path: damage.formula, kind: formula}}
claims: {f: {kind: number}}
""", encoding="utf-8")
    with pytest.raises(StatsayError, match="never evaluated"):
        load_config(tmp_path)
