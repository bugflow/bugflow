"""Use case: poll forges for changes and post each change as a delivery.

This stands in for webhooks when a forge cannot reach the server. It asks
each forge which pull requests have changed and posts each one to the
server's own delivery endpoint, as the forge would have.

Polling again must not cause the same work twice. So a polled delivery's id
is made from what a review would read: for an open pull request its last
commit, title and description; for a closed one, when it closed. A pull
request that has not changed gets the same id as last time, and the server
drops it as a duplicate.

The poll returns the time the next poll should read from. That time moves
forward only if every delivery of this poll was accepted. Otherwise the
next poll reads the same period again.

Comments are read too, for ``/dismiss`` commands. A comment that starts
with one is posted as a delivery whose id is made from the comment's id, so
reading it again, or an edit to it, does not dismiss twice. The first poll,
which has no earlier time to read from, reads the last day's comments.
"""

import hashlib
from collections.abc import Mapping
from datetime import timedelta

from bugflow.forge.domain.errors import DeliveryNotAcceptedError, ForgeError
from bugflow.forge.domain.models.delivery import Delivery, DeliveryComment
from bugflow.forge.domain.models.polling import (
    POLLED_DELIVERY_PREFIX,
    PolledComment,
    PolledPullRequest,
)
from bugflow.forge.domain.services.polling import (
    DeliverySinkService,
    PullRequestFeedService,
)
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.poll_pull_requests import (
    PollPullRequestsRequest,
    PollPullRequestsResponse,
    SentDelivery,
)
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.values.dismissal import parse_dismissal

# The next poll starts reading this long before the present poll began, so that
# a pull request changed while this poll was running is not missed.
OVERLAP = timedelta(minutes=5)
# How far back the first poll reads comments.
COMMENT_LOOKBACK = timedelta(days=1)


def _delivery_id(*parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()
    return f"{POLLED_DELIVERY_PREFIX}{digest[:32]}"


def delivery_for(pull: PolledPullRequest) -> Delivery:
    ref = pull.ref
    key: tuple[str, ...]
    if pull.open:
        action = "synchronize"
        key = ("open", pull.head_sha, pull.title, pull.body)
    else:
        action = "closed"
        closed_at = pull.closed_at.isoformat() if pull.closed_at else ""
        key = ("closed", closed_at)
    return Delivery(
        forge=ref.forge,
        delivery_id=_delivery_id(
            ref.forge, ref.owner, ref.repo, str(ref.number), *key
        ),
        event="pull_request",
        action=action,
        repository=f"{ref.owner}/{ref.repo}",
        ref=ref,
        updated_at=pull.updated_at,
    )


def delivery_for_comment(comment: PolledComment) -> Delivery | None:
    """The delivery for a comment that is a ``/dismiss`` command. None for any
    other comment.
    """
    if parse_dismissal(comment.body) is None:
        return None
    ref = comment.ref
    return Delivery(
        forge=ref.forge,
        delivery_id=_delivery_id(
            ref.forge, ref.owner, ref.repo, "comment", str(comment.comment_id)
        ),
        event="issue_comment",
        action="created",
        repository=f"{ref.owner}/{ref.repo}",
        ref=ref,
        comment=DeliveryComment(
            comment_id=comment.comment_id,
            author=comment.author,
            body=comment.body,
        ),
    )


class PollPullRequestsUseCase:
    """Takes the repositories to poll and the time to read from. Returns the
    deliveries sent, any failures, and the time the next poll should read
    from.
    """

    def __init__(
        self,
        feeds: Mapping[str, PullRequestFeedService],
        sink: DeliverySinkService,
        clock: ClockService,
    ) -> None:
        """``feeds`` has one feed for each kind of forge, by its name
        ("github", "forgejo"). ``sink`` posts deliveries. ``clock`` tells
        the time.
        """
        self._feeds = feeds
        self._sink = sink
        self._clock = clock

    def execute(
        self, request: PollPullRequestsRequest
    ) -> PollPullRequestsResponse:
        started = self._clock.now()
        comments_since = request.since or started - COMMENT_LOOKBACK
        sent: list[SentDelivery] = []
        failures: list[str] = []
        for entry in request.repositories:
            try:
                repository = WatchedRepository.parse(entry)
            except ValueError as exc:
                failures.append(str(exc))
                continue
            feed = self._feeds.get(repository.forge)
            if feed is None:
                failures.append(
                    f"{repository}: no {repository.forge} forge configured"
                )
                continue
            owner, repo = repository.owner, repository.repo
            try:
                pulls = feed.updated_pull_requests(owner, repo, request.since)
                comments = feed.updated_comments(owner, repo, comments_since)
            except ForgeError as exc:
                failures.append(f"{repository}: {exc}")
                continue
            # Sent oldest first, the order a forge would have sent them in.
            deliveries = [delivery_for(pull) for pull in reversed(pulls)]
            for comment in comments:
                delivery = delivery_for_comment(comment)
                if delivery is not None:
                    deliveries.append(delivery)
            for delivery in deliveries:
                try:
                    outcome = self._sink.send(delivery)
                except DeliveryNotAcceptedError as exc:
                    failures.append(f"{delivery.ref}: {exc}")
                    continue
                sent.append(SentDelivery(delivery=delivery, outcome=outcome))
        return PollPullRequestsResponse(
            sent=tuple(sent),
            failures=tuple(failures),
            next_since=request.since if failures else started - OVERLAP,
        )
