"""Term-claim reconstruction on Cataclysm-DDA data. Needs network; opt in with STATSAY_NETWORK=1."""

import os

import pytest

import cdda_materials

pytestmark = pytest.mark.skipif(os.environ.get("STATSAY_NETWORK") != "1",
                                reason="downloads Cataclysm-DDA files; set STATSAY_NETWORK=1")


@pytest.mark.parametrize("ref", [
    "5d320508149b28da05fc4d45e4a8f2d1c7547ef6",  # base of PR #77272, bug #53277 present
    "8f4168bad451f3311496888aaa975328cfede506",  # PR #77272 merged
])
def test_findings_match_expected(ref):
    cdda_materials.check(ref)  # exits non-zero on a missed or forbidden finding
