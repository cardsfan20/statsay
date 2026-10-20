import shutil

import pytest

import fixture
from conftest import FIXTURE, RPGMAKER
from statsay import StatsayError
from statsay.cli import main
from statsay.config import load_config
from statsay.engine import run
from statsay.init import init, render


def initialized(source, tmp_path):
    project = tmp_path / source.name
    shutil.copytree(source, project)
    (project / "statsay.yaml").unlink()
    (project / "statsay.yaml").write_text(render(init(project)), encoding="utf-8")
    return project


def alerts(project, base=None):
    from statsay.revisions import directory_reader
    config = load_config(project)
    findings = run(config, base=directory_reader(config, base) if base else None).findings
    return [f for f in findings if f.severity != "info"]


def test_generic_project_gets_conventions_and_mined_anchors(tmp_path):
    project = initialized(FIXTURE, tmp_path)
    config = load_config(project)
    assert [c.pattern for c in config.conventions] == ["item.{id}.description"]
    assert "HP" in config.claims["heal"].anchors["en"]
    assert "秒間" in config.claims["duration"].anchors["ja"]
    assert "price" not in config.conventions[0].watched_fields  # no description states a price
    assert alerts(project) == []


def test_rpgmaker_project_gets_database_fields_terms_and_plugin_translations(tmp_path):
    project = initialized(RPGMAKER, tmp_path)
    config = load_config(project)
    assert {s.format for s in config.localization} == {"data", "csv"}
    assert "攻撃力" in config.claims["grow"].anchors["ja"]  # from System.json terms
    assert config.claims["mp_rate"].unit == "percent"
    assert set(config.claims["scope"].vocabulary) >= {"7"}
    assert alerts(project) == []


@pytest.mark.parametrize("source, mutation_id", [(FIXTURE, "D01"), (FIXTURE, "D02"), (RPGMAKER, "R01"),
                                                 (RPGMAKER, "R02"), (RPGMAKER, "RT2")])
def test_init_config_catches_planted_numeric_bugs(tmp_path, source, mutation_id):
    clean = initialized(source, tmp_path)
    [mutation] = [m for m in fixture.load_mutations(source) if m["id"] == mutation_id]
    head = tmp_path / mutation_id
    fixture.materialize(clean, mutation, head)
    shutil.copy2(clean / "statsay.yaml", head / "statsay.yaml")
    # Init finds key patterns, not one-off exceptions like the toy game's tutorial hint.
    expected = {(e["key"], e["locale"]) for e in mutation["expected"]
                if e["rule"] == "value_mismatch" and not e["key"].startswith("tutorial.")}
    found = {(f.key, f.locale) for f in alerts(head) if f.rule == "value_mismatch" and f.severity == "error"}
    assert expected <= found


def test_init_refuses_to_overwrite_without_force(tmp_path, capsys):
    project = tmp_path / "toy"
    shutil.copytree(FIXTURE, project)
    with pytest.raises(SystemExit) as raised:
        main(["init", str(project)])
    assert raised.value.code == 2
    assert "already exists" in capsys.readouterr().err


def test_init_explains_what_it_could_not_find(tmp_path):
    (tmp_path / "notes.txt").write_text("nothing here", encoding="utf-8")
    with pytest.raises(StatsayError, match="found no RPG Maker database"):
        init(tmp_path)
