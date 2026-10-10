"""What a deployment may say the build is.

A full git sha or nothing. The column is read as the source tree that
produced a row, so a value that identifies no tree is refused where it
is read, at startup, rather than recorded and discovered later.
"""

import pytest

from bugflow.apps.shared.journals import BUILD_VARIABLE, build_sha

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_a_deployment_that_names_nothing_stamps_nothing() -> None:
    assert build_sha({}) is None
    assert build_sha({BUILD_VARIABLE: ""}) is None
    assert build_sha({BUILD_VARIABLE: "  "}) is None


def test_a_full_sha_is_the_build() -> None:
    assert build_sha({BUILD_VARIABLE: SHA}) == SHA
    assert build_sha({BUILD_VARIABLE: f"  {SHA}\n"}) == SHA


REFUSED = {
    "a branch name": "master",
    "a tag": "v1.2.3",
    "a build number": "4821",
    "a moving tag": "latest",
    "an abbreviated sha": SHA[:12],
    "a sha with something after it": f"{SHA}-dirty",
    "an uppercase sha": SHA.upper(),
}


@pytest.mark.parametrize("value", REFUSED.values(), ids=list(REFUSED))
def test_what_identifies_no_source_tree_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match=BUILD_VARIABLE):
        build_sha({BUILD_VARIABLE: value})
