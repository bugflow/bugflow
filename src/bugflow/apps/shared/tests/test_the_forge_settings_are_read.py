"""The forge settings every program reads the same way."""

from collections.abc import Mapping

import pytest

from bugflow.apps.shared.forges import forge_tokens, forgejo_settings
from bugflow.forge.infrastructure.github import GitHubTokens


def read(environ: Mapping[str, str]) -> GitHubTokens:
    tokens = forge_tokens(environ)
    assert tokens is not None
    return tokens


def test_the_forge_token_is_read_before_the_github_one() -> None:
    assert read({"FORGE_TOKEN": "f", "GITHUB_TOKEN": "g"}).any_owner == "f"
    assert read({"GITHUB_TOKEN": "g"}).any_owner == "g"


def test_no_token_is_none() -> None:
    assert forge_tokens({}) is None
    assert forge_tokens({"FORGE_TOKEN": ""}) is None
    assert forge_tokens({"FORGE_TOKENS_BY_OWNER": ""}) is None


def test_a_token_for_one_owner_is_read_by_the_owner_s_name() -> None:
    tokens = read(
        {"FORGE_TOKENS_BY_OWNER": "gs-dawr=d, GS-GS=g", "FORGE_TOKEN": "f"}
    )
    assert tokens.for_owner("gs-dawr") == "d"
    assert tokens.for_owner("gs-gs") == "g"
    assert tokens.for_owner("other") == "f"


def test_tokens_by_owner_alone_are_enough() -> None:
    tokens = read({"FORGE_TOKENS_BY_OWNER": "gs-dawr=d"})
    assert tokens.any_owner is None
    assert tokens.for_owner("gs-dawr") == "d"


def test_a_pair_that_is_not_owner_equals_token_is_refused() -> None:
    for broken in ("gs-dawr", "=d", "gs-dawr="):
        with pytest.raises(ValueError, match="owner=token"):
            forge_tokens({"FORGE_TOKENS_BY_OWNER": broken})


def test_a_forgejo_needs_both_its_url_and_its_token() -> None:
    assert forgejo_settings(
        {"FORGEJO_URL": "http://forgejo.example", "FORGEJO_TOKEN": "t"}
    ) == ("http://forgejo.example", "t")
    assert forgejo_settings({"FORGEJO_URL": "http://forgejo.example"}) is None
    assert forgejo_settings({"FORGEJO_TOKEN": "t"}) is None
