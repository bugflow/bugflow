"""Tests of ``bugflow poll``, run by its command line."""

import pytest

from bugflow.apps.command.command import run


def test_the_poll_command_names_the_missing_setting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["poll", "--once"], environ={}) == 2
    assert "POLL_REPOSITORIES is not set" in capsys.readouterr().err
