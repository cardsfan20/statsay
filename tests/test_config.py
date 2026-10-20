import pytest

from statsay import StatsayError
from statsay.config import load_config, term_key

BASE = """
data_sources: [{id: items, path: items.json, entity_id_field: id}]
localization: [{path: strings.csv, format: csv, key_column: key, locales: [en]}]
bindings: [{convention: "item.{id}.description", source: items, watched_fields: [flag]}]
"""


def write(tmp_path, claims):
    (tmp_path / "statsay.yaml").write_text(BASE + claims, encoding="utf-8")
    return tmp_path


def test_yaml_boolean_vocabulary_keys_match_data_booleans(tmp_path):
    config = load_config(write(tmp_path, """
claims:
  flag:
    kind: enum
    validated: true
    vocabulary:
      false: {en: ["cannot fly"]}
      true: {en: ["can fly"]}
"""))
    rule = config.claims["flag"]
    assert set(rule.vocabulary) == {term_key(False), term_key(True)} == {"false", "true"}
    assert rule.validated


def test_one_term_naming_two_values_is_rejected(tmp_path):
    with pytest.raises(StatsayError, match="names both"):
        load_config(write(tmp_path, """
claims:
  flag:
    kind: enum
    vocabulary:
      a: {en: ["Fly"]}
      b: {en: ["fly"]}
"""))


def test_enum_without_vocabulary_is_rejected(tmp_path):
    with pytest.raises(StatsayError, match="vocabulary"):
        load_config(write(tmp_path, "claims:\n  flag: {kind: enum}\n"))
