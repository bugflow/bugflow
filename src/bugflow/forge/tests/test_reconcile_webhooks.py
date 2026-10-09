"""Tests of reconciling webhooks.

The most important rule is the first one tested: a webhook this server did
not create is never touched. A repository's other webhooks belong to
whoever added them.
"""

from datetime import UTC, datetime

import pytest

from bugflow.forge.domain.errors import (
    ForgeRejectedError,
    ForgeUnavailableError,
)
from bugflow.forge.domain.models.webhook import Webhook
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.reconcile_webhooks import (
    EVENTS,
    ReconcileWebhooksRequest,
    ReconcileWebhooksResponse,
)
from bugflow.forge.tests.journal import QueryableJournal
from bugflow.forge.usecases.reconcile_webhooks import ReconcileWebhooksUseCase
from bugflow.shared.domain.values.correlation import Correlation

URL = "https://ingress.invalid/webhooks/github"
OTHER = "https://someone-elses-ci.invalid/hook"
RUN = Correlation(workflow_id="webhooks/sync", run_id="r1")
HERE = WatchedRepository(owner="o", repo="r")
THERE = WatchedRepository(owner="o", repo="elsewhere")


class FakeHooks:
    def __init__(
        self, seeded: dict[tuple[str, str], list[Webhook]] | None = None
    ):
        self.hooks = dict(seeded or {})
        self.calls: list[str] = []
        self.fail_on: set[tuple[str, str]] = set()
        self.error: Exception = ForgeUnavailableError("the forge is down")
        self._next = 1
        # Old name -> new name. The fake forge answers for the old name as if
        # it were the new repository, as real forges do.
        self.renamed: dict[tuple[str, str], tuple[str, str]] = {}

    def _at(self, owner: str, repo: str) -> tuple[str, str]:
        return self.renamed.get((owner, repo), (owner, repo))

    def _check(self, owner: str, repo: str) -> None:
        if (owner, repo) in self.fail_on:
            raise self.error

    def list_hooks(self, owner: str, repo: str) -> list[Webhook]:
        self._check(owner, repo)
        self.calls.append(f"list {owner}/{repo}")
        return list(self.hooks.get(self._at(owner, repo), []))

    def current_name(self, owner: str, repo: str) -> str | None:
        self._check(owner, repo)
        now_owner, now_repo = self._at(owner, repo)
        return now_owner + "/" + now_repo

    def create_hook(self, owner, repo, url, secret, events):  # type: ignore[no-untyped-def]
        self._check(owner, repo)
        self.calls.append(f"create {owner}/{repo} {url}")
        self._next += 1
        hook = Webhook(hook_id=self._next, url=url, events=events, active=True)
        self.hooks.setdefault((owner, repo), []).append(hook)
        return hook

    def update_hook(self, owner, repo, hook_id, url, secret, events):  # type: ignore[no-untyped-def]
        self._check(owner, repo)
        self.calls.append(f"update {owner}/{repo} {hook_id}")
        hook = Webhook(hook_id=hook_id, url=url, events=events, active=True)
        self.hooks[(owner, repo)] = [
            hook if h.hook_id == hook_id else h
            for h in self.hooks[(owner, repo)]
        ]
        return hook

    def delete_hook(self, owner: str, repo: str, hook_id: int) -> None:
        self._check(owner, repo)
        self.calls.append(f"delete {owner}/{repo} {hook_id}")
        at = self._at(owner, repo)
        self.hooks[at] = [
            h for h in self.hooks.get(at, []) if h.hook_id != hook_id
        ]


class FakeJournal(QueryableJournal):
    """The test journal, with the one extra question this use case asks."""

    def __init__(
        self, remembered: list[tuple[str, str]] | None = None
    ) -> None:
        super().__init__()
        self._remembered = remembered or []

    def repositories_with(self, event_type: str) -> list[tuple[str, str]]:
        return list(self._remembered)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 17, tzinfo=UTC)


def reconcile(
    hooks: FakeHooks,
    journal: FakeJournal,
    repositories: tuple[WatchedRepository, ...] = (HERE,),
) -> ReconcileWebhooksResponse:
    use_case = ReconcileWebhooksUseCase(hooks, journal, journal, FixedClock())
    return use_case.execute(
        ReconcileWebhooksRequest(
            repositories=repositories,
            url=URL,
            secret="s3cret",
            correlation=RUN,
        )
    )


def ours(url: str = URL, hook_id: int = 1) -> Webhook:
    return Webhook(hook_id=hook_id, url=url, events=EVENTS, active=True)


# --- other people's webhooks are not touched ----------------------------


