"""Tests of deleting the webhooks left at an old address.

The rules, in the order they matter: the webhook at the address this
server answers on now is never deleted, a webhook somebody else added
is never touched, and a dry run deletes nothing.
"""

import pytest

from bugflow.forge.domain.models.webhook import Webhook
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.prune_webhooks import (
    PruneWebhooksRequest,
    PruneWebhooksResponse,
)
from bugflow.forge.dtos.reconcile_webhooks import EVENTS
from bugflow.forge.tests.test_reconcile_webhooks import FakeHooks
from bugflow.forge.usecases.prune_webhooks import (
    PruneRefusedError,
    PruneWebhooksUseCase,
    same_address,
)

OLD = "https://old.invalid/webhooks/github"
NEW = "https://new.invalid/webhooks/github"
OTHER = "https://someone-elses-ci.invalid/hook"
HERE = WatchedRepository(owner="o", repo="r")
THERE = WatchedRepository(owner="o", repo="elsewhere")


def hook(url: str, hook_id: int) -> Webhook:
    return Webhook(hook_id=hook_id, url=url, events=EVENTS, active=True)


def prune(
    hooks: FakeHooks,
    *,
    url: str = OLD,
    keep: str = NEW,
    dry_run: bool = False,
    repositories: tuple[WatchedRepository, ...] = (HERE,),
) -> PruneWebhooksResponse:
    return PruneWebhooksUseCase(hooks).execute(
        PruneWebhooksRequest(
            repositories=repositories, url=url, keep=keep, dry_run=dry_run
        )
    )


def test_the_old_addresss_webhook_goes_and_the_rest_stay() -> None:
    hooks = FakeHooks(
        {("o", "r"): [hook(OLD, 1), hook(NEW, 2), hook(OTHER, 3)]}
    )
    (outcome,) = prune(hooks).outcomes
    assert (outcome.outcome, outcome.hook_ids) == ("deleted", (1,))
    assert [h.url for h in hooks.hooks[("o", "r")]] == [NEW, OTHER]


def test_every_copy_of_the_old_webhook_goes() -> None:
    hooks = FakeHooks({("o", "r"): [hook(OLD, 1), hook(OLD, 4)]})
    (outcome,) = prune(hooks).outcomes
    assert outcome.hook_ids == (1, 4)
    assert hooks.hooks[("o", "r")] == []


def test_a_url_that_only_resembles_the_old_one_is_left_alone() -> None:
    """Matched exactly, as the reconciler matches: a trailing slash or
    another route under the same host is somebody else's webhook."""
    near = [hook(OLD + "/", 1), hook("https://old.invalid/other", 2)]
    hooks = FakeHooks({("o", "r"): list(near)})
    (outcome,) = prune(hooks).outcomes
    assert outcome.outcome == "absent"
    assert hooks.hooks[("o", "r")] == near


def test_a_dry_run_lists_what_it_would_delete_and_deletes_nothing() -> None:
    hooks = FakeHooks({("o", "r"): [hook(OLD, 1), hook(NEW, 2)]})
    (outcome,) = prune(hooks, dry_run=True).outcomes
    assert (outcome.outcome, outcome.hook_ids) == ("would delete", (1,))
    assert len(hooks.hooks[("o", "r")]) == 2
    assert not [c for c in hooks.calls if c.startswith("delete")]


@pytest.mark.parametrize(
    "url",
    [
        NEW,
        NEW + "/",
        "HTTPS://NEW.invalid/webhooks/github",
    ],
)
def test_the_current_address_is_refused_however_it_is_spelt(
    url: str,
) -> None:
    hooks = FakeHooks({("o", "r"): [hook(NEW, 2)]})
    with pytest.raises(PruneRefusedError, match="receives on"):
        prune(hooks, url=url)
    assert hooks.calls == []


def test_one_repository_failing_does_not_stop_the_others() -> None:
    hooks = FakeHooks(
        {("o", "r"): [hook(OLD, 1)], ("o", "elsewhere"): [hook(OLD, 2)]}
    )
    hooks.fail_on.add(("o", "r"))
    response = prune(hooks, repositories=(HERE, THERE))
    assert [o.outcome for o in response.outcomes] == ["failed", "deleted"]
    assert response.failed[0].detail == "the forge is down"
    assert hooks.hooks[("o", "elsewhere")] == []


def test_a_repository_named_twice_is_pruned_once() -> None:
    hooks = FakeHooks({("o", "r"): [hook(OLD, 1)]})
    response = prune(hooks, repositories=(HERE, HERE))
    assert len(response.outcomes) == 1


@pytest.mark.parametrize(
    ("one", "other", "same"),
    [
        (NEW, NEW, True),
        (
            NEW,
            NEW.upper().replace("/WEBHOOKS/GITHUB", "/webhooks/github"),
            True,
        ),
        (NEW, NEW + "/", True),
        (NEW, OLD, False),
        (NEW, "http://new.invalid/webhooks/github", False),
        (NEW, "https://new.invalid/webhooks/forgejo", False),
    ],
)
def test_what_counts_as_the_same_address(
    one: str, other: str, same: bool
) -> None:
    assert same_address(one, other) is same
