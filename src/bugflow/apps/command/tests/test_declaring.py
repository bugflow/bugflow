"""Tests of ``bugflow declare``, ``allow``, ``revoke``, ``cadence`` and
``declared``.

Against a real database, because the commands exist to write rows into
one and a double would prove only that a command calls a method.
Skipped unless DATABASE_URL names a Postgres server.
"""

import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from bugflow.apps.command.command import run
from bugflow.apps.command.declaring import (
    run_allow,
    run_cadence,
    run_declare,
    run_declared,
    run_revoke,
)
from bugflow.apps.shared.boundaries import refuse_without_a_boundary
from bugflow.apps.shared.policies import reviewers_in_force
from bugflow.archive.infrastructure.sqlalchemy_archive_facts import (
    archive_registration,
)
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.method.tests.policy_files import laid_out
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.infrastructure.sqlalchemy_journal import journal
from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture(scope="module")
def shared() -> Iterator[str]:
    """One database for the tests that each name a repository of their
    own, and so do not read one another's rows."""
    for url in scratch_database():
        upgrade(url)
        yield url


def repo() -> str:
    return f"example/{uuid.uuid4()}"


class Said:
    """What one command printed, and what it refused with."""

    def __init__(self) -> None:
        self.out = io.StringIO()
        self.err = io.StringIO()

    @property
    def printed(self) -> str:
        return self.out.getvalue()

    @property
    def refused(self) -> str:
        return self.err.getvalue()


def quiet() -> io.StringIO:
    return io.StringIO()


def test_a_call_that_names_nothing_is_refused(shared: str) -> None:
    said, name = Said(), repo()
    assert run_declare(shared, name, out=said.out, err=said.err) == 2
    assert "name --boundary, --withhold or --archive" in said.refused
    assert said.printed == ""


def test_what_is_not_a_repository_is_refused(shared: str) -> None:
    said = Said()
    status = run_declare(
        shared, "example", withhold=0.1, out=said.out, err=said.err
    )
    assert status == 2
    assert "is not owner/repo" in said.refused


def test_a_repository_on_a_forgejo_is_held_by_its_forge(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, f"forgejo:{name}", withhold=0.1, out=said.out)
    assert f"forgejo:{name} withholds 10%" in said.printed


def test_declaring_a_boundary_says_where_the_period_begins(
    shared: str,
) -> None:
    said, name = Said(), repo()
    status = run_declare(
        shared, name, layer="weekly", boundary="SUN 23:30", out=said.out
    )
    assert status == 0
    assert (
        f"github:{name} begins its weekly period at SUN 23:30" in said.printed
    )


def test_a_boundary_without_a_layer_is_refused(shared: str) -> None:
    said = Said()
    status = run_declare(shared, repo(), boundary="SUN 23:30", err=said.err)
    assert status == 2
    assert "--boundary needs --layer" in said.refused


@pytest.mark.parametrize("boundary", ["60", "soon", "25:00", "XYZ 09:00"])
def test_a_boundary_that_does_not_read_is_refused_and_not_written(
    shared: str, boundary: str
) -> None:
    said, name = Said(), repo()
    status = run_declare(
        shared, name, layer="pull-request", boundary=boundary, err=said.err
    )
    assert status == 2
    assert said.refused.startswith("error: ")
    assert name not in [
        one.repo for one in SqlAlchemyLayerBoundaries(shared).declarations()
    ]


def test_withdrawing_a_boundary_leaves_the_worker_nothing_to_read(
    shared: str,
) -> None:
    said, name = Said(), repo()
    run_declare(
        shared, name, layer="weekly", boundary="SUN 23:30", out=quiet()
    )
    run_declare(shared, name, layer="weekly", boundary="", out=said.out)
    assert f"github:{name} has no boundary on weekly" in said.printed


def test_a_share_withheld_is_said_back(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, name, withhold=0.25, out=said.out)
    assert f"github:{name} withholds 25% of its warnings" in said.printed


def test_a_share_outside_nought_to_one_is_refused(shared: str) -> None:
    said = Said()
    assert run_declare(shared, repo(), withhold=1.5, err=said.err) == 2
    assert "a share is between 0 and 1" in said.refused


