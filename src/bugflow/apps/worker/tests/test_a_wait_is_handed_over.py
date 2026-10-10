"""Tests of a wait nobody sits in: handed over, and ended by whoever is
told.

The runner says whether a completion reaches this server by a route of
its own. If one does, the activity that would have waited is handed
over, and the route that receives the completion ends it, which holds
no worker for as long as a run lasts.
"""

import pytest

from bugflow.apps.worker.evaluate_pull_request import wait_id, waits_of
from bugflow.apps.worker.review_agent import (
    AGENT_NAME,
    DEFAULT_CLONE_URL,
    managed_agent_from_environment,
    review_agent_settings,
)
from bugflow.work.infrastructure.managed_agent import ManagedAgent

CREDENTIALS = {
    "REVIEW_ANTHROPIC_API_KEY": "sk-example",
    "REVIEW_REPOSITORY_TOKEN": "read-only",
    "REVIEW_AGENT_MODEL": "a-model",
}


def test_each_turn_of_a_wait_has_a_name_of_its_own() -> None:
    """A run may answer, be asked again, and answer again, so the two
    waits cannot share an id: Temporal refuses the second."""
    assert wait_id("security", "ses-1", 1) != wait_id("security", "ses-1", 2)


def test_a_wait_is_found_by_what_the_dispatch_row_holds() -> None:
    """Whoever is told a run finished knows the agent and the remote
    id, from the dispatch row, and nothing else. Both turns of the wait
    answer to that, so nothing has to have been kept."""
    open_activities = [
        wait_id("security", "ses-1", 1),
        wait_id("security", "ses-1", 2),
    ]
    assert waits_of(open_activities, "security", "ses-1") == open_activities


def test_another_run_s_wait_is_left_alone() -> None:
    """Two agents review one pull request, and a completion is one
    run's. Ending the other's would report a review that has not
    happened."""
    assert waits_of(
        [wait_id("licence", "ses-2", 1), wait_id("security", "ses-1", 1)],
        "security",
        "ses-1",
    ) == [wait_id("security", "ses-1", 1)]


def test_a_run_whose_worker_asks_has_no_wait_to_end() -> None:
    """A worker that was not handing waits over has none open, and a
    completion for it is the signal alone."""
    assert waits_of([], "security", "ses-1") == []
    assert waits_of(["publish-findings"], "security", "ses-1") == []


def test_whether_a_completion_arrives_is_the_deployments_to_say() -> None:
    """A route nobody posts to is the same as no route, and nothing the
    runner can read tells it whether the platform was set up to post.
    So a setting says."""
    settings = review_agent_settings({"REVIEW_AGENT_MODEL": "a-model"})
    told = ManagedAgent(
        client=object(), repository_token="t", settings=settings, notified=True
    )
    asking = ManagedAgent(
        client=object(), repository_token="t", settings=settings
    )
    assert told.notifies
    assert not asking.notifies


def test_the_agent_is_named_and_reviews_with_the_model_that_was_set() -> None:
    settings = review_agent_settings({"REVIEW_AGENT_MODEL": "a-model"})
    assert (settings.name, settings.model) == (AGENT_NAME, "a-model")
    assert settings.clone_url == DEFAULT_CLONE_URL
    elsewhere = review_agent_settings(
        {
            "REVIEW_AGENT_MODEL": "a-model",
            "FORGE_CLONE_URL": "https://forge.example",
        }
    )
    assert elsewhere.clone_url == "https://forge.example"


def test_no_model_is_a_default() -> None:
    """Which model reviews is the deployment's choice, so a server that
    names none does not start with one somebody else chose."""
    with pytest.raises(ValueError, match="REVIEW_AGENT_MODEL is required"):
        review_agent_settings({})


def test_without_its_credentials_there_is_no_managed_runner() -> None:
    assert managed_agent_from_environment({}) is None
    for missing in ("REVIEW_ANTHROPIC_API_KEY", "REVIEW_REPOSITORY_TOKEN"):
        environ = {k: v for k, v in CREDENTIALS.items() if k != missing}
        assert managed_agent_from_environment(environ) is None


def test_the_managed_runner_is_built_from_its_settings() -> None:
    """Building it reaches nothing: the platform is first asked when a
    review is dispatched."""
    asking = managed_agent_from_environment(CREDENTIALS)
    told = managed_agent_from_environment(
        CREDENTIALS | {"REVIEW_COMPLETION_WEBHOOK": "1"}
    )
    assert asking is not None and told is not None
    assert asking.runner == "managed-agent"
    assert not asking.notifies
    assert told.notifies


def test_credentials_with_no_model_stop_the_program() -> None:
    environ = {
        k: v for k, v in CREDENTIALS.items() if k != "REVIEW_AGENT_MODEL"
    }
    with pytest.raises(ValueError, match="REVIEW_AGENT_MODEL is required"):
        managed_agent_from_environment(environ)


def test_the_fingerprint_follows_the_model() -> None:
    one = managed_agent_from_environment(CREDENTIALS)
    other = managed_agent_from_environment(
        CREDENTIALS | {"REVIEW_AGENT_MODEL": "b-model"}
    )
    assert one is not None and other is not None
    assert one.fingerprint != other.fingerprint
