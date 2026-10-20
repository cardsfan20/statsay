import json

from statsay.config import load_config
from statsay.engine import run

CONFIG = """
data_sources: [{id: units, path: units.json, entity_id_field: id}]
localization: [{path: strings.csv, format: csv, key_column: key, locales: [en, ja]}]
bindings: [{convention: "unit.{id}.description", source: units, watched_fields: [targets_air]}]
claims:
  targets_air:
    kind: enum
    validated: %s
    vocabulary:
      false: {en: ["cannot target air"], ja: ["空中を攻撃できない"]}
      true: {en: ["targets air"], ja: ["空中も攻撃できる"]}
"""


def make(tmp_path, validated):
    (tmp_path / "statsay.yaml").write_text(CONFIG % validated, encoding="utf-8")
    (tmp_path / "units.json").write_text(json.dumps([{"id": "retusa", "targets_air": True}]), encoding="utf-8")
    (tmp_path / "strings.csv").write_text(
        "key,en,ja\nunit.retusa.description,Fires torpedoes. Cannot target air.,魚雷を撃つ。空中を攻撃できない。\n",
        encoding="utf-8")
    return run(load_config(tmp_path))


def test_flag_contradiction_warns_until_vocabulary_is_validated(tmp_path):
    findings = make(tmp_path, "false").findings
    assert [(f.rule, f.severity, f.locale, f.claimed, f.actual) for f in findings] == [
        ("enum_term_mismatch", "warning", "en", "false", True),
        ("enum_term_mismatch", "warning", "ja", "false", True),
    ]


def test_validated_vocabulary_fails_ci(tmp_path):
    assert {f.severity for f in make(tmp_path, "true").findings} == {"error"}


def test_stray_numbers_are_not_reported_when_the_binding_tracks_no_numbers(tmp_path):
    (tmp_path / "statsay.yaml").write_text(CONFIG % "false", encoding="utf-8")
    (tmp_path / "units.json").write_text(json.dumps([{"id": "retusa", "targets_air": False}]), encoding="utf-8")
    (tmp_path / "strings.csv").write_text(
        "key,en,ja\nunit.retusa.description,Fires 2 torpedoes. Cannot target air.,魚雷を2発撃つ。空中を攻撃できない。\n",
        encoding="utf-8")
    assert run(load_config(tmp_path)).findings == []


def test_vocabulary_aliases_and_contrast_cues(tmp_path):
    (tmp_path / "statsay.yaml").write_text("""
data_sources: [{id: items, path: items.json}]
localization: [{path: strings.csv, format: csv, key_column: key, locales: [en]}]
bindings: [{convention: "item.{id}.description", source: items, watched_fields: [material]}]
contrast_cues: {en: {before: ["than"]}}
claims:
  material:
    kind: enum
    vocabulary:
      kevlar: {en: ["kevlar"], aliases: [kevlar_layered, kevlar_rigid]}
      cotton: {en: ["cotton"]}
""", encoding="utf-8")
    (tmp_path / "items.json").write_text(json.dumps([
        {"id": "hood", "material": ["kevlar_layered", "leather"]},
        {"id": "vest", "material": ["nylon"]},
    ]), encoding="utf-8")
    (tmp_path / "strings.csv").write_text(
        "key,en\nitem.hood.description,An armored Kevlar hood.\n"
        "item.vest.description,\"Lighter than Kevlar, and cotton-lined.\"\n", encoding="utf-8")
    findings = run(load_config(tmp_path)).findings
    # hood: "Kevlar" is satisfied by the alias. vest: "than Kevlar" is a comparison; "cotton" is a real claim.
    assert [(f.key, f.claimed) for f in findings] == [("item.vest.description", "cotton")]
