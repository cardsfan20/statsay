"""Natural-bug reconstruction on Wesnoth data. Needs network; opt in with STATSAY_NETWORK=1."""

import os

import pytest

import wesnoth_did

pytestmark = pytest.mark.skipif(os.environ.get("STATSAY_NETWORK") != "1",
                                reason="downloads Wesnoth files; set STATSAY_NETWORK=1")


@pytest.mark.parametrize("ref", [
    "83d4b397f1de466c721e4e393b361c71fc4f5b6c",  # 1.16.11, bug #8549 present
    "8cc930666e47931b3e3436790ceeb210d4144200",  # PR #7770 merged
])
def test_findings_match_expected(ref):
    wesnoth_did.check(ref)  # exits non-zero on any missed or unexpected finding
