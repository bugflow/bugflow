"""The adapter for Forgejo.

It talks to the REST API of a Forgejo server you run yourself, signing in
with a personal access token.

Forgejo's API is modelled on GitHub's but differs in places. These
differences were found with Forgejo 16.0.4, and this adapter handles each:

- The list of a pull request's files has no diffs. They are read from the
  pull request's whole diff and split up by file.
- The list of a pull request's commits is newest first. GitHub's is oldest
  first.
- A pull request's comments come in a single response, not in pages.
- Adding a label that the repository does not have does nothing and reports
  no error. So a missing label is created first. Removing a label the
  repository does not have is an error.
- A comment on a pull request names the pull request in
  ``pull_request_url``, and its ``issue_url`` is empty.
"""

import re
from collections.abc import Iterator
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
from bugflow.forge.domain.services.forge import CommitState
from bugflow.forge.domain.values.conversation import PullRequestState, Reaction
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

# Forgejo's default page size (its ``MAX_RESPONSE_ITEMS`` setting). A server
# may be set to return fewer, so a listing is read until it has as many items
# as the ``X-Total-Count`` header says there are.
PER_PAGE = 50
MAX_PAGES = 60
# The colour given to a label this adapter creates.
LABEL_COLOR = "#ededed"

_FILE_SECTION = re.compile(r"^(?=diff --git )", re.MULTILINE)


def patches_from_diff(diff: str) -> dict[str, str | None]:
    """Split a pull request's whole diff into one patch for each file, keyed
    by the file's path after the change.

    Each patch starts at its first ``@@`` line, as GitHub's patches do. A
    binary file, or a file that was renamed without being changed, has no
    patch.
    """
    patches: dict[str, str | None] = {}
    for section in _FILE_SECTION.split(diff):
        if not section.startswith("diff --git "):
            continue
        lines = section.rstrip("\n").split("\n")
        header = lines[0].removeprefix("diff --git ")
        path = header.split(" b/", 1)[1] if " b/" in header else header
        hunk = None
        for index, line in enumerate(lines[1:], start=1):
            if line.startswith("@@"):
                hunk = index
                break
            if line.startswith("+++ b/"):
                path = line.removeprefix("+++ b/")
            elif line.startswith("rename to "):
                path = line.removeprefix("rename to ")
        patches[path] = None if hunk is None else "\n".join(lines[hunk:])
    return patches


