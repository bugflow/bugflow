"""Tests of ``bugflow set`` and ``settings`` (ADR 008).

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


def test_a_gnome_set_on_again_whose_profile_is_gone_is_given_default(
    tmp_path: Path, database_url: str
) -> None:
    """Switched off, the gnome held strict in place no longer, so a
    deployment without it went in force (ADR 008)."""
    install(tmp_path, database_url, {"profiles.toml": PROFILES})
    environ = {"DATABASE_URL": database_url}
    run(
        ["set", "example/widgets", "prose", "observe", "--profile", "strict"],
        environ,
    )
    assert run(["set", "example/widgets", "prose", "off"], environ) == 0
    assert (
        run(
            [
                "install-policies",
                str(laid_out(tmp_path / "without-strict")),
                "--repository",
                "example/policies",
                "--commit",
                "c2",
            ],
            environ=environ,
        )
        == 0
    )

    assert run(["set", "example/widgets", "prose", "advise"], environ) == 0

    assert held(database_url) == [
        ("example/widgets", "prose", "advise", "default")
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


def test_a_gnome_two_tenants_hold_is_set_for_the_tenant_named(
    tmp_path: Path, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two tenants hold prose (ADR 012). Unnamed, the tenant cannot be
    told, so the setting is refused; named, it is that tenant's, and a
    line names the gnome for its tenant."""
    install(tmp_path, database_url, {"profiles.toml": PROFILES})
    environ = {"DATABASE_URL": database_url}
    assert (
        run(
            [
                "install-policies",
                str(laid_out(tmp_path)),
                "--repository",
                "example/site-policies",
                "--commit",
                "c1",
                "--tenant",
                "business-development",
            ],
            environ=environ,
        )
        == 0
    )
    capsys.readouterr()

    assert run(["set", "example/widgets", "prose", "observe"], environ) == 2
    assert (
        "prose is held by business-development and default; name the tenant"
        in capsys.readouterr().err
    )
    assert held(database_url) == []

    assert (
        run(
            [
                "set",
                "example/widgets",
                "prose",
                "observe",
                "--tenant",
                "business-development",
            ],
            environ,
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert (
        "github:example/widgets business-development/prose observe default, "
        "set by host:" in printed
    )
    assert [
        (one.tenant, one.gnome)
        for one in SqlAlchemyGnomeSettings(database_url).settings()
    ] == [("business-development", "prose")]
