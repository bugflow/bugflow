"""Tests of how the reviewing part of the worker is built from its
settings and the deployment in force.

The tests that take ``database_url`` are skipped unless DATABASE_URL
names a Postgres server.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from temporalio import activity

from bugflow.apps.shared.deploying import checks_from
from bugflow.apps.shared.policies import ReviewersInForce, reviewers_in_force
from bugflow.apps.worker import (
    backfill,
    evaluate_pull_request,
    pull_request,
    stocktake,
)
from bugflow.apps.worker.forge_by_reference import forge_from_environment
from bugflow.apps.worker.parts import WorkerParts
from bugflow.apps.worker.review import (
    WORKFLOWS,
    activities_from_environment,
    answered_policies,
    checked_policies,
    declared_policies,
    object_store_from_environment,
    parts_from_environment,
    policy_classes,
    refuse_without_a_forge,
    reviewing_from_environment,
    watched_repositories,
)
from bugflow.apps.worker.reviewers import verdict_scope
from bugflow.apps.worker.tests.deployed import WIDGETS, put_in_force
from bugflow.apps.worker.worker import JudgeRates
from bugflow.forge.domain.errors import ForgeError
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.method.infrastructure.reviewer_packages import (
    DomainSpecificReviewAgent,
    parse_agent,
)
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.review.domain.models.enforcement import ADVISE, OBSERVE
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.infrastructure.in_memory_enforcement import (
    InMemoryEnforcement,
)
from bugflow.review.infrastructure.sqlalchemy_enforcement import (
    SqlAlchemyEnforcement,
)
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.null_object_store import NullObjectStore
from bugflow.shared.infrastructure.s3_object_store import S3ObjectStore
from bugflow.work.infrastructure.stub_agent import StubAgent

ON_GITHUB = PullRequestRef(owner="example-org", repo="widgets", number=1)
ON_FORGEJO = PullRequestRef(
    forge="forgejo", owner="example-org", repo="widgets", number=1
)
FORGEJO = {"FORGEJO_URL": "http://forgejo.test", "FORGEJO_TOKEN": "f"}

#: What the layer a delivery fires holds, in the tests that are about
#: the runner and not about where a reviewer is held.
HELD = frozenset({"security"})


def test_without_a_token_evaluations_fail_with_a_clear_reason() -> None:
    forge = forge_from_environment({})
    with pytest.raises(ForgeError, match="set FORGE_TOKEN"):
        forge.fetch_snapshot(ON_GITHUB)


def test_each_pull_request_is_read_from_the_forge_its_reference_names() -> (
    None
):
    forge = forge_from_environment({"FORGE_TOKEN": "t"} | FORGEJO)
    assert isinstance(forge.forge_for(ON_FORGEJO), ForgejoForge)
    assert isinstance(forge.forge_for(ON_GITHUB), GitHubForge)


@pytest.mark.parametrize("missing", ["FORGEJO_URL", "FORGEJO_TOKEN"])
def test_without_both_forgejo_settings_its_pull_requests_fail_clearly(
    missing: str,
) -> None:
    environ = {"FORGE_TOKEN": "t"} | FORGEJO
    del environ[missing]
    forge = forge_from_environment(environ)
    with pytest.raises(ForgeError, match="set FORGEJO_URL and FORGEJO_TOKEN"):
        forge.fetch_snapshot(ON_FORGEJO)
    assert isinstance(forge.forge_for(ON_GITHUB), GitHubForge)


def test_a_closed_conversation_is_asked_of_the_pull_requests_own_forge() -> (
    None
):
    forge = forge_from_environment({"FORGE_TOKEN": "t"})
    with pytest.raises(ForgeError, match="no Forgejo configured"):
        forge.reactions(ON_FORGEJO, 41)
    with pytest.raises(ForgeError, match="no Forgejo configured"):
        forge.state(ON_FORGEJO)


@pytest.mark.parametrize("token", [None, ""])
def test_publishing_without_a_token_does_not_start(token: str | None) -> None:
    """One refusal at startup, and not every evaluation saying the same
    thing."""
    environ: dict[str, str] = {}
    if token is not None:
        environ["FORGE_TOKEN"] = token
    enforcement = InMemoryEnforcement()
    enforcement.bind(*WIDGETS, ADVISE)
    with pytest.raises(ValueError, match="github:example-org/widgets is"):
        refuse_without_a_forge(environ, enforcement)


def test_publishing_with_only_a_forgejo_configured_starts() -> None:
    enforcement = InMemoryEnforcement()
    enforcement.bind("forgejo", "example-org/widgets", ADVISE)
    refuse_without_a_forge(FORGEJO, enforcement)


def test_an_observed_repository_needs_no_forge() -> None:
    """Observing is the default and publishes nothing, so a deployment
    that has decided about no repository starts without a forge."""
    enforcement = InMemoryEnforcement()
    enforcement.bind(*WIDGETS, OBSERVE)
    refuse_without_a_forge({}, enforcement)


STORE = {
    "TOKENOMIC_S3_ENDPOINT": "https://objects.invalid",
    "TOKENOMIC_S3_BUCKET": "calls",
    "TOKENOMIC_S3_ACCESS_KEY": "a",
    "TOKENOMIC_S3_SECRET_KEY": "s",
}


def test_content_is_kept_only_if_all_four_settings_are_given() -> None:
    assert isinstance(object_store_from_environment(STORE), S3ObjectStore)
    for missing in STORE:
        partial = {k: v for k, v in STORE.items() if k != missing}
        store = object_store_from_environment(partial)
        assert isinstance(store, NullObjectStore), missing


def test_watched_repositories_are_named_as_the_journal_names_them() -> None:
    assert watched_repositories(
        {
            "WATCHED_REPOSITORIES": "example-org/widgets, "
            "forgejo:example-org/gadgets,"
        }
    ) == ("github:example-org/widgets", "forgejo:example-org/gadgets")
    assert watched_repositories({}) == ()
    with pytest.raises(ValueError, match="not owner/repo"):
        watched_repositories({"WATCHED_REPOSITORIES": "widgets"})


def test_each_class_has_its_own_rate_or_the_shared_one() -> None:
    rates = JudgeRates.from_environment(
        {
            "JUDGE_REQUESTS_PER_SECOND": "2",
            "JUDGE_REQUESTS_PER_SECOND_SMALL": "5",
            "JUDGE_REQUESTS_PER_SECOND_LARGE": "0",
        }
    )
    assert rates.reviews == 2.0
    assert rates.classes == {"small": 5.0, "medium": 2.0, "large": None}
    unset = JudgeRates.from_environment({})
    assert set(unset.classes.values()) == {unset.reviews}


MANAGED = {
    "REVIEW_RUNNER": "managed-agent",
    "REVIEW_ANTHROPIC_API_KEY": "sk-example-sessions",
    "REVIEW_REPOSITORY_TOKEN": "a-read-only-token",
    "REVIEW_AGENT_MODEL": "a-session-model",
}


def managed_agents(
    runner: str = "managed-agent",
) -> dict[str, DomainSpecificReviewAgent]:
    return {
        "security": parse_agent(
            Path("security/reviewer.md"),
            f"agent_id: security\nsummary: s\nrunner: {runner}\n"
            "governs: no\n---\n\nProse.\n",
        )
    }


def test_no_runner_named_dispatches_nothing() -> None:
    assert reviewing_from_environment({}, {}, HELD) == ({}, None)
    assert reviewing_from_environment({}, managed_agents(), HELD) == (
        {},
        None,
    )


def test_a_runner_this_worker_does_not_have_stops_it() -> None:
    with pytest.raises(ValueError, match="this worker has"):
        reviewing_from_environment(
            {"REVIEW_RUNNER": "another"}, managed_agents("another"), HELD
        )


def test_the_managed_runner_is_built_from_its_settings() -> None:
    reviewers, agent = reviewing_from_environment(
        MANAGED, managed_agents(), HELD
    )
    assert list(reviewers) == ["security"]
    assert agent is not None and agent.runner == "managed-agent"


def test_a_managed_runner_short_of_its_settings_dispatches_nothing() -> None:
    for missing in ("REVIEW_ANTHROPIC_API_KEY", "REVIEW_REPOSITORY_TOKEN"):
        environ = {k: v for k, v in MANAGED.items() if k != missing}
        _, agent = reviewing_from_environment(environ, managed_agents(), HELD)
        assert agent is None, f"{missing} was not required"


def test_a_managed_runner_with_no_model_named_stops_the_worker() -> None:
    unnamed = {k: v for k, v in MANAGED.items() if k != "REVIEW_AGENT_MODEL"}
    with pytest.raises(ValueError, match="REVIEW_AGENT_MODEL is required"):
        reviewing_from_environment(unnamed, managed_agents(), HELD)


def test_the_managed_runner_never_falls_back_to_the_forge_token() -> None:
    """Anything in the runner's container can act on the repository
    with the token's permissions, so only the token meant for it is
    used."""
    environ = {
        **{k: v for k, v in MANAGED.items() if k != "REVIEW_REPOSITORY_TOKEN"},
        "FORGE_TOKEN": "a-token-that-can-write",
    }
    _, agent = reviewing_from_environment(environ, managed_agents(), HELD)
    assert agent is None


def test_a_reviewer_held_only_by_a_clock_still_gets_its_runner() -> None:
    """A runner built from what a delivery dispatches alone would be
    missing for a reviewer the topology holds only on a clock, and its
    stocktake would have nobody to ask."""
    reviewers, agent = reviewing_from_environment(
        MANAGED, managed_agents(), frozenset(), frozenset({"security"})
    )
    assert reviewers == {}
    assert agent is not None


def test_a_reviewer_no_layer_holds_gets_no_runner() -> None:
    _, agent = reviewing_from_environment(
        MANAGED, managed_agents(), frozenset(), frozenset()
    )
    assert agent is None


def test_a_runner_the_caller_built_is_used_in_place_of_the_setting() -> None:
    stub = StubAgent()
    reviewers, agent = reviewing_from_environment(
        {"REVIEW_RUNNER": "managed-agent"},
        managed_agents(stub.runner),
        HELD,
        agent=stub,
    )
    assert list(reviewers) == ["security"]
    assert agent is stub


def in_force(database_url: str) -> ReviewersInForce:
    put_in_force(database_url)
    reviewers = reviewers_in_force(
        SqlAlchemyPolicyDeployments(database_url), checks_from({})
    )
    assert reviewers is not None
    return reviewers


def test_what_is_judged_and_checked_is_read_from_the_deployment(
    database_url: str,
) -> None:
    reviewers = in_force(database_url)

    checked = checked_policies(reviewers.agents)
    assert {
        policy_id: (one.agent_id, one.clause)
        for policy_id, one in checked.items()
    } == {"P-09": ("prose", "EX-21")}
    assert answered_policies(reviewers) == {"P-01", "P-09"}
    assert declared_policies(reviewers) == ("P-01",)
    assert policy_classes(reviewers) == {"P-01": "small"}


def test_a_checked_policy_stays_in_its_reviewers_verdict(
    database_url: str,
) -> None:
    """A checked policy runs beside the judge, and counts toward its
    reviewer's verdict as a judged one does."""
    reviewers = in_force(database_url)
    scope = verdict_scope(reviewers.agents, answered_policies(reviewers))
    assert scope["prose"] == ("P-01", "P-09")


