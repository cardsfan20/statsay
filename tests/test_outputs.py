import json
import shutil
import subprocess

import pytest

import fixture
from conftest import FIXTURE
from statsay.cli import main


def run_cli(args, capsys):
    try:
        main(args)
        code = 0
    except SystemExit as raised:
        code = raised.code
    return code, capsys.readouterr()


@pytest.fixture
def d01(tmp_path):
    [mutation] = [m for m in fixture.load_mutations(FIXTURE) if m["id"] == "D01"]
    fixture.materialize(FIXTURE, mutation, tmp_path / "D01")
    return tmp_path / "D01"


def test_sarif_has_regions_fixes_and_fingerprints(d01, capsys):
    code, out = run_cli(["check", str(d01), "--format", "sarif"], capsys)
    assert code == 1
    run = json.loads(out.out)["runs"][0]
    errors = [r for r in run["results"] if r["level"] == "error"]
    assert len(errors) == 4
    first = errors[0]
    assert first["locations"][0]["physicalLocation"]["region"]["startLine"] == 3
    replacement = first["fixes"][0]["artifactChanges"][0]["replacements"][0]
    assert replacement["insertedContent"]["text"] == "40"
    assert len({r["partialFingerprints"]["statsay/v1"] for r in run["results"]}) == len(run["results"])


def test_agent_output_names_the_change_and_the_fix(d01, capsys):
    code, out = run_cli(["check", str(d01), "--base", str(FIXTURE), "--changed-only", "--format", "agent"], capsys)
    lines = out.out.splitlines()
    assert lines[0] == "items.potion.heal 50 -> 40"
    assert '  FIX     en item.potion.description [9,11] "50" -> "40"' in lines
    assert not any("brew" in line for line in lines)  # unchanged entities are left out


def test_changed_only_needs_a_base(d01, capsys):
    code, out = run_cli(["check", str(d01), "--changed-only"], capsys)
    assert code == 2
    assert "--changed-only needs" in out.err


def test_patch_applies_with_git_and_clears_the_errors(d01, capsys, monkeypatch):
    monkeypatch.chdir(d01)
    code, out = run_cli(["check", ".", "--format", "patch"], capsys)
    (d01 / "fix.patch").write_text(out.out, encoding="utf-8", newline="\n")
    subprocess.run(["git", "apply", "fix.patch"], cwd=d01, check=True, capture_output=True)
    assert run_cli(["check", "."], capsys)[0] == 0


def test_summary_merges_identical_texts(tmp_path, capsys):
    (tmp_path / "statsay.yaml").write_text("""
data_sources: [{id: items, path: items.json}]
localization: [{path: strings.csv, format: csv, key_column: key, locales: [en]}]
bindings: [{convention: "item.{id}.description", source: items, watched_fields: [heal]}]
claims: {heal: {kind: number, anchors: {en: ["HP"]}}}
""", encoding="utf-8")
    (tmp_path / "items.json").write_text(json.dumps([{"id": i, "heal": 40} for i in ("a", "xl_a", "xs_a")]),
                                         encoding="utf-8")
    (tmp_path / "strings.csv").write_text("key,en\n" + "".join(
        f"item.{i}.description,Restores 50 HP.\n" for i in ("a", "xl_a", "xs_a")), encoding="utf-8")
    code, out = run_cli(["check", str(tmp_path), "--format", "summary"], capsys)
    assert out.out.count("text says 50, data says 40") == 1
    assert "3 entities, **heal**" in out.out
    assert "3 strings with the same text" in out.out


def test_summary_groups_identical_term_findings_across_entities(tmp_path, capsys):
    (tmp_path / "statsay.yaml").write_text("""
data_sources: [{id: items, path: items.json}]
localization: [{path: strings.csv, format: csv, key_column: key, locales: [en]}]
bindings: [{convention: "item.{id}.description", source: items, watched_fields: [material]}]
claims: {material: {kind: enum, vocabulary: {canvas: {en: [canvas]}, nylon: {en: [nylon]}}}}
""", encoding="utf-8")
    (tmp_path / "items.json").write_text(json.dumps([{"id": i, "material": ["nylon"]} for i in ("p", "xl_p", "xs_p")]),
                                         encoding="utf-8")
    (tmp_path / "strings.csv").write_text("key,en\n" + "".join(
        f"item.{i}.description,Made of canvas layers.\n" for i in ("p", "xl_p", "xs_p")), encoding="utf-8")
    code, out = run_cli(["check", str(tmp_path), "--format", "summary"], capsys)
    assert out.out.count("text says canvas") == 1
    assert "3 strings with the same text" in out.out


def test_baseline_suppresses_reviewed_findings_and_keeps_notes(d01, capsys):
    baseline = d01 / ".statsay-baseline.json"
    assert run_cli(["baseline", str(d01)], capsys)[0] == 0
    data = json.loads(baseline.read_text(encoding="utf-8"))
    data["findings"][0]["note"] = "accepted: tutorial rewrite pending"
    baseline.write_text(json.dumps(data), encoding="utf-8")

    code, out = run_cli(["check", str(d01), "--baseline", str(baseline)], capsys)
    assert code == 0
    assert "6 baselined findings suppressed" in out.out

    run_cli(["baseline", str(d01)], capsys)  # regenerate: the note survives
    notes = [e["note"] for e in json.loads(baseline.read_text(encoding="utf-8"))["findings"]]
    assert "accepted: tutorial rewrite pending" in notes


def test_new_finding_after_baseline_still_fails(d01, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    run_cli(["baseline", str(FIXTURE), "--output", str(baseline)], capsys)  # clean fixture: 2 info notes
    code, out = run_cli(["check", str(d01), "--baseline", str(baseline)], capsys)
    assert code == 1
    assert "2 baselined findings suppressed" in out.out
