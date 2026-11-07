"""The forge settings every program reads the same way."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from bugflow.apps.shared.forges import (
    forge_tokens,
    forgejo_settings,
    github_app,
)
from bugflow.forge.infrastructure.github import GitHubTokens

PEM = "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n"


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


def test_a_github_app_is_read_with_its_key_and_installations() -> None:
    app = github_app(
        {
            "FORGE_APP_ID": "4242",
            "FORGE_APP_PRIVATE_KEY": PEM,
            "FORGE_APP_INSTALLATIONS": "GS-GS=77, gs-dawr=78",
        }
    )
    assert app is not None
    assert (app.app_id, app.private_key) == ("4242", PEM)
    assert app.installations == {"gs-gs": 77, "gs-dawr": 78}


def test_a_key_s_line_breaks_may_be_written_as_backslash_n() -> None:
    escaped = PEM.replace("\n", "\\n")
    app = github_app({"FORGE_APP_ID": "1", "FORGE_APP_PRIVATE_KEY": escaped})
    assert app is not None
    assert app.private_key == PEM


def test_a_key_may_be_read_from_a_file(tmp_path: Path) -> None:
    key_file = tmp_path / "app.pem"
    key_file.write_text(PEM)
    app = github_app(
        {"FORGE_APP_ID": "1", "FORGE_APP_PRIVATE_KEY_FILE": str(key_file)}
    )
    assert app is not None
    assert app.private_key == PEM


def test_an_app_id_without_a_key_is_refused() -> None:
    with pytest.raises(ValueError, match="FORGE_APP_PRIVATE_KEY"):
        github_app({"FORGE_APP_ID": "1"})


def test_an_installation_that_is_not_a_number_is_refused() -> None:
    with pytest.raises(ValueError, match="not a number"):
        github_app(
            {
                "FORGE_APP_ID": "1",
                "FORGE_APP_PRIVATE_KEY": PEM,
                "FORGE_APP_INSTALLATIONS": "gs-gs=seventy",
            }
        )


def test_no_app_id_is_no_app() -> None:
    assert github_app({}) is None
    blank = {"FORGE_APP_ID": " ", "FORGE_APP_PRIVATE_KEY": PEM}
    assert github_app(blank) is None


def test_an_app_alone_is_enough_and_names_its_owners() -> None:
    tokens = read(
        {
            "FORGE_APP_ID": "1",
            "FORGE_APP_PRIVATE_KEY": PEM,
            "FORGE_APP_INSTALLATIONS": "gs-gs=77",
        }
    )
    assert tokens.any_owner is None
    assert tokens.app is not None
    assert tokens.owners == frozenset({"gs-gs"})


def test_a_forgejo_needs_both_its_url_and_its_token() -> None:
    assert forgejo_settings(
        {"FORGEJO_URL": "http://forgejo.example", "FORGEJO_TOKEN": "t"}
    ) == ("http://forgejo.example", "t")
    assert forgejo_settings({"FORGEJO_URL": "http://forgejo.example"}) is None
    assert forgejo_settings({"FORGEJO_TOKEN": "t"}) is None