def test_allowing_binds_what_a_run_may_spend(shared: str) -> None:
    said, name = Said(), repo()
    assert run_allow(shared, name, usd=2.5, turns=30, out=said.out) == 0
    assert (
        f"github:{name} may spend $2.50 and 30 turns per event" in said.printed
    )
    assert "the runner is held to" in said.printed


def test_allowing_an_owner_binds_each_of_its_repositories(
    shared: str,
) -> None:
    said, owner = Said(), str(uuid.uuid4())
    status = run_allow(shared, f"{owner}/*", usd=5.0, turns=None, out=said.out)
    assert status == 0
    assert f"github:{owner}/* may spend $5.00" in said.printed
    listed = Said()
    run_declared(shared, f"{owner}/r", out=listed.out)
    assert f"github:{owner}/* may spend $5.00" in listed.printed
    elsewhere = Said()
    run_declared(shared, f"{uuid.uuid4()}/r", out=elsewhere.out)
    assert f"github:{owner}/*" not in elsewhere.printed


def test_revoking_an_owners_allowance_leaves_its_repositories(
    shared: str,
) -> None:
    said, owner = Said(), str(uuid.uuid4())
    run_allow(shared, f"{owner}/*", usd=5.0, turns=None, out=quiet())
    run_allow(shared, f"{owner}/r", usd=2.5, turns=None, out=quiet())
    run_revoke(shared, f"{owner}/*", out=said.out)
    assert f"github:{owner}/* has no allowance of its own" in said.printed
    listed = Said()
    run_declared(shared, f"{owner}/r", out=listed.out)
    assert f"github:{owner}/r may spend $2.50" in listed.printed
    assert f"github:{owner}/*" not in listed.printed


def test_what_is_no_owner_is_refused(shared: str) -> None:
    said = Said()
    status = run_allow(shared, "a/b/*", usd=5.0, turns=None, err=said.err)
    assert status == 2
    assert "is not owner/name, owner/* or either after forgejo:" in (
        said.refused
    )


def test_allowing_a_layer_and_an_agent_says_which(shared: str) -> None:
    said = Said()
    run_allow(
        shared,
        repo(),
        usd=9.0,
        turns=120,
        layer="weekly",
        agent="security",
        out=said.out,
    )
    assert "weekly security may spend $9.00" in said.printed


def test_a_period_allowance_says_how_it_is_kept(shared: str) -> None:
    said = Said()
    run_allow(shared, repo(), usd=50.0, turns=0, per="weekly", out=said.out)
    assert "per weekly" in said.printed
    assert "a run is refused once the weekly allowance is spent" in (
        said.printed
    )


def test_a_period_allowance_nothing_bounds_says_what_to_declare(
    database_url: str,
) -> None:
    said, name = Said(), repo()
    run_allow(
        database_url, name, usd=50.0, turns=None, per="weekly", out=said.out
    )
    assert "this server has no weekly boundary" in said.printed
    assert "`bugflow cadence weekly --boundary BOUNDARY`" in said.printed

    run_cadence(database_url, "weekly", "MON 00:00", out=quiet())
    again = Said()
    run_allow(
        database_url, name, usd=40.0, turns=None, per="weekly", out=again.out
    )
    assert "has no weekly boundary" not in again.printed


def test_an_allowance_may_limit_nothing_and_says_so(shared: str) -> None:
    said = Said()
    run_allow(shared, repo(), usd=None, turns=None, out=said.out)
    assert "unlimited money and unlimited turns" in said.printed


def test_one_resource_may_be_unlimited_and_another_not(shared: str) -> None:
    said = Said()
    run_allow(shared, repo(), usd=None, turns=60, out=said.out)
    assert "unlimited money and 60 turns" in said.printed


def test_a_write_says_back_the_allowance_it_wrote(shared: str) -> None:
    """A scope holds one allowance per cadence, and the one said back
    is the one this call wrote."""
    said, name = Said(), repo()
    run_allow(shared, name, usd=10.0, turns=None, per="nightly", out=quiet())
    run_allow(shared, name, usd=2.5, turns=60, out=said.out)
    assert "$2.50 and 60 turns per event" in said.printed


