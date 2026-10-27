"""Tests of ``bugflow prune-webhooks``, run by its command line against
a fake of GitHub. It records nothing, and reads the watched repositories
from a database, so the command tests are skipped unless DATABASE_URL
names a Postgres server.
"""

import httpx2
import pytest

from bugflow.apps.command.command import run
from bugflow.apps.command.tests.watching import watching
from bugflow.apps.command.webhooks import PruneSettings
from bugflow.forge.tests.test_forge_conformance import FakeGitHub

OLD = "https://old.example"
NEW = "https://new.example"


def environment(
    database_url: str = "postgresql://nowhere/none",
) -> dict[str, str]:
    return {
        "DATABASE_URL": database_url,
        "INGRESS_URL": NEW + "/",
        "FORGE_TOKEN": "t",
    }


def watched(database_url: str) -> dict[str, str]:
    """The environment, with o/r and o/other watched in the database."""
    watching(database_url, "o/r", "o/other")
    return environment(database_url)


def seeded() -> FakeGitHub:
    github = FakeGitHub()
    for number, (repo, url) in enumerate(
        [
            ("r", f"{OLD}/webhooks/github"),
            ("r", f"{NEW}/webhooks/github"),
            ("r", "https://ci.example/hook"),
            ("other", f"{NEW}/webhooks/github"),
        ],
        start=1,
    ):
        github.hooks.setdefault(("o", repo), []).append(
            {
                "id": number,
                "config": {"url": url, "content_type": "json"},
                "events": ["pull_request", "issue_comment"],
                "active": True,
            }
        )
    return github


def urls(github: FakeGitHub, repo: str) -> list[str]:
    return [h["config"]["url"] for h in github.hooks[("o", repo)]]


def test_the_settings_add_the_route_to_both_addresses() -> None:
    settings = PruneSettings.from_environment(
        environment(), OLD + "/", lambda: ()
    )
    assert settings.url == "https://old.example/webhooks/github"
    assert settings.keep == "https://new.example/webhooks/github"


def test_the_old_webhook_is_deleted_and_every_other_kept(
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    github = seeded()
    transport = httpx2.MockTransport(github.handle)
    assert (
        run(
            ["prune-webhooks", OLD],
            environ=watched(database_url),
            transport=transport,
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "deleted      o/r  hook 1" in printed
    assert "absent       o/other" in printed
    assert urls(github, "r") == [
        f"{NEW}/webhooks/github",
        "https://ci.example/hook",
    ]
    assert urls(github, "other") == [f"{NEW}/webhooks/github"]


def test_a_dry_run_names_the_webhook_and_sends_no_delete(
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    github = seeded()
    methods: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        methods.append(request.method)
        return github.handle(request)

    assert (
        run(
            ["prune-webhooks", OLD, "--dry-run"],
            environ=watched(database_url),
            transport=httpx2.MockTransport(handle),
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "would delete o/r  hook 1" in printed
    assert "1 webhook(s) to delete on 2 repositories, 0 failed" in printed
    assert set(methods) == {"GET"}
    assert len(urls(github, "r")) == 3


def test_the_current_address_is_refused_before_the_forge_is_asked(
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"the forge was asked: {request.url}")

    status = run(
        ["prune-webhooks", NEW],
        environ=watched(database_url),
        transport=httpx2.MockTransport(handle),
    )
    assert status == 2
    assert "refused:" in capsys.readouterr().err


def test_a_missing_setting_is_named(
    capsys: pytest.CaptureFixture[str],
) -> None:
    environ = environment() | {"INGRESS_URL": ""}
    assert run(["prune-webhooks", OLD], environ=environ) == 2
    assert "INGRESS_URL is not set" in capsys.readouterr().err


def test_a_repository_the_forge_refuses_fails_the_run(
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    github = seeded()

    def handle(request: httpx2.Request) -> httpx2.Response:
        if "/repos/o/other/" in str(request.url):
            return httpx2.Response(403, json={"message": "forbidden"})
        return github.handle(request)

    status = run(
        ["prune-webhooks", OLD],
        environ=watched(database_url),
        transport=httpx2.MockTransport(handle),
    )
    assert status == 1
    printed = capsys.readouterr().out
    assert "failed       o/other" in printed
    assert "deleted      o/r  hook 1" in printed
