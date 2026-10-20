import json
import shutil
import subprocess

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


def test_clean_fixture_passes_and_reports_coverage(capsys):
    code, out = run_cli(["check", str(FIXTURE), "--format", "json"], capsys)
    assert code == 0
    payload = json.loads(out.out)
    assert payload["coverage"] == [{
        "source": "items", "rule": "item.{id}.description", "entities": 15, "bound": 14,
        "unbound": ["items.antidote"],
    }]
    assert payload["summary"] == {"error": 0, "warning": 0, "info": 2}


def test_planted_bug_fails_ci(tmp_path, capsys):
    [mutation] = [m for m in fixture.load_mutations(FIXTURE) if m["id"] == "D01"]
    fixture.materialize(FIXTURE, mutation, tmp_path / "D01")
    code, out = run_cli(["check", str(tmp_path / "D01")], capsys)
    assert code == 1
    assert "heal: text says 50, data says 40" in out.out


def test_fail_on_threshold(capsys):
    assert run_cli(["check", str(FIXTURE), "--fail-on", "info"], capsys)[0] == 1
    assert run_cli(["check", str(FIXTURE), "--fail-on", "never"], capsys)[0] == 0


def test_missing_config_exits_2(tmp_path, capsys):
    code, out = run_cli(["check", str(tmp_path)], capsys)
    assert code == 2
    assert "no config found" in out.err


def test_bad_config_exits_2(tmp_path, capsys):
    (tmp_path / "statsay.yaml").write_text("data_sources: []\nbindings: []\n", encoding="utf-8")
    code, out = run_cli(["check", str(tmp_path)], capsys)
    assert code == 2
    assert "localization" in out.err


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
                   cwd=cwd, check=True, capture_output=True)


def test_base_ref_reads_the_base_revision_from_git(tmp_path, capsys):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    [mutation] = [m for m in fixture.load_mutations(FIXTURE) if m["id"] == "D10"]
    fixture.materialize(FIXTURE, mutation, tmp_path / "head")
    shutil.copy2(tmp_path / "head" / "data" / "items.json", repo / "data" / "items.json")

    code, out = run_cli(["check", str(repo), "--base-ref", "HEAD", "--format", "json"], capsys)
    changed = [f for f in json.loads(out.out)["findings"] if f["rule"] == "watched_field_changed"]
    assert code == 0  # warnings only
    assert {(f["locale"], f["field"], f["old"], f["new"]) for f in changed} == {
        ("en", "heal", 9999, 5000), ("ja", "heal", 9999, 5000),
    }


def test_unknown_base_ref_exits_2(tmp_path, capsys):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    git(repo, "init", "-q")
    code, out = run_cli(["check", str(repo), "--base-ref", "no-such-branch"], capsys)
    assert code == 2
    assert "not a Git commit" in out.err