def test_naming_the_money_leaves_the_turns_as_they_were(shared: str) -> None:
    said, name = Said(), repo()
    run_allow(shared, name, usd=40.0, turns=None, per="nightly", out=quiet())
    run_allow(shared, name, usd=10.0, per="nightly", out=said.out)
    assert "$10.00 and unlimited turns" in said.printed


def test_naming_the_turns_leaves_the_money_as_it_was(shared: str) -> None:
    said, name = Said(), repo()
    run_allow(shared, name, usd=2.5, turns=60.0, out=quiet())
    run_allow(shared, name, turns=30.0, out=said.out)
    assert "$2.50 and 30 turns" in said.printed


def test_an_allowance_naming_no_resource_is_refused(shared: str) -> None:
    said = Said()
    assert run_allow(shared, repo(), err=said.err) == 2
    assert "name --usd" in said.refused


def test_a_new_allowance_must_name_both_resources(shared: str) -> None:
    said = Said()
    assert run_allow(shared, repo(), usd=5.0, err=said.err) == 2
    assert "nothing to leave alone" in said.refused


def test_an_allowance_per_what_is_no_cadence_is_refused(shared: str) -> None:
    said = Said()
    status = run_allow(
        shared, repo(), usd=5.0, turns=10, per="sometimes", err=said.err
    )
    assert status == 2
    assert "'sometimes' is not a cadence" in said.refused


def test_revoking_leaves_the_scopes_other_allowance(shared: str) -> None:
    said, name = Said(), repo()
    run_allow(shared, name, usd=10.0, turns=None, per="nightly", out=quiet())
    run_allow(shared, name, usd=2.5, turns=60, out=quiet())
    assert run_revoke(shared, name, per="nightly", out=said.out) == 0
    assert "no longer allowed anything per nightly" in said.printed
    assert "$2.50 and 60 turns per event" in said.printed


def test_revoking_a_scopes_last_allowance_says_what_is_left(
    shared: str,
) -> None:
    said, name = Said(), repo()
    run_allow(shared, name, usd=2.5, turns=60, out=quiet())
    run_revoke(shared, name, out=said.out)
    assert "has no allowance of its own" in said.printed


def test_revoking_what_was_never_bound_says_so_and_does_not_fail(
    shared: str,
) -> None:
    said = Said()
    assert run_revoke(shared, repo(), out=said.out) == 0
    assert "no allowance of its own" in said.printed


def test_this_server_says_where_its_own_periods_begin(
    database_url: str,
) -> None:
    said = Said()
    status = run_cadence(database_url, "weekly", "SUN 23:30", out=said.out)
    assert status == 0
    assert "this server begins its weekly periods at SUN 23:30" in said.printed
    read = Said()
    assert run_cadence(database_url, "weekly", out=read.out) == 0
    assert read.printed == said.printed


def test_what_is_no_cadence_is_refused(shared: str) -> None:
    said = Said()
    assert run_cadence(shared, "sometimes", "SUN 23:30", err=said.err) == 2
    assert "is not a cadence" in said.refused


def test_the_cadence_no_clock_fires_is_refused(shared: str) -> None:
    said = Said()
    assert run_cadence(shared, "event", "60s", err=said.err) == 2
    assert "no clock fires the event cadence" in said.refused


def test_a_boundary_the_cadence_cannot_take_is_refused(
    database_url: str,
) -> None:
    said = Said()
    status = run_cadence(
        database_url, "fortnightly", "FRI 09:00", err=said.err
    )
    assert status == 2
    assert "a fortnight begins at an instant" in said.refused
    read = Said()
    run_cadence(database_url, "fortnightly", out=read.out)
    assert "this server has no fortnightly boundary" in read.printed


def test_withdrawing_this_servers_boundary_says_what_it_costs(
    database_url: str,
) -> None:
    said = Said()
    run_cadence(database_url, "monthly", "1 00:00", out=quiet())
    run_cadence(database_url, "monthly", "", out=said.out)
    assert "every allowance counted per monthly refuses" in said.printed


def ledger() -> str:
    return str(uuid.uuid4())


def test_binding_a_ledger_says_its_archive_is_kept_here(shared: str) -> None:
    said, name, bound = Said(), repo(), ledger()
    assert run_declare(shared, name, archive=bound, out=said.out) == 0
    assert (
        f"github:{name} has the archive of ledger {bound} kept here"
        in said.printed
    )


