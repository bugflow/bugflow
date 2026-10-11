"""Tests of ``bugflow declare``, ``allow``, ``revoke``, ``cadence`` and
``declared``.

Against a real database, because the commands exist to write rows into
one and a double would prove only that a command calls a method.
Skipped unless DATABASE_URL names a Postgres server.
"""

import io
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

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
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.method.tests.policy_files import laid_out
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)
from bugflow.shared.infrastructure.migrations import upgrade
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


def test_declaring_says_back_what_the_database_holds(shared: str) -> None:
    said, name = Said(), repo()
    status = run_declare(
        shared,
        name,
        ["P-01", "Q-01"],
        ["evaluate-pull-request"],
        out=said.out,
    )
    assert status == 0
    assert f"github:{name} is judged on P-01, Q-01" in said.printed
    assert f"github:{name} dispatches evaluate-pull-request" in said.printed


def test_declaring_nothing_says_nothing_and_does_not_fail(shared: str) -> None:
    said, name = Said(), repo()
    assert run_declare(shared, name, [], [], out=said.out) == 0
    assert f"github:{name} is judged on nothing" in said.printed


def test_declaring_again_replaces_what_was_declared(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, name, ["P-01", "Q-01"], [], out=quiet())
    run_declare(shared, name, ["P-01"], [], out=said.out)
    assert "judged on P-01\n" in said.printed


def test_naming_one_set_leaves_the_other_as_it_was(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, name, ["P-01"], ["weekly-reading"], out=quiet())
    run_declare(shared, name, ["P-01", "P-02"], None, out=said.out)
    assert f"github:{name} is judged on P-01, P-02" in said.printed
    assert f"github:{name} dispatches weekly-reading" in said.printed


def test_a_set_is_emptied_when_that_is_asked_for(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, name, ["P-01"], ["weekly-reading"], out=quiet())
    run_declare(shared, name, None, [], out=said.out)
    assert f"github:{name} is judged on P-01" in said.printed
    assert f"github:{name} dispatches nothing" in said.printed


def test_a_call_that_names_nothing_is_refused(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, name, ["P-01"], ["weekly-reading"], out=quiet())
    assert run_declare(shared, name, out=said.out, err=said.err) == 2
    assert "name --policy" in said.refused
    assert said.printed == ""


def test_what_is_not_a_repository_is_refused(shared: str) -> None:
    said = Said()
    status = run_declare(
        shared, "example", profile="advise", out=said.out, err=said.err
    )
    assert status == 2
    assert "is not owner/repo" in said.refused


def test_a_repository_on_a_forgejo_is_held_by_its_forge(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, f"forgejo:{name}", profile="advise", out=said.out)
    assert f"forgejo:{name} is on the advise profile" in said.printed


def test_a_repository_is_bound_to_the_profile_it_declared(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, name, profile="advise", out=said.out)
    assert f"github:{name} is on the advise profile" in said.printed


def test_a_repository_nobody_bound_is_observed(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, name, ["P-01"], out=said.out)
    assert f"github:{name} is on the observe profile" in said.printed


def test_a_profile_nobody_defined_is_refused(shared: str) -> None:
    said = Said()
    status = run_declare(
        shared, repo(), profile="publish-everything", err=said.err
    )
    assert status == 2
    assert "is no profile; name one of advise, gate, observe" in said.refused


def test_binding_again_replaces_the_profile(shared: str) -> None:
    said, name = Said(), repo()
    run_declare(shared, name, profile="gate", out=quiet())
    run_declare(shared, name, profile="observe", out=said.out)
    assert f"github:{name} is on the observe profile" in said.printed


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
        ["P-01"],
        ["evaluate-pull-request"],
        profile="advise",
        layer="pull-request",
        boundary="60s",
        withhold=0.1,
        out=quiet(),
    )
    run_allow(database_url, name, usd=1.0, turns=10, out=quiet())
    run_allow(database_url, usd=99.0, turns=None, per="monthly", out=quiet())
    run_cadence(database_url, "monthly", "1 00:00", out=quiet())

    assert run_declared(database_url, out=said.out) == 0

    assert said.printed.splitlines() == [
        f"{where} is judged on P-01",
        f"{where} dispatches evaluate-pull-request",
        f"{where} is on the advise profile",
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
        run_declare(database_url, name, ["P-01"], out=quiet())
        run_allow(database_url, name, usd=1.0, turns=10, out=quiet())
    run_allow(database_url, usd=5.0, turns=None, out=quiet())

    assert run_declared(database_url, ours, out=said.out) == 0

    assert theirs not in said.printed
    assert f"github:{ours} is judged on P-01" in said.printed
    assert f"github:{ours} may spend $1.00" in said.printed
    assert "everything may spend $5.00" in said.printed


def test_a_repository_with_nothing_declared_says_so(
    database_url: str,
) -> None:
    said, name = Said(), repo()
    run_declare(database_url, repo(), ["P-01"], out=quiet())
    assert run_declared(database_url, name, out=said.out) == 0
    assert said.printed == (
        f"nothing is declared and nothing is allowed for github:{name}\n"
    )


DECLARATIONS = '[repository."example/repository"]\npolicies = ["P-01"]\n'


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


def test_under_a_deployment_that_declares_the_sets_are_refused(
    tmp_path: Path, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The deployment's file is the whole of what is judged, and the
    next deployment writes it again, so a set changed here would be
    undone."""
    directory = laid_out(tmp_path)
    (directory / "declarations.toml").write_text(DECLARATIONS)
    install(directory, database_url)
    environ = {"DATABASE_URL": database_url}
    capsys.readouterr()

    for named in (["--policy", "Q-01"], ["--no-processes"]):
        assert run(["declare", "example/repository", *named], environ) == 2
        refused = capsys.readouterr()
        assert "carries declarations.toml" in refused.err
        assert refused.out == ""

    assert (
        run(["declare", "example/repository", "--profile", "advise"], environ)
        == 0
    )
    printed = capsys.readouterr().out
    assert "github:example/repository is judged on P-01" in printed
    assert "github:example/repository is on the advise profile" in printed


def test_under_a_deployment_that_declares_nothing_the_sets_are_written(
    tmp_path: Path, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    install(laid_out(tmp_path), database_url)
    capsys.readouterr()
    status = run(
        ["declare", "example/repository", "--policy", "P-01"],
        {"DATABASE_URL": database_url},
    )
    assert status == 0
    assert "github:example/repository is judged on P-01" in (
        capsys.readouterr().out
    )


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
        ["declare", "example/repository", "--profile", "advise"],
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
