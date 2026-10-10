"""Tests of ``bugflow webhooks``: its settings, and the command run by
its command line against a fake of GitHub and a real database.

The command tests are skipped unless DATABASE_URL names a Postgres
server.
"""

import httpx2
import pytest
import sqlalchemy as sa

from bugflow.apps.command.command import run
from bugflow.apps.command.webhooks import REQUIRED, HookSettings
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.tests.test_forge_conformance import FakeGitHub
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_journal import journal

BUILD = "4" * 40


def environment(database_url: str = "postgresql://nowhere/none") -> dict:  # type: ignore[type-arg]
    return {
        "WATCHED_REPOSITORIES": "o/r, o/other",
        "INGRESS_URL": "https://ingress.example/",
        "WEBHOOK_SECRET": "s3cret",
        "FORGE_TOKEN": "t",
        "DATABASE_URL": database_url,
        "BUILD_SHA": BUILD,
    }


def test_the_settings_are_read_and_the_route_is_added() -> None:
    settings = HookSettings.from_environment(environment())
    assert settings.repositories == (
        WatchedRepository(owner="o", repo="r"),
        WatchedRepository(owner="o", repo="other"),
    )
    assert settings.url == "https://ingress.example/webhooks/github"
    assert (settings.secret, settings.token) == ("s3cret", "t")


@pytest.mark.parametrize("name", ["INGRESS_URL", "WEBHOOK_SECRET"])
def test_a_missing_address_or_secret_is_named(name: str) -> None:
    environ = environment() | {name: ""}
    with pytest.raises(ValueError, match=name):
        HookSettings.from_environment(environ)


def test_every_variable_the_command_reads_is_listed() -> None:
    """A deployment's check reads the list to see the container the
    command runs in supplies each one."""
    assert set(REQUIRED) <= set(environment())


def test_a_repository_on_forgejo_cannot_be_registered() -> None:
    environ = environment() | {"WATCHED_REPOSITORIES": "forgejo:o/r"}
    with pytest.raises(ValueError, match="only github"):
        HookSettings.from_environment(environ)


def test_no_repositories_need_no_token() -> None:
    environ = environment() | {"WATCHED_REPOSITORIES": "", "FORGE_TOKEN": ""}
    assert HookSettings.from_environment(environ).repositories == ()


def test_the_command_names_the_missing_setting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    environ = environment() | {"INGRESS_URL": ""}
    assert run(["webhooks"], environ=environ) == 2
    assert "INGRESS_URL is not set" in capsys.readouterr().err


def test_no_database_url_is_an_error_before_anything_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["webhooks"], environ=environment("")) == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_the_command_registers_a_hook_and_records_it(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub()
    transport = httpx2.MockTransport(github.handle)
    environ = environment(database_url)
    assert run(["webhooks"], environ=environ, transport=transport) == 0
    printed = capsys.readouterr().out
    assert "reconciled against https://ingress.example/webhooks/github" in (
        printed
    )
    assert "created    o/r" in printed
    assert "created    o/other" in printed
    (hook,) = github.hooks[("o", "r")]
    assert hook["config"]["url"] == "https://ingress.example/webhooks/github"

    assert run(["webhooks"], environ=environ, transport=transport) == 0
    assert "unchanged  o/r" in capsys.readouterr().out

    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(journal.c.repo, journal.c.build).where(
                        journal.c.event_type == "webhook.reconciled"
                    )
                )
            )
    finally:
        engine.dispose()
    assert (("o/r", BUILD) in rows) and (("o/other", BUILD) in rows)