def test_a_ledger_is_bound_to_a_scope_of_the_repository(shared: str) -> None:
    said, name, bound = Said(), repo(), ledger()
    status = run_declare(
        shared, name, archive=bound, scope="a/b", out=said.out
    )
    assert status == 0
    assert f"github:{name} at a/b has the archive of ledger {bound}" in (
        said.printed
    )


def test_the_root_is_written_as_a_dot_and_held_as_empty(shared: str) -> None:
    said, name, bound = Said(), repo(), ledger()
    run_declare(shared, name, archive=bound, scope=".", out=said.out)
    assert f"github:{name} has the archive of ledger {bound}" in said.printed


def test_binding_a_ledger_again_to_the_same_place_says_nothing_of_a_move(
    shared: str,
) -> None:
    said, name, bound = Said(), repo(), ledger()
    run_declare(shared, name, archive=bound, out=quiet())
    run_declare(shared, name, archive=bound, out=said.out)
    assert "is moved" not in said.printed
    assert f"has the archive of ledger {bound}" in said.printed


def test_binding_a_ledger_to_another_place_says_it_is_moved(
    shared: str,
) -> None:
    said, name, bound = Said(), repo(), ledger()
    run_declare(shared, name, archive=bound, scope="a", out=quiet())
    run_declare(shared, name, archive=bound, scope="b", out=said.out)
    assert (
        f"ledger {bound} was bound to github:{name} at a and is moved"
        in said.printed
    )
    assert f"github:{name} at b has the archive of ledger {bound}" in (
        said.printed
    )
    assert f"github:{name} at a has" not in said.printed


def test_a_scope_with_two_ledgers_names_the_other(shared: str) -> None:
    said, name, first, second = Said(), repo(), ledger(), ledger()
    run_declare(shared, name, archive=first, out=quiet())
    run_declare(shared, name, archive=second, out=said.out)
    assert f"github:{name} has 1 other ledger(s) bound to it: {first}" in (
        said.printed
    )


def test_a_scope_without_an_archive_is_refused(shared: str) -> None:
    said, name = Said(), repo()
    status = run_declare(shared, name, scope="a", out=said.out, err=said.err)
    assert status == 2
    assert "--scope needs --archive" in said.refused
    assert said.printed == ""


def test_what_is_no_ledger_id_is_refused_and_not_written(shared: str) -> None:
    said, name = Said(), repo()
    status = run_declare(
        shared, name, archive="not-a-ledger", out=said.out, err=said.err
    )
    assert status == 2
    assert "is no ledger id" in said.refused
    said = Said()
    run_declared(shared, name, out=said.out)
    assert "kept here" not in said.printed


def test_binding_a_ledger_is_recorded_in_the_journal(shared: str) -> None:
    name, bound = repo(), ledger()
    build = "0123456789abcdef0123456789abcdef01234567"
    run_declare(shared, name, archive=bound, build=build, out=quiet())
    engine = sa.create_engine(engine_url(shared))
    try:
        with engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(
                        archive_registration.c.ledger_id, journal.c.build
                    )
                    .join_from(
                        journal,
                        archive_registration,
                        journal.c.event_id == archive_registration.c.event_id,
                    )
                    .where(
                        journal.c.event_type == "archive.bound",
                        journal.c.repo == name,
                    )
                )
            )
    finally:
        engine.dispose()
    assert [(row.ledger_id, row.build) for row in rows] == [(bound, build)]


def test_declared_lists_the_ledgers_bound_to_a_repository(
    shared: str,
) -> None:
    said, name, bound = Said(), repo(), ledger()
    run_declare(shared, name, archive=bound, out=quiet())
    assert run_declared(shared, name, out=said.out) == 0
    assert f"github:{name} has the archive of ledger {bound} kept here" in (
        said.printed
    )


def test_the_command_binds_a_ledger(
    shared: str, capsys: pytest.CaptureFixture[str]
) -> None:
    name, bound = repo(), ledger()
    environ = {"DATABASE_URL": shared}
    assert (
        run(["declare", name, "--archive", bound, "--scope", "docs"], environ)
        == 0
    )
    printed = capsys.readouterr().out
    assert (
        f"github:{name} at docs has the archive of ledger {bound}" in printed
    )
    assert run(["declare", name, "--scope", "docs"], environ) == 2
    assert "--scope needs --archive" in capsys.readouterr().err