def test_a_hook_this_system_did_not_add_is_left_alone() -> None:
    """Another service's webhook is left exactly as it is. Changing it could
    break that service, and there would be no way to put it back.
    """
    theirs = Webhook(
        hook_id=9, url=OTHER, events=frozenset({"push"}), active=True
    )
    hooks = FakeHooks({("o", "r"): [theirs]})
    reconcile(hooks, FakeJournal())
    assert theirs in hooks.hooks[("o", "r")]
    assert not [c for c in hooks.calls if c.startswith(("delete", "update"))]


def test_withdrawing_leaves_every_other_hook_where_it_was() -> None:
    theirs = Webhook(
        hook_id=9, url=OTHER, events=frozenset({"push"}), active=True
    )
    hooks = FakeHooks({("o", "elsewhere"): [theirs, ours(hook_id=3)]})
    journal = FakeJournal(remembered=[("github", "o/elsewhere")])
    reconcile(hooks, journal, repositories=())
    assert hooks.hooks[("o", "elsewhere")] == [theirs]


# --- declaring ----------------------------------------------------------


def test_a_repository_with_no_hook_of_ours_gets_one() -> None:
    hooks = FakeHooks()
    response = reconcile(hooks, FakeJournal())
    assert [o.outcome for o in response.outcomes] == ["created"]
    assert hooks.hooks[("o", "r")][0].url == URL


def test_running_twice_changes_nothing_the_second_time() -> None:
    """This runs on every deployment, so a second run with nothing to fix must
    change nothing.
    """
    hooks = FakeHooks()
    reconcile(hooks, FakeJournal())
    hooks.calls.clear()
    response = reconcile(hooks, FakeJournal())
    assert [o.outcome for o in response.outcomes] == ["unchanged"]
    assert hooks.calls == ["list o/r"]


def test_a_hook_with_the_wrong_events_is_corrected() -> None:
    stale = Webhook(
        hook_id=1, url=URL, events=frozenset({"push"}), active=True
    )
    hooks = FakeHooks({("o", "r"): [stale]})
    response = reconcile(hooks, FakeJournal())
    assert [o.outcome for o in response.outcomes] == ["updated"]
    assert hooks.hooks[("o", "r")][0].events == EVENTS


def test_an_inactive_hook_is_corrected() -> None:
    """A forge can switch a webhook off after repeated failures. It then sends
    nothing, although it still appears in the list. It is switched back on.
    """
    off = Webhook(hook_id=1, url=URL, events=EVENTS, active=False)
    hooks = FakeHooks({("o", "r"): [off]})
    response = reconcile(hooks, FakeJournal())
    assert [o.outcome for o in response.outcomes] == ["updated"]
    assert hooks.hooks[("o", "r")][0].active


def test_a_duplicate_hook_is_dropped_so_deliveries_arrive_once() -> None:
    hooks = FakeHooks({("o", "r"): [ours(hook_id=1), ours(hook_id=2)]})
    response = reconcile(hooks, FakeJournal())
    assert [h.hook_id for h in hooks.hooks[("o", "r")]] == [1]
    assert "duplicate" in response.outcomes[0].detail


def test_a_repository_named_twice_is_reconciled_once() -> None:
    hooks = FakeHooks()
    response = reconcile(hooks, FakeJournal(), repositories=(HERE, HERE))
    assert len(response.outcomes) == 1


# --- withdrawing --------------------------------------------------------


def test_a_repository_no_longer_declared_has_its_hook_removed() -> None:
    hooks = FakeHooks({("o", "elsewhere"): [ours(hook_id=3)]})
    journal = FakeJournal(remembered=[("github", "o/elsewhere")])
    response = reconcile(hooks, journal, repositories=(HERE,))
    assert ("o", "elsewhere") in hooks.hooks
    assert hooks.hooks[("o", "elsewhere")] == []
    assert {o.outcome for o in response.outcomes} == {"created", "removed"}


def test_a_repository_still_declared_is_not_withdrawn() -> None:
    hooks = FakeHooks({("o", "r"): [ours()]})
    journal = FakeJournal(remembered=[("github", "o/r")])
    response = reconcile(hooks, journal, repositories=(HERE,))
    assert [o.outcome for o in response.outcomes] == ["unchanged"]


def test_a_renamed_repository_keeps_its_hook() -> None:
    """The journal remembers a repository under its old name, the request
    lists it under its new name, and the forge answers for both. The
    webhook must be kept, not removed for the sake of the old name.
    """
    hooks = FakeHooks({("o", "r"): [ours()]})
    hooks.renamed[("o", "old")] = ("o", "r")
    journal = FakeJournal(remembered=[("github", "o/old")])
    response = reconcile(hooks, journal, repositories=(HERE,))
    assert hooks.hooks[("o", "r")] == [ours()]
    assert not any(call.startswith("delete") for call in hooks.calls)
    assert sorted(o.outcome for o in response.outcomes) == [
        "renamed",
        "unchanged",
    ]


