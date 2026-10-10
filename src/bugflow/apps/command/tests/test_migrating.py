"""Tests of ``bugflow migrate``, run by its command line.

Skipped unless DATABASE_URL names a Postgres server. Each test makes an
empty database of its own.
"""

from collections.abc import Iterator

import pytest

from bugflow.apps.command.command import run
from bugflow.shared.infrastructure.migrations import pending
from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture
def empty() -> Iterator[str]:
    yield from scratch_database()


def test_a_check_names_the_scripts_an_empty_database_has_not_run(
    empty: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["migrate", "--check"], environ={"DATABASE_URL": empty}) == 1
    printed = capsys.readouterr().out.splitlines()
    assert printed == pending(empty)
    assert printed[0] == "s0001_the_archive_tables"


def test_migrating_runs_the_scripts_and_a_check_then_finds_none(
    empty: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["migrate"], environ={"DATABASE_URL": empty}) == 0
    assert run(["migrate", "--check"], environ={"DATABASE_URL": empty}) == 0
    assert capsys.readouterr().out == ""


def test_no_database_url_is_an_error_before_anything_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["migrate"], environ={}) == 2
    assert "DATABASE_URL not set" in capsys.readouterr().err