def test_nothing_declared_says_so(database_url: str) -> None:
    said = Said()
    assert run_declared(database_url, out=said.out) == 0
    assert said.printed == "nothing is declared and nothing is allowed\n"


def test_what_is_declared_is_read_back_whole(database_url: str) -> None:
    said, name = Said(), repo()
    where = f"github:{name}"
    run_declare(
        database_url,
        name,
        layer="pull-request",
        boundary="60s",
        withhold=0.1,
        out=quiet(),
    )
    SqlAlchemyGnomeSettings(database_url).save(
        GnomeSetting(
            forge="github",
            repo=name,
            gnome="prose",
            behaviour="advise",
            set_by="a test",
            set_at=datetime.now(UTC),
        )
    )
    run_allow(database_url, name, usd=1.0, turns=10, out=quiet())
    run_allow(database_url, usd=99.0, turns=None, per="monthly", out=quiet())
    run_cadence(database_url, "monthly", "1 00:00", out=quiet())

    assert run_declared(database_url, out=said.out) == 0

    assert said.printed.splitlines() == [
        f"{where} prose is advise, judging by default",
        f"{where} may spend $1.00 and 10 turns per event, which the "
        "runner is held to while it works",
        "everything may spend $99.00 and unlimited turns per monthly, "
        "and a run is refused once the monthly allowance is spent",
        "this server begins its monthly periods at 1 00:00",
        f"{where} begins its pull-request period at 60s",
        f"{where} withholds 10% of its warnings, drawn by finding, so "
        "what becomes of them can be measured",
    ]


def test_one_repository_is_read_back_with_what_covers_it(
    database_url: str,
) -> None:
    said, ours, theirs = Said(), repo(), repo()
    for name in (ours, theirs):
        run_declare(database_url, name, withhold=0.1, out=quiet())
        run_allow(database_url, name, usd=1.0, turns=10, out=quiet())
    run_allow(database_url, usd=5.0, turns=None, out=quiet())

    assert run_declared(database_url, ours, out=said.out) == 0

    assert theirs not in said.printed
    assert f"github:{ours} withholds 10%" in said.printed
    assert f"github:{ours} may spend $1.00" in said.printed
    assert "everything may spend $5.00" in said.printed


def test_a_repository_with_nothing_declared_says_so(
    database_url: str,
) -> None:
    said, name = Said(), repo()
    run_declare(database_url, repo(), withhold=0.1, out=quiet())
    assert run_declared(database_url, name, out=said.out) == 0
    assert said.printed == (
        f"nothing is declared and nothing is allowed for github:{name}\n"
    )


def install(directory: Path, database_url: str) -> None:
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


def test_a_window_declared_for_each_watched_repository_lets_a_worker_start(
    tmp_path: Path, database_url: str
) -> None:
    install(laid_out(tmp_path), database_url)
    in_force = reviewers_in_force(
        SqlAlchemyPolicyDeployments(database_url), ()
    )
    assert in_force is not None
    watched = ["example/repository", "forgejo:example/other"]
    boundaries = SqlAlchemyLayerBoundaries(database_url)
    with pytest.raises(ValueError, match="no boundary declared"):
        refuse_without_a_boundary(in_force.layers, watched, boundaries)

    for name in watched:
        status = run(
            ["declare", name, "--layer", "pull-request", "--boundary", "60s"],
            {"DATABASE_URL": database_url},
        )
        assert status == 0

    refuse_without_a_boundary(in_force.layers, watched, boundaries)


def test_a_boundary_the_layers_cadence_cannot_take_is_refused(
    tmp_path: Path, database_url: str
) -> None:
    """The deployment in force runs pull-request on an event, which a
    settling window bounds; the ingress raises on a phase."""
    install(laid_out(tmp_path), database_url)
    said, name = Said(), repo()
    status = run_declare(
        database_url,
        name,
        layer="pull-request",
        boundary="SUN 23:30",
        err=said.err,
    )
    assert status == 2
    assert "runs at the event cadence" in said.refused
    assert SqlAlchemyLayerBoundaries(database_url).declarations() == []