def test_a_rename_is_matched_without_case() -> None:
    hooks = FakeHooks({("o", "r"): [ours()]})
    hooks.renamed[("o", "old")] = ("O", "R")
    journal = FakeJournal(remembered=[("github", "o/old")])
    reconcile(hooks, journal, repositories=(HERE,))
    assert not any(call.startswith("delete") for call in hooks.calls)


def test_a_remembered_name_the_system_cannot_parse_is_skipped() -> None:
    """A journal entry with a forge name this version does not recognise is
    skipped, and the run carries on with the other repositories.
    """
    journal = FakeJournal(remembered=[("github", "nonsense")])
    response = reconcile(FakeHooks(), journal)
    assert [o.outcome for o in response.outcomes] == ["created"]


# --- failure ------------------------------------------------------------


def test_one_unreachable_repository_does_not_stop_the_others() -> None:
    hooks = FakeHooks()
    hooks.fail_on = {("o", "r")}
    response = reconcile(hooks, FakeJournal(), repositories=(HERE, THERE))
    assert [o.outcome for o in response.outcomes] == ["failed", "created"]
    assert response.failed[0].repository == HERE


def test_a_rejection_is_reported_rather_than_raised() -> None:
    hooks = FakeHooks()
    hooks.fail_on = {("o", "r")}
    hooks.error = ForgeRejectedError("the token may not administer hooks")
    response = reconcile(hooks, FakeJournal())
    assert response.failed[0].outcome == "failed"
    assert "administer" in response.failed[0].detail


# --- the journal --------------------------------------------------------


def test_every_outcome_is_journalled_against_the_repository() -> None:
    journal = FakeJournal()
    reconcile(FakeHooks(), journal)
    entry = journal.entries[0]
    assert entry.event_type == "webhook.reconciled"
    assert entry.repo == "o/r"
    assert entry.pr_number is None
    assert entry.payload["outcome"] == "created"


def test_the_secret_is_never_journalled() -> None:
    journal = FakeJournal()
    reconcile(FakeHooks(), journal)
    assert "s3cret" not in str(journal.entries[0])


def test_a_rerun_records_the_same_fact_under_the_same_id() -> None:
    """The journal entry's id is made from the run, so a run that is retried
    after writing some of its entries does not record them twice.
    """
    first, second = FakeJournal(), FakeJournal()
    reconcile(FakeHooks(), first)
    reconcile(FakeHooks(), second)
    assert first.entries[0].event_id == second.entries[0].event_id


@pytest.mark.parametrize("repositories", [(), (HERE,)])
def test_nothing_is_journalled_when_there_is_nothing_to_report(
    repositories: tuple[WatchedRepository, ...],
) -> None:
    journal = FakeJournal()
    reconcile(FakeHooks(), journal, repositories=repositories)
    assert len(journal.entries) == len(repositories)


class RacedHooks(FakeHooks):
    """A fake forge in which another run adds the webhook after this run has
    listed the webhooks and before it creates one. The create is then
    refused, as GitHub refuses a webhook it already has.
    """

    def __init__(self, *, then_visible: bool) -> None:
        super().__init__()
        self._then_visible = then_visible

    def create_hook(self, owner, repo, url, secret, events):  # type: ignore[no-untyped-def]
        self.calls.append(f"create {owner}/{repo} {url}")
        if self._then_visible:
            self.hooks.setdefault((owner, repo), []).append(
                Webhook(hook_id=9, url=url, events=events, active=True)
            )
        raise ForgeRejectedError("GitHub returned 422 for /repos/o/r/hooks")


def test_a_hook_another_run_added_first_is_not_a_failure() -> None:
    """Two runs at once both try to add the webhook, and the forge refuses the
    second. The webhook exists, which is what was wanted, so this is
    reported as success.
    """
    hooks = RacedHooks(then_visible=True)
    response = reconcile(hooks, FakeJournal())

    (outcome,) = response.outcomes
    assert outcome.outcome == "unchanged"
    assert outcome.detail == "another run added it first"
    assert response.failed == ()


def test_a_refusal_with_no_hook_behind_it_still_fails() -> None:
    """If the forge refuses and there is still no webhook of ours, the refusal
    is a real failure and is reported.
    """
    hooks = RacedHooks(then_visible=False)
    response = reconcile(hooks, FakeJournal())

    (outcome,) = response.outcomes
    assert outcome.outcome == "failed"
    assert "422" in outcome.detail
    assert len(response.failed) == 1


def test_the_forge_is_read_again_before_a_refusal_is_believed() -> None:
    """The two cases are told apart by listing the webhooks again, not by
    reading the forge's error message.
    """
    hooks = RacedHooks(then_visible=True)
    reconcile(hooks, FakeJournal())

    assert hooks.calls == [
        "list o/r",
        f"create o/r {URL}",
        "list o/r",
    ]
