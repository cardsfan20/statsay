"""E1 on the toy game: every case must match its expected findings exactly."""

import pytest

import e1
from conftest import FIXTURE

CASES = list(e1.cases(FIXTURE))


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_case_matches_expectation(case):
    result = e1.score(case)
    assert not result["missed"], f"missed: {sorted(result['missed'])}"
    assert not result["extra"], f"unexpected: {sorted(result['extra'])}"
    assert not result["problems"], result["problems"]


def test_every_planted_bug_is_in_scope_or_explicitly_deferred():
    planted = [case for case in CASES if case["category"] in ("data_only", "text_only")]
    deferred = [case["id"] for case in planted if not case["planted"]]
    # D03 (enum scope) and D10 (no claim, diff mode) need M2 rules.
    assert deferred == ["D03", "D10"]
