"""Use case: make the webhooks on a list of repositories match what is wanted.

A forge sends deliveries only for a repository that has a webhook pointing
at this server. This use case creates those webhooks and keeps them
correct. It is meant to be run on every deployment, and to change nothing
when everything is already right.

Two rules:

- Only this server's own webhook is touched. A repository may have other
  webhooks, for example a build service's. A webhook counts as this
  server's only if its URL is exactly the URL given in the request. Nothing
  is matched by name or by part of a URL.
- The list of repositories is the whole truth. A repository on the list
  gets a webhook. A repository that was on the list in an earlier run and
  is not now has its webhook removed. The journal is how earlier runs are
  remembered.
"""

from collections.abc import Sequence

from bugflow.forge.domain import facts
from bugflow.forge.domain.errors import ForgeError, ForgeRejectedError
from bugflow.forge.domain.repositories.webhook_admin import (
    WebhookAdminRepository,
)
from bugflow.forge.domain.services.journal_history import (
    JournalRepositoriesService,
)
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.reconcile_webhooks import (
    ReconcileWebhooksRequest,
    ReconcileWebhooksResponse,
    RepositoryOutcome,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService

EVENT = facts.WEBHOOK_RECONCILED


class ReconcileWebhooksUseCase:
    """Takes the repositories that should have a webhook and the URL
    deliveries go to. Returns what was done on each repository: created,
    updated, unchanged, removed, renamed or failed.
    """

    def __init__(
        self,
        hooks: WebhookAdminRepository,
        journal: RecordingService,
        remembered: JournalRepositoriesService,
        clock: ClockService,
    ) -> None:
        self._hooks = hooks
        self._journal = journal
        self._remembered = remembered
        self._clock = clock

    def execute(
        self, request: ReconcileWebhooksRequest
    ) -> ReconcileWebhooksResponse:
        declared = tuple(dict.fromkeys(request.repositories))
        outcomes = [self._declare(r, request) for r in declared]
        outcomes.extend(
            self._withdraw_unless_renamed(r, declared, request)
            for r in self._dropped(declared, request)
        )
        self._record(outcomes, request)
        return ReconcileWebhooksResponse(outcomes=tuple(outcomes))

    def _declare(
        self, repo: WatchedRepository, request: ReconcileWebhooksRequest
    ) -> RepositoryOutcome:
        """Make sure the repository has exactly one webhook of ours, set
        correctly.
        """
        try:
            ours = [
                hook
                for hook in self._hooks.list_hooks(repo.owner, repo.repo)
                if hook.url == request.url
            ]
            if not ours:
                return self._create(repo, request)

            # This use case never creates a second webhook, but a repository
            # can still end up with two: from two runs at once, or from someone
            # adding the same URL by hand. Keep the first and remove the rest,
            # or every delivery would arrive twice.
            keep, spare = ours[0], ours[1:]
            for hook in spare:
                self._hooks.delete_hook(repo.owner, repo.repo, hook.hook_id)

            if keep.matches(request.url, request.events) and not spare:
                # The secret cannot be compared, because a forge never gives it
                # back. So an "unchanged" webhook may have an old secret. To
                # change the secret, update every webhook.
                return RepositoryOutcome(repository=repo, outcome="unchanged")

            self._hooks.update_hook(
                repo.owner,
                repo.repo,
                keep.hook_id,
                request.url,
                request.secret,
                request.events,
            )
            detail = f"dropped {len(spare)} duplicate" if spare else ""
            return RepositoryOutcome(
                repository=repo, outcome="updated", detail=detail
            )
        except ForgeError as exc:
            # A failure on one repository must not stop the others. It is
            # reported in the result.
            return RepositoryOutcome(
                repository=repo, outcome="failed", detail=str(exc)
            )

    def _create(
        self, repo: WatchedRepository, request: ReconcileWebhooksRequest
    ) -> RepositoryOutcome:
        """Add our webhook, or accept the one another run has just added.

        If two runs happen at once, both see no webhook of ours and both
        try to add one. The forge refuses the second. That refusal is not a
        failure: the webhook that was wanted now exists.

        To tell that case from a real refusal, the list of webhooks is read
        again. If ours is there, that is the result. If it is not, the
        refusal is raised.
        """
        try:
            self._hooks.create_hook(
                repo.owner,
                repo.repo,
                request.url,
                request.secret,
                request.events,
            )
        except ForgeRejectedError:
            theirs = [
                hook
                for hook in self._hooks.list_hooks(repo.owner, repo.repo)
                if hook.url == request.url
            ]
            if not theirs:
                raise
            return RepositoryOutcome(
                repository=repo,
                outcome="unchanged",
                detail="another run added it first",
            )
        return RepositoryOutcome(repository=repo, outcome="created")

    def _withdraw_unless_renamed(
        self,
        repo: WatchedRepository,
        declared: Sequence[WatchedRepository],
        request: ReconcileWebhooksRequest,
    ) -> RepositoryOutcome:
        """Remove our webhook from a repository that is no longer on the list,
        unless the repository was only renamed.

        A forge still answers for a renamed repository under its old name.
        If the old name is no longer listed but the new name is, removing
        the webhook "from the old name" would remove the working webhook on
        the new one. Names are compared without regard to case, as forges
        compare them.
        """
        try:
            now = self._hooks.current_name(repo.owner, repo.repo)
        except ForgeError as exc:
            return RepositoryOutcome(
                repository=repo, outcome="failed", detail=str(exc)
            )
        still = {
            f"{d.owner}/{d.repo}".lower()
            for d in declared
            if d.forge == repo.forge
        }
        if now is not None and now.lower() in still:
            return RepositoryOutcome(
                repository=repo,
                outcome="renamed",
                detail=f"now {now}; its hook is kept",
            )
        return self._withdraw(repo, request)

    def _withdraw(
        self, repo: WatchedRepository, request: ReconcileWebhooksRequest
    ) -> RepositoryOutcome:
        try:
            for hook in self._hooks.list_hooks(repo.owner, repo.repo):
                if hook.url == request.url:
                    self._hooks.delete_hook(
                        repo.owner, repo.repo, hook.hook_id
                    )
            return RepositoryOutcome(repository=repo, outcome="removed")
        except ForgeError as exc:
            return RepositoryOutcome(
                repository=repo, outcome="failed", detail=str(exc)
            )

    def _dropped(
        self,
        declared: Sequence[WatchedRepository],
        request: ReconcileWebhooksRequest,
    ) -> list[WatchedRepository]:
        """Repositories that an earlier run gave a webhook and that are not on
        the list now.
        """
        known = set(declared)
        dropped = []
        for forge, full_name in self._remembered.repositories_with(EVENT):
            # The journal may hold a forge name this version does not know.
            # Parsing it, and skipping it if that fails, keeps one odd entry
            # from stopping the run.
            try:
                repo = WatchedRepository.parse(f"{forge}:{full_name}")
            except ValueError:
                continue
            if repo not in known:
                dropped.append(repo)
        return dropped

    def _record(
        self,
        outcomes: Sequence[RepositoryOutcome],
        request: ReconcileWebhooksRequest,
    ) -> None:
        """Write one journal entry for each repository, saying what was done.

        A repository whose webhook was removed is recorded too. It
        therefore stays among the repositories the journal remembers, and a
        later run looks at it again, finds no webhook of ours, and records
        another removal. That is harmless.
        """
        now = self._clock.now()
        entries = [
            JournalEntry(
                event_id=event_id(
                    request.correlation,
                    EVENT,
                    f"{o.repository.forge}/{o.repository.owner}/"
                    f"{o.repository.repo}",
                ),
                occurred_at=now,
                event_type=EVENT,
                forge=o.repository.forge,
                repo=f"{o.repository.owner}/{o.repository.repo}",
                pr_number=None,
                commit_sha=None,
                corpus_version=None,
                workflow_id=request.correlation.workflow_id,
                run_id=request.correlation.run_id,
                payload={
                    "outcome": o.outcome,
                    "detail": o.detail,
                    "url": request.url,
                    "events": sorted(request.events),
                },
            )
            for o in outcomes
        ]
        if entries:
            self._journal.append(entries)