def test_a_worker_with_no_runner_says_it_starts_no_reviewer(
    database_url: str,
) -> None:
    built = activities_from_environment(
        {"DATABASE_URL": database_url}, in_force(database_url)
    )
    assert built.review_agents() == []
    assert built.reviewing == "starts no review agent: none is configured"
    assert built.judge_port is None


def test_a_worker_says_what_each_layer_starts(database_url: str) -> None:
    """The example topology holds the security reviewer on the weekly
    layer and no reviewer on a delivery."""
    built = activities_from_environment(
        {"DATABASE_URL": database_url, **MANAGED}, in_force(database_url)
    )
    assert built.reviewing == (
        "starts no review agent on a pull request;"
        " weekly layer starts security"
    )
    assert built.review_agents() == []
    assert built.stocktake_reviewers("weekly") == ["security"]
    assert built.stocktake_reviewers("weekly", *WIDGETS) == ["security"]
    assert built.stocktake_reviewers("weekly", "github", "a/b") == []


def test_a_worker_names_the_reviewer_it_cannot_start(
    database_url: str,
) -> None:
    """The runner is named and its credentials are missing."""
    built = activities_from_environment(
        {"DATABASE_URL": database_url, "REVIEW_RUNNER": "managed-agent"},
        in_force(database_url),
    )
    assert built.reviewing == (
        "starts no review agent: security cannot be started, because"
        " the runner is not configured"
    )


