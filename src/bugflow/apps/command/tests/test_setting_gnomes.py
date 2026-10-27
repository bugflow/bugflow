"""Tests of ``bugflow set``, ``settings`` and ``settle`` (ADR 008).

Against a real database, because the commands exist to write rows into
one. Skipped unless DATABASE_URL names a Postgres server.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa

from bugflow.apps.command.command import run
from bugflow.method.tests.policy_files import MANIFEST, POLICY, laid_out
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
    gnome_setting_change,
)
from bugflow.shared.infrastructure.database import engine_url

#: A second policy for the reviewer the files hold, so a profile can
#: name fewer than all of them.
SECOND = {
    "prose/reviewer.md": MANIFEST.replace(
        "policies: P-01\n", "policies: P-01, P-02\n"
    ),
    "prose/policies/P-02-other.md": POLICY.replace(
        "policy_id: P-01", "policy_id: P-02"
    ),
}

PROFILES = '[profile.prose.strict]\npolicies = ["P-01"]\n'


def install(
    tmp_path: Path, database_url: str, more: dict[str, str] | None = None
) -> None:
    directory = laid_out(tmp_path)
    for path, text in (SECOND | (more or {})).items():
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_text(text)
    status = run(
        [
            "install-policies",
            str(directory),
            "--repository",
            "example/policies",
            "--commit",
            "c1",
        ],
        environ={"DATABASE_URL": database_url},
    )
    assert status == 0


def held(database_url: str) -> list[tuple[str, str, str, str]]:
    return [
        (one.repo, one.gnome, one.behaviour, one.profile)
        for one in SqlAlchemyGnomeSettings(database_url).settings()
    ]


def test_setting_a_gnome_records_it_and_says_what_is_held(
    tmp_path: Path, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    install(tmp_path, database_url, {"profiles.toml": PROFILES})
    environ = {"DATABASE_URL": database_url}
    capsys.readouterr()

    assert run(["set", "example/widgets", "prose", "observe"], environ) == 0
    assert (
        run(
            [
                "set",
                "example/widgets",
                "prose",
                "advise",
                "--profile",
                "strict",
            ],
            environ,
        )
        == 0
    )

    printed = capsys.readouterr().out
    assert (
        "github:example/widgets prose advise strict, set by host:" in printed
    )
    assert held(database_url) == [
        ("example/widgets", "prose", "advise", "strict")
    ]
    engine = sa.create_engine(engine_url(database_url))
    with engine.connect() as connection:
        changes = connection.execute(
            sa.select(
                gnome_setting_change.c.behaviour,
                gnome_setting_change.c.was_behaviour,
            ).order_by(gnome_setting_change.c.behaviour)
        ).all()
    assert [tuple(one) for one in changes] == [
        ("advise", "observe"),
        ("observe", None),
    ]


def test_a_gnome_keeps_its_profile_when_only_its_behaviour_is_set(
    tmp_path: Path, database_url: str
) -> None:
    install(tmp_path, database_url, {"profiles.toml": PROFILES})
    environ = {"DATABASE_URL": database_url}
    run(
        ["set", "example/widgets", "prose", "observe", "--profile", "strict"],
        environ,
    )

    assert run(["set", "example/widgets", "prose", "gate"], environ) == 0

    assert held(database_url) == [
        ("example/widgets", "prose", "gate", "strict")
    ]


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        (["other-gnome", "observe"], "'other-gnome' is not a gnome"),
        (
            ["prose", "observe", "--profile", "lenient"],
            "'lenient' is not a profile of prose",
        ),
    ],
)
def test_a_gnome_or_profile_not_in_force_is_refused(
    tmp_path: Path,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    problem: str,
) -> None:
    install(tmp_path, database_url)
    capsys.readouterr()

    status = run(
        ["set", "example/widgets", *args], {"DATABASE_URL": database_url}
    )

    assert status == 2
    assert problem in capsys.readouterr().err
    assert held(database_url) == []


def test_settling_makes_a_setting_from_each_declaration(
    tmp_path: Path, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """One repository declares the reviewer's every policy, which is its
    default, and one declares P-01 alone, which is strict. The first is
    on the advise profile; the second was bound to none, so is
    observed."""
    install(
        tmp_path,
        database_url,
        {
            "profiles.toml": PROFILES,
            "declarations.toml": (
                '[repository."example/widgets"]\n'
                'policies = ["P-01", "P-02"]\n'
                '[repository."example/gears"]\n'
                'policies = ["P-01"]\n'
            ),
        },
    )
    environ = {"DATABASE_URL": database_url}
    assert (
        run(["declare", "example/widgets", "--profile", "advise"], environ)
        == 0
    )
    capsys.readouterr()

    assert run(["settle", "--check"], environ) == 0
    assert "github:example/gears prose would be observe strict" in (
        capsys.readouterr().out
    )
    assert held(database_url) == []

    assert run(["settle"], environ) == 0
    assert held(database_url) == [
        ("example/gears", "prose", "observe", "strict"),
        ("example/widgets", "prose", "advise", "default"),
    ]
    capsys.readouterr()

    assert run(["settle"], environ) == 0
    assert "is already set; left as it is" in capsys.readouterr().out


def test_settling_refuses_a_declaration_no_profile_matches(
    tmp_path: Path, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    install(
        tmp_path,
        database_url,
        {
            "declarations.toml": (
                '[repository."example/widgets"]\npolicies = ["P-02"]\n'
            )
        },
    )
    capsys.readouterr()

    status = run(["settle"], {"DATABASE_URL": database_url})

    said = capsys.readouterr()
    assert status == 2
    assert "github:example/widgets declares P-02 of prose" in said.out
    assert "nothing is settled" in said.err
    assert held(database_url) == []
