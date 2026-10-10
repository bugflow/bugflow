"""Tests of which reviewers run at a layer, and which run nowhere.

A layer holds processes, and a process that is a review names the
reviewer it runs. So the topology decides where a reviewer runs, and
the runner stays set up for the layers that want it.
"""

from dataclasses import replace
from pathlib import Path

from bugflow.apps.worker.reviewers import (
    dispatchable,
    governing_by_default,
    policy_summaries,
    processes_on,
    reviewers_anywhere,
    reviewers_for,
    reviewers_on,
    verdict_scope,
    worth_on,
)
from bugflow.method.domain.models.pace_layer import layer, process
from bugflow.method.infrastructure.policy_files import parse_policy
from bugflow.method.infrastructure.reviewer_packages import (
    DomainSpecificReviewAgent,
)
from bugflow.method.tests.policy_files import POLICY
from bugflow.review.domain.models.review_declaration import (
    DispatchedProcesses,
)
from bugflow.review.infrastructure.in_memory_review_declaration import (
    InMemoryDispatchedProcesses,
)
from bugflow.shared.domain.values.budget import Budget

REVIEWS = process("security-review", "pull request", reviewer="security")
EVALUATES = process("evaluate-pull-request", "pull request")


def agent(agent_id: str, runner: str) -> DomainSpecificReviewAgent:
    return DomainSpecificReviewAgent(
        agent_id=agent_id,
        summary="reads the worktree",
        runner=runner,
        governs=False,
        policies=(),
        directory=Path("/nowhere"),
        description="reads the worktree",
    )


AGENTS = {
    "security": agent("security", "managed-agent"),
    "licence": agent("licence", "managed-agent"),
}


def test_a_reviewer_no_layer_holds_is_dispatched_nowhere() -> None:
    layers = {
        "pull-request": layer(
            "pull-request",
            "event",
            ["evaluate-pull-request"],
            {"evaluate-pull-request": EVALUATES},
        )
    }
    assert reviewers_on(layers, "event") == frozenset()
    assert dispatchable(AGENTS, "managed-agent", frozenset()) == {}


def test_a_layer_that_holds_a_review_dispatches_that_reviewer() -> None:
    layers = {
        "pull-request": layer(
            "pull-request",
            "event",
            ["evaluate-pull-request", "security-review"],
            {"evaluate-pull-request": EVALUATES, "security-review": REVIEWS},
        )
    }
    held = reviewers_on(layers, "event")
    assert held == frozenset({"security"})
    assert set(dispatchable(AGENTS, "managed-agent", held)) == {"security"}


def test_a_review_held_by_another_cadence_does_not_run_here() -> None:
    layers = {
        "weekly": layer(
            "weekly",
            "weekly",
            ["security-review"],
            {"security-review": REVIEWS},
        )
    }
    assert reviewers_on(layers, "event") == frozenset()
    assert reviewers_on(layers, "weekly") == frozenset({"security"})


def test_every_reviewer_any_layer_holds_is_served() -> None:
    """What decides whether a worker needs a runner, as against which
    reviewers a delivery dispatches. The two differ exactly when the
    topology puts a reviewer on a clock."""
    layers = {
        "pull-request": layer(
            "pull-request",
            "event",
            ["evaluate-pull-request"],
            {"evaluate-pull-request": EVALUATES},
        ),
        "weekly": layer(
            "weekly",
            "weekly",
            ["security-review"],
            {"security-review": REVIEWS},
        ),
    }
    assert reviewers_on(layers, "event") == frozenset()
    assert reviewers_anywhere(layers) == frozenset({"security"})


def test_a_process_may_say_what_its_work_is_worth() -> None:
    """A range review reads a week and a review of one pull request
    reads a diff. What the work is worth is declared beside the
    topology. What a deployment will spend is bound apart from it."""
    reads_the_week = process(
        "security-stocktake",
        "range",
        reviewer="security",
        worth=Budget(usd=9.0, turns=120),
    )
    assert reads_the_week.worth == Budget(usd=9.0, turns=120)
    assert REVIEWS.worth is None
    weekly = layer(
        "weekly",
        "weekly",
        ["security-stocktake", "security-review"],
        {"security-stocktake": reads_the_week, "security-review": REVIEWS},
    )
    assert worth_on(weekly) == {"security": Budget(usd=9.0, turns=120)}


def test_a_dispatchable_reviewer_carries_its_layers_declared_worth() -> None:
    """What the process declared is read when the worker starts. What
    the deployment bound is read at the dispatch, because a ceiling
    read once could not be lowered without a restart."""
    held = dispatchable(
        AGENTS,
        "managed-agent",
        frozenset({"security"}),
        layer="weekly",
        worth={"security": Budget(usd=9.0, turns=120)},
    )
    assert held["security"].worth == Budget(usd=9.0, turns=120)
    assert held["security"].layer == "weekly"


def test_a_process_that_declared_nothing_declares_nothing() -> None:
    """A reviewer whose work nobody valued is not thereby allowed a
    usual amount: it is allowed what the deployment bound, and nothing
    if that is nothing."""
    held = dispatchable(AGENTS, "managed-agent", frozenset({"security"}))
    assert held["security"].worth is None


def test_a_layers_reviewers_are_named_by_their_processes() -> None:
    """A repository declares processes and a fan-out names reviewers,
    so something holds the two together. Per layer, because two layers
    may run the same reviewer under different processes."""
    weekly = layer(
        "weekly", "weekly", ["security-review"], {"security-review": REVIEWS}
    )
    assert processes_on(weekly) == {"security": "security-review"}


def test_a_process_that_names_no_reviewer_is_not_in_the_map() -> None:
    held = layer(
        "pull-request",
        "event",
        ["evaluate-pull-request"],
        {"evaluate-pull-request": EVALUATES},
    )
    assert processes_on(held) == {}


def test_a_comment_names_a_rule_by_its_policys_summary() -> None:
    parsed = parse_policy("P-01-example.md", POLICY)
    assert policy_summaries({"prose": {"P-01": parsed}, "security": {}}) == {
        "P-01": "The description says what changed"
    }


def test_a_verdict_covers_the_declared_policies_this_server_answers() -> None:
    declares = replace(agent("prose", "judge"), policies=("P-01", "P-02"))
    assert verdict_scope({"prose": declares}, ["P-02", "P-07"]) == {
        "prose": ("P-02",)
    }


def test_a_reviewer_governs_by_default_if_its_manifest_says_so() -> None:
    governs = replace(agent("prose", "judge"), governs=True)
    assert governing_by_default({"prose": governs} | AGENTS) == ("prose",)


def declared(*processes: str) -> InMemoryDispatchedProcesses:
    held = InMemoryDispatchedProcesses()
    held.declare(
        DispatchedProcesses(forge="github", repo="o/r", processes=processes)
    )
    return held


def test_a_repository_is_dispatched_the_reviewers_it_declared() -> None:
    named = {"security": "security-review", "licence": "licence-review"}
    held = ["licence", "security"]
    assert reviewers_for(
        held, declared("security-review"), named, "github", "o/r"
    ) == ["security"]
    assert reviewers_for(held, declared(), named, "github", "o/r") == []
    assert reviewers_for(held, None, named, "github", "o/r") == held


def test_a_reviewer_no_process_names_cannot_be_declared() -> None:
    assert (
        reviewers_for(
            ["security"], declared("security-review"), {}, "github", "o/r"
        )
        == []
    )