def test_the_worker_collects_at_close(database_url: str) -> None:
    built = activities_from_environment(
        {"DATABASE_URL": database_url, "FORGE_TOKEN": "t"},
        in_force(database_url),
    )
    assert built.collect_at_close in built.all()
    assert built.collecting == "collecting conversations at close"


def test_what_a_repository_is_reviewed_for_is_its_declaration(
    database_url: str,
) -> None:
    """With no judge, the checked policy is still answered, and only
    for the repository that declared it."""
    built = activities_from_environment(
        {"DATABASE_URL": database_url}, in_force(database_url)
    )
    assert [one.policy_id for one in built.review_policies(*WIDGETS)] == [
        "P-09"
    ]
    assert built.review_policies("github", "example-org/gadgets") == []


def names(activities: tuple[Callable[..., Any], ...]) -> set[str]:
    """The names these activities are registered under."""
    return {
        activity._Definition.must_from_callable(one).name or ""
        for one in activities
    }


def called_by_the_workflows() -> set[str]:
    """Every activity name a review workflow's module defines."""
    return {
        value
        for module in (
            evaluate_pull_request,
            pull_request,
            backfill,
            stocktake,
        )
        for name, value in vars(module).items()
        if name.endswith("_ACTIVITY") and isinstance(value, str)
    }