def test_a_boundary_on_a_layer_nothing_in_force_holds_is_kept(
    tmp_path: Path, database_url: str
) -> None:
    """The deployment that brings the layer is checked against it."""
    install(laid_out(tmp_path), database_url)
    said, name = Said(), repo()
    status = run_declare(
        database_url, name, layer="weekly", boundary="SUN 23:30", out=said.out
    )
    assert status == 0
    assert "begins its weekly period at SUN 23:30" in said.printed


def test_the_command_line_allows_revokes_and_reads_back(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    environ = {"DATABASE_URL": database_url}
    allowed = ["allow", "example/repository", "--usd", "2", "--no-turn-limit"]
    assert run(allowed, environ) == 0
    assert run(["allow", "--turns", "40", "--no-money-limit"], environ) == 0
    assert run(["cadence", "nightly", "--boundary", "00:00"], environ) == 0
    capsys.readouterr()

    assert run(["declared"], environ) == 0
    assert capsys.readouterr().out.splitlines() == [
        "github:example/repository may spend $2.00 and unlimited turns "
        "per event, which the runner is held to while it works",
        "everything may spend unlimited money and 40 turns per event, "
        "which the runner is held to while it works",
        "this server begins its nightly periods at 00:00",
    ]

    revoked = ["revoke", "example/repository", "--per", "event"]
    assert run(revoked, environ) == 0
    assert "has no allowance of its own" in capsys.readouterr().out


def test_a_timezone_that_is_none_is_refused_before_anything_is_written(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run(
        ["cadence", "weekly", "--boundary", "SUN 23:30"],
        {"DATABASE_URL": database_url, "PERIODS_TIMEZONE": "Nowhere/None"},
    )
    assert status == 2
    assert "is not a timezone" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["declare", "example/repository", "--withhold", "0.1"],
        ["set", "example/repository", "prose", "observe"],
        ["settings"],
        ["allow", "example/repository", "--usd", "1", "--turns", "10"],
        ["revoke", "example/repository", "--per", "event"],
        ["cadence", "weekly"],
        ["declared"],
    ],
)
def test_each_command_needs_the_database_url(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(argv, environ={}) == 2
    assert "DATABASE_URL not set" in capsys.readouterr().err


def test_archive_origin_command_normalizes_and_refuses_reassignment(
    shared: str, capsys: pytest.CaptureFixture[str]
) -> None:
    name, ledger = repo(), str(uuid.uuid4())
    environ = {"DATABASE_URL": shared}
    assert (
        run(
            [
                "declare",
                "forgejo:" + name,
                "--archive",
                ledger,
                "--archive-origin",
                f"git@ONE.example:{name}.git",
            ],
            environ,
        )
        == 0
    )
    assert f"origin one.example/{name}" in capsys.readouterr().out
    assert (
        run(
            [
                "declare",
                "forgejo:" + name,
                "--archive",
                ledger,
                "--archive-origin",
                f"two.example/{name}",
                "--withhold",
                "0.5",
            ],
            environ,
        )
        == 2
    )
    assert "ledger already has" in capsys.readouterr().err
    assert run(["declared", "forgejo:" + name], environ) == 0
    output = capsys.readouterr().out
    assert f"origin one.example/{name}" in output
    assert "withholds 50%" not in output


@pytest.mark.parametrize(
    "origin",
    ["https://host.example/wrong/path", "http://host.example/team/repo"],
)
def test_invalid_archive_origin_refuses_before_other_declarations(
    shared: str, origin: str
) -> None:
    name, said = repo(), Said()
    assert (
        run_declare(
            shared,
            name,
            archive=str(uuid.uuid4()),
            archive_origin=origin,
            withhold=0.1,
            out=said.out,
            err=said.err,
        )
        == 2
    )
    assert not said.printed
    assert run_declared(shared, name, out=said.out) == 0
    assert "nothing is declared" in said.printed


def test_archive_origin_requires_archive(shared: str) -> None:
    said = Said()
    assert (
        run_declare(
            shared,
            repo(),
            withhold=0.1,
            archive_origin="host.example/team/repo",
            err=said.err,
        )
        == 2
    )
    assert "--archive-origin needs --archive" in said.refused
