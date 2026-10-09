"""Tests that every forge adapter behaves the same way.

The same tests are run against the GitHub adapter and the Forgejo adapter.
Each adapter talks to a fake of its forge, which keeps pull requests,
comments and labels in memory and answers the HTTP requests the adapter
makes.

To support another forge, write its adapter and a fake of it, and add the
fake to the fixture. The tests themselves do not change.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, Protocol
from urllib.parse import unquote

import httpx2
import pytest

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.services.forge import ForgeService
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="o", repo="r", number=6)
MARKER = "<!-- conformance:summary -->"
# The diff of the one changed file, as the adapter should return it.
PATCH = "@@ -1 +1,3 @@\n-w\n+x\n+y\n+z"


class ForgeBackend(Protocol):
    def comment_bodies(self, number: int) -> list[str]: ...

    def unattribute_commits(self) -> None:
        """Remove the account from every commit's author, as a forge does when
        a commit's email matches none of its users.
        """
        ...

    def labels_on(self, number: int) -> set[str]: ...

    def add_comment(self, number: int, body: str) -> int: ...

    def add_label(self, number: int, name: str) -> None: ...

    def status_on(self, sha: str, context: str) -> tuple[str, str] | None: ...

    def close(self, number: int) -> None:
        """Close the pull request, as merging or closing it does."""
        ...


class FakeGitHub:
    """A fake of GitHub's API for pull requests, comments, labels and
    webhooks.
    """

    def __init__(self) -> None:
        self.pulls: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.labels: dict[int, set[str]] = {}
        self.statuses: dict[tuple[str, str], tuple[str, str]] = {}
        # Webhooks, kept separately for each repository. The fake's other
        # endpoints ignore which repository is named, because those tests use
        # only one. The webhook tests use several.
        self.hooks: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._next_id = 1000

    def close(self, number: int) -> None:
        self.pulls[number]["pull"]["state"] = "closed"

    def seed_pull_request(self, number: int) -> None:
        self.pulls[number] = {
            "pull": {
                "number": number,
                "title": "Add the judge port",
                "body": "Introduces the port.",
                "head": {"ref": "judge-port"},
                "base": {"ref": "master", "sha": "b" * 40},
                "user": {"login": "a-contributor"},
                "state": "open",
            },
            # GitHub lists commits oldest first.
            "commits": [
                {
                    "sha": "a" * 40,
                    "commit": {
                        "message": "Add the port\n",
                        "author": {
                            "name": "A Contributor",
                            "email": "a@example.invalid",
                        },
                        "committer": {
                            "name": "A Contributor",
                            "email": "a@example.invalid",
                        },
                        "verification": {"verified": True, "reason": "valid"},
                    },
                    "author": {"login": "a-contributor"},
                    "committer": {"login": "a-contributor"},
                },
                {
                    "sha": "b" * 40,
                    "commit": {
                        "message": "Use the port\n",
                        "author": {
                            "name": "Another Contributor",
                            "email": "another@example.invalid",
                        },
                        # Committed by someone other than the author, as after
                        # a rebase or when someone applies a patch.
                        "committer": {
                            "name": "A Contributor",
                            "email": "a@example.invalid",
                        },
                        "verification": {
                            "verified": False,
                            "reason": "unsigned",
                        },
                    },
                    "author": {"login": "another-contributor"},
                    "committer": {"login": "a-contributor"},
                },
            ],
            "files": [
                {
                    "filename": "port.py",
                    "additions": 3,
                    "deletions": 1,
                    "patch": PATCH,
                }
            ],
        }
        self.comments.setdefault(number, [])
        self.labels.setdefault(number, set())

    def unattribute_commits(self) -> None:
        for seeded in self.pulls.values():
            for commit in seeded["commits"]:
                commit.pop("author", None)

    def comment_bodies(self, number: int) -> list[str]:
        return [c["body"] for c in self.comments.get(number, [])]

    def labels_on(self, number: int) -> set[str]:
        return set(self.labels.get(number, set()))

    def add_comment(self, number: int, body: str) -> int:
        self._next_id += 1
        self.comments.setdefault(number, []).append(
            {"id": self._next_id, "body": body}
        )
        return self._next_id

    def add_label(self, number: int, name: str) -> None:
        self.labels.setdefault(number, set()).add(name)

    def status_on(self, sha: str, context: str) -> tuple[str, str] | None:
        return self.statuses.get((sha, context))

    @staticmethod
    def _page(items: list[Any], request: httpx2.Request) -> list[Any]:
        per_page = int(request.url.params.get("per_page", "30"))
        page = int(request.url.params.get("page", "1"))
        return items[(page - 1) * per_page : page * per_page]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        parts = request.url.path.strip("/").split("/")
        method = request.method
        if parts[:1] != ["repos"]:
            return httpx2.Response(404)
        if parts[3:4] == ["hooks"]:
            return self._hooks(parts[1], parts[2], parts[4:], method, request)
        if len(parts) < 5:
            return httpx2.Response(404)
        kind, rest = parts[3], parts[4:]

        if kind == "statuses" and method == "POST":
            status = _json(request)
            self.statuses[(rest[0], status["context"])] = (
                status["state"],
                status["description"],
            )
            return httpx2.Response(201, json=status)

        if kind == "commits" and method == "GET":
            # The endpoint for a single commit, the only one where GitHub lists
            # the paths a commit changed.
            for held in self.pulls.values():
                for commit in held["commits"]:
                    if commit["sha"] == rest[0]:
                        return httpx2.Response(
                            200,
                            json={
                                **commit,
                                "files": [
                                    {"filename": f["filename"]}
                                    for f in held["files"]
                                ],
                            },
                        )
            return httpx2.Response(404)

        if kind == "pulls" and method == "GET":
            pull = self.pulls.get(int(rest[0]))
            if pull is None:
                return httpx2.Response(404)
            if len(rest) == 1:
                return httpx2.Response(200, json=pull["pull"])
            return httpx2.Response(
                200, json=self._page(pull[rest[1]], request)
            )

        if kind == "issues" and rest[0] == "comments" and method == "PATCH":
            comment_id = int(rest[1])
            for comments in self.comments.values():
                for comment in comments:
                    if comment["id"] == comment_id:
                        comment["body"] = _json(request)["body"]
                        return httpx2.Response(200, json=comment)
            return httpx2.Response(404)

        number = int(rest[0])
        if number not in self.pulls:
            return httpx2.Response(404)
        if rest[1:] == ["comments"] and method == "GET":
            return httpx2.Response(
                200, json=self._page(self.comments[number], request)
            )
        if rest[1:] == ["comments"] and method == "POST":
            comment_id = self.add_comment(number, _json(request)["body"])
            return httpx2.Response(201, json={"id": comment_id})
        if rest[1:] == ["labels"] and method == "POST":
            self.labels[number].update(_json(request)["labels"])
            return httpx2.Response(200, json=sorted(self.labels[number]))
        if rest[1:2] == ["labels"] and len(rest) == 3 and method == "DELETE":
            if rest[2] not in self.labels[number]:
                return httpx2.Response(404)
            self.labels[number].discard(rest[2])
            return httpx2.Response(200, json=sorted(self.labels[number]))
        return httpx2.Response(404)

    def _hooks(
        self,
        owner: str,
        repo: str,
        rest: list[str],
        method: str,
        request: httpx2.Request,
    ) -> httpx2.Response:
        """The endpoints for a repository's webhooks.

        The secret is stored and never returned, as on GitHub. A caller
        cannot read back the secret it wrote.
        """
        hooks = self.hooks.setdefault((owner, repo), [])
        if not rest:
            if method == "GET":
                return httpx2.Response(
                    200, json=self._page([_public(h) for h in hooks], request)
                )
            if method == "POST":
                self._next_id += 1
                hook = dict(_json(request), id=self._next_id)
                hooks.append(hook)
                return httpx2.Response(201, json=_public(hook))
            return httpx2.Response(404)

        hook_id = int(rest[0])
        found = next((h for h in hooks if h["id"] == hook_id), None)
        if found is None:
            return httpx2.Response(404)
        if method == "PATCH":
            found.update(_json(request))
            return httpx2.Response(200, json=_public(found))
        if method == "DELETE":
            hooks.remove(found)
            return httpx2.Response(204)
        return httpx2.Response(404)


def _public(hook: dict[str, Any]) -> dict[str, Any]:
    """A webhook as a forge returns it: everything except the secret."""
    config = {k: v for k, v in hook["config"].items() if k != "secret"}
    return {**hook, "config": config}


class FakeForgejo:
    """A fake of Forgejo's API for pull requests, comments and labels. It
    answers as Forgejo 16.0.4 does.
    """

    def __init__(self) -> None:
        self.pulls: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.labels: dict[int, set[str]] = {}
        self.repository_labels: set[str] = set()
        self.statuses: dict[tuple[str, str], tuple[str, str]] = {}
        self._next_id = 1000

    def close(self, number: int) -> None:
        self.pulls[number]["pull"]["state"] = "closed"

    def seed_pull_request(self, number: int) -> None:
        self.pulls[number] = {
            "pull": {
                "number": number,
                "title": "Add the judge port",
                "body": "Introduces the port.",
                "head": {"ref": "judge-port"},
                "base": {"ref": "master", "sha": "b" * 40},
                "user": {"login": "a-contributor"},
                "state": "open",
            },
            # Forgejo lists commits newest first.
            "commits": [
                {
                    "sha": "b" * 40,
                    "commit": {
                        "message": "Use the port\n",
                        "author": {
                            "name": "Another Contributor",
                            "email": "another@example.invalid",
                        },
                        # Committed by someone other than the author, as after
                        # a rebase or when someone applies a patch.
                        "committer": {
                            "name": "A Contributor",
                            "email": "a@example.invalid",
                        },
                        "verification": {
                            "verified": False,
                            "reason": "unsigned",
                        },
                    },
                    "author": {"login": "another-contributor"},
                    "committer": {"login": "a-contributor"},
                },
                {
                    "sha": "a" * 40,
                    "commit": {
                        "message": "Add the port\n",
                        "author": {
                            "name": "A Contributor",
                            "email": "a@example.invalid",
                        },
                        "committer": {
                            "name": "A Contributor",
                            "email": "a@example.invalid",
                        },
                        "verification": {"verified": True, "reason": "valid"},
                    },
                    "author": {"login": "a-contributor"},
                    "committer": {"login": "a-contributor"},
                },
            ],
            # No diff here: Forgejo's list of files does not include one.
            "files": [{"filename": "port.py", "additions": 3, "deletions": 1}],
            "diff": (
                "diff --git a/port.py b/port.py\n"
                "index 1111111..2222222 100644\n"
                "--- a/port.py\n+++ b/port.py\n"
                f"{PATCH}\n"
            ),
        }
        self.comments.setdefault(number, [])
        self.labels.setdefault(number, set())

    def unattribute_commits(self) -> None:
        for seeded in self.pulls.values():
            for commit in seeded["commits"]:
                commit.pop("author", None)

    def comment_bodies(self, number: int) -> list[str]:
        return [c["body"] for c in self.comments.get(number, [])]

    def labels_on(self, number: int) -> set[str]:
        return set(self.labels.get(number, set()))

    def add_comment(self, number: int, body: str) -> int:
        self._next_id += 1
        self.comments.setdefault(number, []).append(
            {"id": self._next_id, "body": body}
        )
        return self._next_id

    def add_label(self, number: int, name: str) -> None:
        self.repository_labels.add(name)
        self.labels.setdefault(number, set()).add(name)

    def status_on(self, sha: str, context: str) -> tuple[str, str] | None:
        return self.statuses.get((sha, context))

    @staticmethod
    def _paged(items: list[Any], request: httpx2.Request) -> httpx2.Response:
        limit = min(int(request.url.params.get("limit", "50")), 50)
        page = int(request.url.params.get("page", "1"))
        return httpx2.Response(
            200,
            json=items[(page - 1) * limit : page * limit],
            headers={"X-Total-Count": str(len(items))},
        )

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        parts = request.url.path.strip("/").split("/")
        method = request.method
        if parts[:3] != ["api", "v1", "repos"] or len(parts) < 6:
            return httpx2.Response(404)
        kind, rest = parts[5], parts[6:]

        if kind == "statuses" and method == "POST":
            status = _json(request)
            self.statuses[(rest[0], status["context"])] = (
                status["state"],
                status["description"],
            )
            return httpx2.Response(201, json=status)

        if kind == "labels" and not rest:
            if method == "GET":
                return self._paged(
                    [{"name": n} for n in sorted(self.repository_labels)],
                    request,
                )
            name = _json(request)["name"]
            self.repository_labels.add(name)
            return httpx2.Response(201, json={"name": name})

        if kind == "pulls" and method == "GET" and rest:
            number_text = rest[0].removesuffix(".diff")
            pull = self.pulls.get(int(number_text))
            if pull is None:
                return httpx2.Response(404)
            if rest[0].endswith(".diff"):
                return httpx2.Response(200, text=pull["diff"])
            if len(rest) == 1:
                return httpx2.Response(200, json=pull["pull"])
            return self._paged(pull[rest[1]], request)

        if kind == "issues" and rest[:1] == ["comments"] and method == "PATCH":
            comment_id = int(rest[1])
            for comments in self.comments.values():
                for comment in comments:
                    if comment["id"] == comment_id:
                        comment["body"] = _json(request)["body"]
                        return httpx2.Response(200, json=comment)
            return httpx2.Response(404)

        if kind != "issues" or not rest or int(rest[0]) not in self.pulls:
            return httpx2.Response(404)
        number = int(rest[0])
        if rest[1:] == ["comments"] and method == "GET":
            # All of a pull request's comments are returned at once.
            return httpx2.Response(200, json=self.comments[number])
        if rest[1:] == ["comments"] and method == "POST":
            comment_id = self.add_comment(number, _json(request)["body"])
            return httpx2.Response(201, json={"id": comment_id})
        if rest[1:] == ["labels"] and method == "POST":
            # A label name the repository does not have is ignored, as Forgejo
            # does.
            self.labels[number].update(
                name
                for name in _json(request)["labels"]
                if name in self.repository_labels
            )
            return httpx2.Response(
                200, json=[{"name": n} for n in sorted(self.labels[number])]
            )
        if rest[1:2] == ["labels"] and len(rest) == 3 and method == "DELETE":
            name = unquote(rest[2])
            if name not in self.repository_labels:
                return httpx2.Response(422)
            self.labels[number].discard(name)
            return httpx2.Response(204)
        return httpx2.Response(404)


def _json(request: httpx2.Request) -> Any:
    return json.loads(request.read())


@dataclass
class Subject:
    forge: ForgeService
    backend: ForgeBackend


@pytest.fixture(params=["github", "forgejo"])
def subject(request: pytest.FixtureRequest) -> Iterator[Subject]:
    if request.param == "github":
        github = FakeGitHub()
        github.seed_pull_request(REF.number)
        forge: ForgeService = GitHubForge(
            "t", transport=httpx2.MockTransport(github.handle)
        )
        yield Subject(forge=forge, backend=github)
    else:
        forgejo = FakeForgejo()
        forgejo.seed_pull_request(REF.number)
        forge = ForgejoForge(
            "http://forgejo.test",
            "t",
            transport=httpx2.MockTransport(forgejo.handle),
        )
        yield Subject(forge=forge, backend=forgejo)


def test_fetches_the_pull_request(subject: Subject) -> None:
    snapshot = subject.forge.fetch_snapshot(REF)
    assert (snapshot.title, snapshot.head_branch, snapshot.base_branch) == (
        "Add the judge port",
        "judge-port",
        "master",
    )
    assert snapshot.changed_lines == 4


def test_commits_come_oldest_first_and_each_file_with_its_patch(
    subject: Subject,
) -> None:
    snapshot = subject.forge.fetch_snapshot(REF)
    assert [c.summary for c in snapshot.commits] == [
        "Add the port",
        "Use the port",
    ]
    (changed,) = snapshot.files
    assert (changed.path, changed.patch) == ("port.py", PATCH)


def test_the_account_that_opened_it_is_carried(subject: Subject) -> None:
    """The snapshot has the account that opened the pull request."""
    assert subject.forge.fetch_snapshot(REF).author_login == "a-contributor"


def test_an_email_makes_a_commit_and_both_forges_record_it(
    subject: Subject,
) -> None:
    """The snapshot has the name and email git recorded for each commit's
    author.
    """
    commits = subject.forge.fetch_snapshot(REF).commits
    assert [c.author.email for c in commits] == [
        "a@example.invalid",
        "another@example.invalid",
    ]
    assert [c.author.name for c in commits] == [
        "A Contributor",
        "Another Contributor",
    ]


def test_the_committer_is_kept_apart_from_the_author(
    subject: Subject,
) -> None:
    """The author and the committer are kept separately. They differ after a
    rebase or when someone else applied the patch.
    """
    second = subject.forge.fetch_snapshot(REF).commits[1]
    assert second.author.email == "another@example.invalid"
    assert second.committer.email == "a@example.invalid"


def test_whether_the_signature_verifies_is_carried(
    subject: Subject,
) -> None:
    """The snapshot says whether the forge could verify each commit's
    signature.
    """
    commits = subject.forge.fetch_snapshot(REF).commits
    assert [c.verified for c in commits] == [True, False]
    assert commits[1].verification_reason == "unsigned"


def test_a_login_is_the_forges_mapping_and_may_be_absent(
    subject: Subject,
) -> None:
    """The account is the forge's match for the email, not part of the commit.
    When nothing matched it is empty, and the email is still there.
    """
    subject.backend.unattribute_commits()
    commits = subject.forge.fetch_snapshot(REF).commits
    assert [c.author.login for c in commits] == ["", ""]
    assert [c.author.email for c in commits] == [
        "a@example.invalid",
        "another@example.invalid",
    ]


def test_a_missing_pull_request_is_rejected(subject: Subject) -> None:
    with pytest.raises(ForgeRejectedError):
        subject.forge.fetch_snapshot(replace(REF, number=999))


def test_a_comment_is_added(subject: Subject) -> None:
    subject.forge.add_comment(REF, MARKER, f"{MARKER}\nfirst")
    assert subject.backend.comment_bodies(REF.number) == [f"{MARKER}\nfirst"]


def test_the_marker_makes_a_repeat_add_nothing(subject: Subject) -> None:
    """Adding a comment twice with the same marker adds it once. A retry after
    a lost response must not post the same comment again.
    """
    first = subject.forge.add_comment(REF, MARKER, f"{MARKER}\nv1")
    second = subject.forge.add_comment(REF, MARKER, f"{MARKER}\nv2")
    assert first == second
    assert subject.backend.comment_bodies(REF.number) == [f"{MARKER}\nv1"]


def test_other_comments_are_left_alone(subject: Subject) -> None:
    subject.backend.add_comment(REF.number, "a reviewer's comment")
    subject.forge.add_comment(REF, MARKER, f"{MARKER}\nv1")
    subject.forge.add_comment(REF, MARKER, f"{MARKER}\nv2")
    assert subject.backend.comment_bodies(REF.number) == [
        "a reviewer's comment",
        f"{MARKER}\nv1",
    ]


def test_a_marked_comment_is_found_past_the_first_page(
    subject: Subject,
) -> None:
    for n in range(150):
        subject.backend.add_comment(REF.number, f"comment {n}")
    marked = subject.backend.add_comment(REF.number, f"{MARKER}\nold")
    assert subject.forge.add_comment(REF, MARKER, f"{MARKER}\nnew") == marked
    bodies = subject.backend.comment_bodies(REF.number)
    assert len(bodies) == 151 and bodies[-1] == f"{MARKER}\nold"


def test_a_different_marker_adds_another_comment(subject: Subject) -> None:
    """A comment with a different marker is added as a new comment."""
    subject.forge.add_comment(REF, MARKER, f"{MARKER}\nfirst")
    other = "<!-- bugflow:evaluation:second -->"
    subject.forge.add_comment(REF, other, f"{other}\nsecond")
    assert subject.backend.comment_bodies(REF.number) == [
        f"{MARKER}\nfirst",
        f"{other}\nsecond",
    ]


def test_labels_are_added_and_removed(subject: Subject) -> None:
    subject.backend.add_label(REF.number, "doctrine:fail")
    subject.forge.set_labels(
        REF,
        add=frozenset({"doctrine:pass"}),
        remove=frozenset({"doctrine:fail"}),
    )
    assert subject.backend.labels_on(REF.number) == {"doctrine:pass"}


def test_removing_a_label_that_is_absent_is_not_an_error(
    subject: Subject,
) -> None:
    subject.forge.set_labels(
        REF, add=frozenset(), remove=frozenset({"doctrine:warn"})
    )
    assert subject.backend.labels_on(REF.number) == set()


def test_labels_outside_the_request_are_untouched(subject: Subject) -> None:
    subject.backend.add_label(REF.number, "needs-design")
    subject.forge.set_labels(
        REF,
        add=frozenset({"doctrine:warn"}),
        remove=frozenset({"doctrine:pass"}),
    )
    assert subject.backend.labels_on(REF.number) == {
        "needs-design",
        "doctrine:warn",
    }


def test_a_commit_status_is_set_over_the_earlier_one(subject: Subject) -> None:
    head = "b" * 40
    subject.forge.set_commit_status(
        REF, head, "doctrine", "failure", "1 failing finding"
    )
    subject.forge.set_commit_status(
        REF, head, "doctrine", "success", "no findings"
    )
    assert subject.backend.status_on(head, "doctrine") == (
        "success",
        "no findings",
    )


def test_reports_an_open_pull_request_as_open(subject: Subject) -> None:
    assert subject.forge.is_open(REF) is True


def test_reports_a_closed_pull_request_as_closed(subject: Subject) -> None:
    """A closed or merged pull request is reported as not open. Whatever is
    waiting for it to close relies on this.
    """
    subject.backend.close(REF.number)
    assert subject.forge.is_open(REF) is False


def test_the_commit_the_base_was_at_is_carried(subject: Subject) -> None:
    """The snapshot has the commit the target branch was at. A review compares
    against that commit, since the branch itself moves on.
    """
    snapshot = subject.forge.fetch_snapshot(REF)
    assert snapshot.base_sha == "b" * 40
    assert snapshot.summary().base_sha == "b" * 40
