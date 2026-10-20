"""ci/run-check.sh against a simulated pull request: a bare origin, a shallow clone, a feature branch."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import fixture
from conftest import FIXTURE, ROOT

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false", *args],
                   cwd=cwd, check=True, capture_output=True)


def test_run_check_uses_the_pr_base_and_reports_before_failing(tmp_path):
    git(tmp_path, "init", "-q", "--bare", "origin.git")
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), "seed")
    for name in ("statsay.yaml", "data", "locales"):
        source = FIXTURE / name
        (shutil.copytree if source.is_dir() else shutil.copy2)(source, seed / name)
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "base")
    git(seed, "push", "-q", "origin", "HEAD:main")

    [mutation] = [m for m in fixture.load_mutations(FIXTURE) if m["id"] == "D10"]
    fixture.materialize(FIXTURE, mutation, tmp_path / "d10")
    git(tmp_path, "clone", "-q", "--depth", "1", (tmp_path / "origin.git").as_uri(), "pr")
    pr = tmp_path / "pr"
    git(pr, "checkout", "-qb", "feature")
    shutil.copy2(tmp_path / "d10" / "data" / "items.json", pr / "data" / "items.json")
    git(pr, "commit", "-qam", "nerf elixir")

    env = dict(os.environ, PR_BASE="main", INPUT_FAIL_ON="warning",
               GITHUB_OUTPUT=str(tmp_path / "out.txt"), GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
               PATH=os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")]))
    done = subprocess.run([BASH, str(ROOT / "ci" / "run-check.sh")], cwd=pr, env=env, capture_output=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, done.stderr

    outputs = dict(line.split("=", 1) for line in (tmp_path / "out.txt").read_text().splitlines())
    assert outputs == {"exit-code": "1", "sarif": "statsay.sarif"}
    # D10 is only visible in diff mode, so this proves the PR base was used.
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "**heal** 9999 → 5000" in summary
    rules = {r["ruleId"] for r in json.loads((pr / "statsay.sarif").read_text(encoding="utf-8"))["runs"][0]["results"]}
    assert "watched_field_changed" in rules
