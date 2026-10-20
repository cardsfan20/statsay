"""E1 on every mutation fixture: each case must match its expected findings exactly."""

import pytest

import e1
from conftest import FIXTURE, RPGMAKER

CASES = [(fixture.name, case) for fixture in (FIXTURE, RPGMAKER) for case in e1.cases(fixture)]


@pytest.mark.parametrize("case", [case for _, case in CASES],
                         ids=[f"{name}-{case['id']}-{case['mode']}" for name, case in CASES])
def test_case_matches_expectation(case):
    result = e1.score(case)
    assert not result["missed"], f"missed: {sorted(result['missed'], key=str)}"
    assert not result["extra"], f"unexpected: {sorted(result['extra'], key=str)}"
    assert not result["problems"], result["problems"]


def test_every_planted_bug_is_in_scope():
    planted = [case for _, case in CASES if case["category"] in ("data_only", "text_only")]
    assert [case["id"] for case in planted if case["mode"] == "diff" and not case["planted"]] == []
    # These have no claim to check, so only diff mode can see them.
    assert [case["id"] for case in planted if case["mode"] == "current" and not case["planted"]] == [
        "D10", "R06", "R07",
    ]
