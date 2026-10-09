"""The adapter for GitHub.

It talks to GitHub's REST API at api.github.com, signing in with a personal
access token. One class, ``GitHubForge``, provides everything the forge
context asks of a forge: reading and writing a pull request, reading its
discussion, listing what has changed for the poller, and managing webhooks.
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx2

from bugflow.forge.domain.errors import (
    ForgeError,
    ForgeRejectedError,
    ForgeUnavailableError,
)
from bugflow.forge.domain.models.delivery import forge_time
from bugflow.forge.domain.models.polling import (
    PolledComment,
    PolledPullRequest,
    PullRequestPage,
)
from bugflow.forge.domain.models.pull_request import (
    Authorship,
    ChangedFile,
    CommitSnapshot,
    PullRequestSnapshot,
)
from bugflow.forge.domain.models.webhook import Webhook
from bugflow.forge.domain.services.forge import CommitState
from bugflow.forge.domain.values.conversation import PullRequestState, Reaction
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

API_URL = "https://api.github.com"
PER_PAGE = 100
# GitHub lists at most 250 commits and 3,000 files for a pull request. Thirty
# pages of a hundred covers both.
MAX_PAGES = 30


def _authorship(
    claim: dict[str, Any] | None, account: dict[str, Any] | None
) -> Authorship:
    """Build an ``Authorship`` from the name and email git recorded
    (``claim``) and the account GitHub matched to it (``account``), if any.
    """
    claim = claim or {}
    return Authorship(
        name=claim.get("name") or "",
        email=claim.get("email") or "",
        login=(account or {}).get("login") or "",
    )


def _commit_snapshot(c: dict[str, Any]) -> CommitSnapshot:
    commit = c.get("commit") or {}
    verification = commit.get("verification") or {}
    return CommitSnapshot(
        sha=c["sha"],
        message=commit["message"],
        author=_authorship(commit.get("author"), c.get("author")),
        committer=_authorship(commit.get("committer"), c.get("committer")),
        verified=bool(verification.get("verified")),
        verification_reason=verification.get("reason") or "",
        # The list of a pull request's commits has no ``files``. They are
        # present only if the caller fetched each commit and added them.
        files=tuple(
            f["filename"] for f in (c.get("files") or []) if f.get("filename")
        ),
    )


def snapshot_from_payloads(
    ref: PullRequestRef,
    pull: dict[str, Any],
    commits: list[dict[str, Any]],
    files: list[dict[str, Any]],
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=ref,
        title=pull["title"],
        body=pull.get("body") or "",
        head_branch=pull["head"]["ref"],
        base_branch=pull["base"]["ref"],
        base_sha=(pull["base"] or {}).get("sha") or "",
        author_login=(pull.get("user") or {}).get("login") or "",
        commits=tuple(_commit_snapshot(c) for c in commits),
        files=tuple(
            ChangedFile(
                path=f["filename"],
                additions=f["additions"],
                deletions=f["deletions"],
                patch=f.get("patch"),
            )
            for f in files
        ),
    )


def _timestamp(value: str | None) -> datetime | None:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    )


def polled_from_payload(
    owner: str, repo: str, pull: dict[str, Any]
) -> PolledPullRequest:
    """Build a ``PolledPullRequest`` from one entry of GitHub's list of pull
    requests.
    """
    updated_at = _timestamp(pull["updated_at"])
    assert updated_at is not None
    return PolledPullRequest(
        ref=PullRequestRef(owner=owner, repo=repo, number=pull["number"]),
        open=pull["state"] == "open",
        head_sha=pull["head"]["sha"],
        title=pull["title"],
        body=pull.get("body") or "",
        updated_at=updated_at,
        closed_at=_timestamp(pull.get("closed_at")),
    )


def polled_comment_from_payload(
    owner: str, repo: str, comment: dict[str, Any]
) -> PolledComment | None:
    """Build a ``PolledComment`` from one entry of GitHub's list of comments.
    Returns None for a comment on an ordinary issue.

    GitHub lists comments on pull requests and on issues together. A
    comment on a pull request is recognised by ``/pull/`` in its link.
    """
    if "/pull/" not in (comment.get("html_url") or ""):
        return None
    number = int(str(comment["issue_url"]).rstrip("/").rsplit("/", 1)[1])
    updated_at = _timestamp(comment["updated_at"])
    assert updated_at is not None
    return PolledComment(
        ref=PullRequestRef(owner=owner, repo=repo, number=number),
        comment_id=comment["id"],
        author=(comment.get("user") or {}).get("login") or "",
        body=comment.get("body") or "",
        updated_at=updated_at,
    )


def _retry_after(headers: httpx2.Headers) -> timedelta:
    """How long GitHub asks a rate-limited client to wait.

    It is the ``retry-after`` header in seconds if present; otherwise the
    time until ``x-ratelimit-reset``; otherwise one minute. The wait is
    never less than a minute when taken from the reset time.
    """
    retry_after = headers.get("retry-after", "")
    if retry_after.isdigit():
        return timedelta(seconds=int(retry_after))
    reset = headers.get("x-ratelimit-reset", "")
    if reset.isdigit():
        return timedelta(seconds=max(60, int(reset) - int(time.time())))
    return timedelta(minutes=1)


def classify(response: httpx2.Response, path: str) -> ForgeError:
    """Turn a failed response into the right error: ``ForgeUnavailableError``
    if trying again later may work, ``ForgeRejectedError`` if it will not.

    GitHub reports a rate limit as status 429, or as 403 with either a
    ``retry-after`` header or ``x-ratelimit-remaining: 0``. A 403 with
    neither means permission was refused. A status of 500 or above is a
    fault at GitHub.
    """
    status = response.status_code
    message = f"GitHub returned {status} for {path}"
    headers = response.headers
    rate_limited = status == 429 or (
        status == 403
        and (
            "retry-after" in headers
            or headers.get("x-ratelimit-remaining") == "0"
        )
    )
    if rate_limited:
        return ForgeUnavailableError(
            f"{message}: rate limited", _retry_after(headers)
        )
    if status >= 500:
        return ForgeUnavailableError(message)
    return ForgeRejectedError(message)


class GitHubForge:
    """GitHub, as the forge context sees a forge.

    ``token`` is a personal access token. ``transport`` replaces the
    network, for tests.
    """

    def __init__(
        self, token: str, transport: httpx2.BaseTransport | None = None
    ) -> None:
        self._client = httpx2.Client(
            base_url=API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            transport=transport,
            # GitHub answers a request for a renamed repository with a redirect
            # to its new name: 301 for a read, 307 for a write. Redirects are
            # followed, keeping the method. The host stays the same, so the
            # token is sent on.
            follow_redirects=True,
        )

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        path = f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
        pull = self._get(path)
        commits = self._get_all(f"{path}/commits")
        files = self._get_all(f"{path}/files")
        return snapshot_from_payloads(
            ref, pull, [self._with_files(ref, c) for c in commits], files
        )

    def _with_files(
        self, ref: PullRequestRef, commit: dict[str, Any]
    ) -> dict[str, Any]:
        """Add to a commit the list of paths it changed.

        This costs one request for each commit. GitHub's list of a pull
        request's commits does not say which files each commit changed;
        only the endpoint for a single commit does. The paths are wanted so
        that a review can look at each commit's changes separately.
        """
        found = self._get(
            f"/repos/{ref.owner}/{ref.repo}/commits/{commit['sha']}"
        )
        return {**commit, "files": found.get("files") or []}

    def is_open(self, ref: PullRequestRef) -> bool:
        pull = self._get(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
        return bool(pull.get("state") == "open")

    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        path = f"/repos/{ref.owner}/{ref.repo}/issues/comments/{comment_id}"
        return tuple(
            Reaction(
                content=str(raw.get("content") or ""),
                login=str((raw.get("user") or {}).get("login") or ""),
                reacted_at=forge_time(raw.get("created_at")),
            )
            for raw in self._get(f"{path}/reactions") or []
        )

    def state(self, ref: PullRequestRef) -> PullRequestState:
        pull = self._get(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
        return PullRequestState(
            merged=bool(pull.get("merged")),
            head_sha=(pull.get("head") or {}).get("sha") or None,
        )

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        repo = f"/repos/{ref.owner}/{ref.repo}"
        comments = f"{repo}/issues/{ref.number}/comments"
        for comment in self._get_all(comments):
            if marker in (comment.get("body") or ""):
                # A comment with this marker is already there, so nothing is
                # added.
                return int(comment["id"])
        created = self._send("POST", comments, json={"body": body})
        return int(created["id"])

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        labels = f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}/labels"
        if add:
            self._send("POST", labels, json={"labels": sorted(add)})
        for name in sorted(remove - add):
            # GitHub answers 404 if the pull request does not have the label.
            # That is not an error here.
            self._send(
                "DELETE", f"{labels}/{quote(name, safe='')}", missing_ok=True
            )

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        self._send(
            "POST",
            f"/repos/{ref.owner}/{ref.repo}/statuses/{sha}",
            json={
                "state": state,
                "context": context,
                "description": description,
            },
        )

    def updated_pull_requests(
        self, owner: str, repo: str, since: datetime | None
    ) -> list[PolledPullRequest]:
        path = f"/repos/{owner}/{repo}/pulls"
        params: dict[str, int | str] = {
            "state": "open" if since is None else "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": PER_PAGE,
        }
        pulls: list[PolledPullRequest] = []
        for page in range(1, MAX_PAGES + 1):
            batch = self._get(path, params | {"page": page})
            for payload in batch:
                pull = polled_from_payload(owner, repo, payload)
                if since is not None and pull.updated_at < since:
                    return pulls
                pulls.append(pull)
            if len(batch) < PER_PAGE:
                break
        return pulls

    def closed_pull_requests(
        self, owner: str, repo: str, page: int
    ) -> PullRequestPage:
        batch = self._get(
            f"/repos/{owner}/{repo}/pulls",
            {
                "state": "closed",
                "sort": "created",
                "direction": "asc",
                "per_page": PER_PAGE,
                "page": page,
            },
        )
        return PullRequestPage(
            pulls=tuple(polled_from_payload(owner, repo, p) for p in batch),
            last=len(batch) < PER_PAGE,
        )

    def updated_comments(
        self, owner: str, repo: str, since: datetime
    ) -> list[PolledComment]:
        path = f"/repos/{owner}/{repo}/issues/comments"
        params: dict[str, int | str] = {
            "sort": "updated",
            "direction": "asc",
            "since": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "per_page": PER_PAGE,
        }
        comments: list[PolledComment] = []
        for page in range(1, MAX_PAGES + 1):
            batch = self._get(path, params | {"page": page})
            for payload in batch:
                comment = polled_comment_from_payload(owner, repo, payload)
                if comment is not None:
                    comments.append(comment)
            if len(batch) < PER_PAGE:
                break
        return comments

    # --- managing webhooks (WebhookAdminRepository) -----------------------
    # These methods work on a repository, not on one pull request. Errors are
    # reported the same way as for every other call.

    def list_hooks(self, owner: str, repo: str) -> list[Webhook]:
        return [
            webhook_from_payload(payload)
            for payload in self._get_all(f"/repos/{owner}/{repo}/hooks")
        ]

    def create_hook(
        self,
        owner: str,
        repo: str,
        url: str,
        secret: str,
        events: frozenset[str],
    ) -> Webhook:
        payload = self._send(
            "POST",
            f"/repos/{owner}/{repo}/hooks",
            json=_hook_body(url, secret, events),
        )
        return webhook_from_payload(payload)

    def update_hook(
        self,
        owner: str,
        repo: str,
        hook_id: int,
        url: str,
        secret: str,
        events: frozenset[str],
    ) -> Webhook:
        payload = self._send(
            "PATCH",
            f"/repos/{owner}/{repo}/hooks/{hook_id}",
            json=_hook_body(url, secret, events),
        )
        return webhook_from_payload(payload)

    def current_name(self, owner: str, repo: str) -> str | None:
        found = self._send("GET", f"/repos/{owner}/{repo}", missing_ok=True)
        return str(found["full_name"]) if found else None

    def delete_hook(self, owner: str, repo: str, hook_id: int) -> None:
        # A webhook that someone deleted in the meantime is already gone, which
        # is what was wanted, so a 404 is not an error.
        self._send(
            "DELETE",
            f"/repos/{owner}/{repo}/hooks/{hook_id}",
            missing_ok=True,
        )

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, int | str] | None = None,
        json: dict[str, Any] | None = None,
        missing_ok: bool = False,
    ) -> Any:
        try:
            response = self._client.request(
                method, path, params=params, json=json
            )
            if missing_ok and response.status_code == 404:
                return None
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise classify(exc.response, path) from exc
        except httpx2.RequestError as exc:
            raise ForgeUnavailableError(
                f"could not reach GitHub: {exc}"
            ) from exc
        return response.json() if response.content else None

    def _get(
        self, path: str, params: dict[str, int | str] | None = None
    ) -> Any:
        return self._send("GET", path, params=params)

    def _get_all(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            batch = self._get(path, {"per_page": PER_PAGE, "page": page})
            items.extend(batch)
            if len(batch) < PER_PAGE:
                break
        return items


def _hook_body(
    url: str, secret: str, events: frozenset[str]
) -> dict[str, Any]:
    """The JSON GitHub is sent to create or update a webhook.

    ``content_type`` is ``json`` so that GitHub posts each delivery as a
    JSON body. The alternative, form encoding, would put the JSON inside a
    form field, and the receiving side could neither read it nor check its
    signature.
    """
    return {
        "name": "web",
        "active": True,
        "events": sorted(events),
        "config": {
            "url": url,
            "content_type": "json",
            "secret": secret,
            "insecure_ssl": "0",
        },
    }


def webhook_from_payload(payload: dict[str, Any]) -> Webhook:
    return Webhook(
        hook_id=payload["id"],
        url=(payload.get("config") or {}).get("url") or "",
        events=frozenset(payload.get("events") or ()),
        active=bool(payload.get("active")),
    )