def test_without_a_database_nothing_is_reviewed() -> None:
    parts = parts_from_environment({})
    assert parts == WorkerParts(
        lines=("reviews nothing: DATABASE_URL is not set",)
    )


def test_with_no_deployment_in_force_the_part_only_watches_for_one(
    database_url: str,
) -> None:
    """Nothing is registered and nothing is refused, whatever else is
    or is not set up."""
    SqlAlchemyEnforcement(database_url).bind(*WIDGETS, ADVISE)

    parts = parts_from_environment(
        {
            "DATABASE_URL": database_url,
            "WATCHED_REPOSITORIES": "example-org/widgets",
            "PERIODS_TIMEZONE": "Nowhere/At-All",
            "REVIEW_RUNNER": "another",
        }
    )

    assert not parts.serves
    assert parts.before_serving == ()
    assert parts.schedules == ()
    assert len(parts.watchers) == 1
    assert parts.lines == (
        "reviews nothing: no policy deployment is in force",
    )


def test_with_a_deployment_in_force_the_review_workflows_are_registered(
    database_url: str,
) -> None:
    put_in_force(database_url)

    parts = parts_from_environment({"DATABASE_URL": database_url})

    assert parts.workflows == WORKFLOWS
    assert set(parts.assessing) == {"small", "medium", "large"}
    assert {
        name for held in parts.assessing.values() for name in names(held)
    } == {evaluate_pull_request.ASSESS_ACTIVITY}
    assert len(parts.schedules) == len(parts.watchers) == 1
    assert parts.lines[0].startswith(
        f"reviews under example-org/pull-request-policies at {'c' * 40}, "
        "content "
    )
    assert parts.lines[1:] == (
        "holds the layers pull-request, weekly",
        "judges nothing: LITELLM_MASTER_KEY is not set",
        "starts no review agent: none is configured",
        "collecting conversations at close",
    )
    for refuse in parts.before_serving:
        refuse()


def test_every_activity_a_workflow_calls_is_registered_under_its_name(
    database_url: str,
) -> None:
    """A recorded history holds an activity's name, so the names the
    workflows call are the names the activities must answer to."""
    put_in_force(database_url)

    parts = parts_from_environment({"DATABASE_URL": database_url})

    registered = names(parts.activities) | names(parts.judging)
    assert registered == called_by_the_workflows()


def test_a_deployment_that_publishes_with_no_forge_is_refused(
    database_url: str,
) -> None:
    put_in_force(database_url)
    SqlAlchemyEnforcement(database_url).bind(*WIDGETS, ADVISE)

    refused = parts_from_environment({"DATABASE_URL": database_url})
    with pytest.raises(ValueError, match="without a forge to publish to"):
        for refuse in refused.before_serving:
            refuse()

    served = parts_from_environment(
        {"DATABASE_URL": database_url, "FORGE_TOKEN": "t"}
    )
    for refuse in served.before_serving:
        refuse()


def test_a_watched_repository_with_no_boundary_is_refused(
    database_url: str,
) -> None:
    put_in_force(database_url)
    environ = {
        "DATABASE_URL": database_url,
        "WATCHED_REPOSITORIES": "example-org/widgets",
    }

    refused = parts_from_environment(environ)
    with pytest.raises(ValueError, match="no boundary declared") as raised:
        for refuse in refused.before_serving:
            refuse()
    assert "github:example-org/widgets on weekly" in str(raised.value)

    boundaries = SqlAlchemyLayerBoundaries(database_url)
    for layer, boundary in (("weekly", "SUN 23:30"), ("pull-request", "60s")):
        boundaries.declare(
            LayerBoundary(
                forge="github",
                repo="example-org/widgets",
                layer=layer,
                boundary=boundary,
            )
        )
    for refuse in parts_from_environment(environ).before_serving:
        refuse()


def test_a_setting_that_cannot_be_used_stops_a_worker_that_reviews(
    database_url: str,
) -> None:
    put_in_force(database_url)
    with pytest.raises(ValueError, match="PERIODS_TIMEZONE"):
        parts_from_environment(
            {"DATABASE_URL": database_url, "PERIODS_TIMEZONE": "Nowhere/None"}
        )