def _authorship(
    claim: dict[str, Any] | None, account: dict[str, Any] | None
) -> Authorship:
    """Build an ``Authorship`` from the name and email git recorded
    (``claim``) and the account Forgejo matched to it (``account``), if
    any.
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
        # When asked to include files, Forgejo's list of commits gives each
        # file's path as ``filename``.
        files=tuple(
            f["filename"] for f in (c.get("files") or []) if f.get("filename")
        ),
    )


def snapshot_from_payloads(
    ref: PullRequestRef,
    pull: dict[str, Any],
    commits: list[dict[str, Any]],
    files: list[dict[str, Any]],
    diff: str,
) -> PullRequestSnapshot:
    patches = patches_from_diff(diff)
    return PullRequestSnapshot(
        ref=ref,
        title=pull["title"],
        body=pull.get("body") or "",
        head_branch=pull["head"]["ref"],
        base_branch=pull["base"]["ref"],
        base_sha=(pull["base"] or {}).get("sha") or "",
        author_login=(pull.get("user") or {}).get("login") or "",
        # Forgejo lists commits newest first. They are reversed to oldest
        # first.
        commits=tuple(_commit_snapshot(c) for c in reversed(commits)),
        files=tuple(
            ChangedFile(
                path=f["filename"],
                additions=f["additions"],
                deletions=f["deletions"],
                patch=patches.get(f["filename"]),
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
    """Build a ``PolledPullRequest`` from one entry of Forgejo's list of pull
    requests.
    """
    updated_at = _timestamp(pull["updated_at"])
    assert updated_at is not None
    return PolledPullRequest(
        ref=PullRequestRef(
            forge="forgejo", owner=owner, repo=repo, number=pull["number"]
        ),
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
    """Build a ``PolledComment`` from one entry of Forgejo's list of a
    repository's comments. Returns None for a comment on an ordinary issue.
    """
    url = comment.get("pull_request_url") or ""
    if not url:
        return None
    updated_at = _timestamp(comment["updated_at"])
    assert updated_at is not None
    return PolledComment(
        ref=PullRequestRef(
            forge="forgejo",
            owner=owner,
            repo=repo,
            number=int(url.rstrip("/").rsplit("/", 1)[1]),
        ),
        comment_id=comment["id"],
        author=(comment.get("user") or {}).get("login") or "",
        body=comment.get("body") or "",
        updated_at=updated_at,
    )


def classify(response: httpx2.Response, path: str) -> ForgeError:
    """Turn a failed response into the right error: ``ForgeUnavailableError``
    if trying again later may work, ``ForgeRejectedError`` if it will not.

    Forgejo itself has no rate limit, but a proxy in front of it may answer
    429.
    """
    status = response.status_code
    message = f"Forgejo returned {status} for {path}"
    if status == 429:
        retry_after = response.headers.get("retry-after", "")
        return ForgeUnavailableError(
            f"{message}: rate limited",
            timedelta(seconds=int(retry_after))
            if retry_after.isdigit()
            else timedelta(minutes=1),
        )
    if status >= 500:
        return ForgeUnavailableError(message)
    return ForgeRejectedError(message)


class ForgejoForge:
    def __init__(
        self,
        url: str,
        token: str,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._client = httpx2.Client(
            base_url=f"{url.rstrip('/')}/api/v1",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/json",
            },
            timeout=30.0,
            transport=transport,
            # Forgejo answers a request for a renamed repository with a
            # redirect to its new name: 301 for a read, 307 for a write.
            # Redirects are followed, keeping the method. The host stays the
            # same, so the token is sent on.
            follow_redirects=True,
        )

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        path = f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
        pull = self._send("GET", path)
        commits = self._get_all(
            # Ask for each commit's files, so that a review can look at each
            # commit's changes separately. Forgejo includes them in this one
            # response, so it costs no extra request.
            f"{path}/commits",
            {"files": "true", "verification": "false"},
        )
        files = self._get_all(f"{path}/files")
        diff = self._request("GET", f"{path}.diff").text
        return snapshot_from_payloads(ref, pull, commits, files, diff)

    def is_open(self, ref: PullRequestRef) -> bool:
        path = f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
        return bool(self._send("GET", path).get("state") == "open")

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
            for raw in self._send("GET", f"{path}/reactions") or []
        )

    def state(self, ref: PullRequestRef) -> PullRequestState:
        pull = self._send(
            "GET", f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
        )
        return PullRequestState(
            merged=bool(pull.get("merged")),
            head_sha=(pull.get("head") or {}).get("sha") or None,
        )

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        repo = f"/repos/{ref.owner}/{ref.repo}"
        comments = f"{repo}/issues/{ref.number}/comments"
        # Forgejo returns all of a pull request's comments in one response.
        for comment in self._send("GET", comments):
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
        repo = f"/repos/{ref.owner}/{ref.repo}"
        existing = {
            str(label["name"]) for label in self._get_all(f"{repo}/labels")
        }
        for name in sorted(add - existing):
            self._send(
                "POST",
                f"{repo}/labels",
                json={"name": name, "color": LABEL_COLOR},
            )
        labels = f"{repo}/issues/{ref.number}/labels"
        if add:
            self._send("POST", labels, json={"labels": sorted(add)})
        # Removing a label that the pull request does not have is fine.
        # Removing one that the repository does not have is an error, so only
        # labels the repository has are removed.
        for name in sorted((remove - add) & existing):
            self._send("DELETE", f"{labels}/{quote(name, safe='')}")

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
        params: dict[str, int | str] = {
            "state": "open" if since is None else "all",
            "sort": "recentupdate",
        }
        pulls: list[PolledPullRequest] = []
        for batch in self._pages(f"/repos/{owner}/{repo}/pulls", params):
            for payload in batch:
                pull = polled_from_payload(owner, repo, payload)
                if since is not None and pull.updated_at < since:
                    return pulls
                pulls.append(pull)
        return pulls

    def closed_pull_requests(
        self, owner: str, repo: str, page: int
    ) -> PullRequestPage:
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "oldest",
                "limit": PER_PAGE,
                "page": page,
            },
        )
        batch: list[dict[str, Any]] = response.json()
        total = response.headers.get("x-total-count", "")
        # A server may return fewer items per page than asked for, so the
        # length of a full page is taken as the page size.
        last = not batch or (
            page * len(batch) >= int(total)
            if total.isdigit()
            else len(batch) < PER_PAGE
        )
        return PullRequestPage(
            pulls=tuple(polled_from_payload(owner, repo, p) for p in batch),
            last=last,
        )

    def updated_comments(
        self, owner: str, repo: str, since: datetime
    ) -> list[PolledComment]:
        params: dict[str, int | str] = {
            "since": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        comments: list[PolledComment] = []
        for batch in self._pages(
            f"/repos/{owner}/{repo}/issues/comments", params
        ):
            for payload in batch:
                comment = polled_comment_from_payload(owner, repo, payload)
                if comment is not None:
                    comments.append(comment)
        return comments

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, int | str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx2.Response:
        try:
            response = self._client.request(
                method, path, params=params, json=json
            )
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise classify(exc.response, path) from exc
        except httpx2.RequestError as exc:
            raise ForgeUnavailableError(
                f"could not reach Forgejo: {exc}"
            ) from exc
        return response

    def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        response = self._request(method, path, json=json)
        return response.json() if response.content else None

    def _pages(
        self, path: str, params: dict[str, int | str] | None = None
    ) -> Iterator[list[dict[str, Any]]]:
        read = 0
        for page in range(1, MAX_PAGES + 1):
            response = self._request(
                "GET",
                path,
                params=(params or {}) | {"limit": PER_PAGE, "page": page},
            )
            batch: list[dict[str, Any]] = response.json()
            yield batch
            read += len(batch)
            total = response.headers.get("x-total-count", "")
            if not batch or (
                read >= int(total)
                if total.isdigit()
                else len(batch) < PER_PAGE
            ):
                return

    def _get_all(
        self, path: str, params: dict[str, int | str] | None = None
    ) -> list[dict[str, Any]]:
        return [item for batch in self._pages(path, params) for item in batch]
