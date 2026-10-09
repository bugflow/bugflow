"""Tests of the Forgejo adapter against fake Forgejo responses.

The behaviour every forge adapter must have is tested in
``test_forge_conformance.py``. The tests here are about Forgejo's own
particulars: its responses, its diff format, its paging and its errors, as
Forgejo 16.0.4 produced them.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest

from bugflow.forge.domain.errors import (
    ForgeRejectedError,
    ForgeUnavailableError,
)
from bugflow.forge.infrastructure.forgejo import (
    ForgejoForge,
    patches_from_diff,
    polled_comment_from_payload,
    snapshot_from_payloads,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

URL = "http://forgejo.test"
REF = PullRequestRef(forge="forgejo", owner="o", repo="r", number=1)
PULL = {
    "title": "Add the poller",
    "body": None,
    "head": {"ref": "change"},
    "base": {"ref": "master"},
}
# The first two sections are a diff Forgejo produced for a pull request that
# adds a binary file and a text file. The rest are git's output for a deletion
# and for renames.
DIFF = """\
diff --git a/logo.png b/logo.png
new file mode 100644
index 0000000..c866266
Binary files /dev/null and b/logo.png differ
diff --git a/poller.py b/poller.py
new file mode 100644
index 0000000..50e05d3
--- /dev/null
+++ b/poller.py
@@ -0,0 +1,2 @@
+def poll():
+    return 1
diff --git a/old.txt b/old.txt
deleted file mode 100644
index 3b18e51..0000000
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
diff --git a/cli.py b/app/cli.py
similarity index 90%
rename from cli.py
rename to app/cli.py
index 1111111..2222222 100644
--- a/cli.py
+++ b/app/cli.py
@@ -1,2 +1,2 @@
-import sys
+import os
 main()
diff --git a/a.txt b/b.txt
similarity index 100%
rename from a.txt
rename to b.txt

"""


def forge(handler: Any) -> ForgejoForge:
    return ForgejoForge(URL, "t", transport=httpx2.MockTransport(handler))


def test_a_diff_is_split_into_each_files_patch() -> None:
    assert patches_from_diff(DIFF) == {
        "logo.png": None,
        "poller.py": "@@ -0,0 +1,2 @@\n+def poll():\n+    return 1",
        "old.txt": "@@ -1 +0,0 @@\n-gone",
        "app/cli.py": "@@ -1,2 +1,2 @@\n-import sys\n+import os\n main()",
        "b.txt": None,
    }


def test_commits_are_oldest_first_and_files_carry_their_patches() -> None:
    snapshot = snapshot_from_payloads(
        REF,
        PULL,
        [
            {"sha": "b" * 40, "commit": {"message": "Add the logo\n"}},
            {"sha": "a" * 40, "commit": {"message": "Add the poller\n"}},
        ],
        [
            {"filename": "poller.py", "additions": 2, "deletions": 0},
            {"filename": "logo.png", "additions": 0, "deletions": 0},
        ],
        DIFF,
    )
    assert [c.summary for c in snapshot.commits] == [
        "Add the poller",
        "Add the logo",
    ]
    poller, logo = snapshot.files
    assert poller.patch == "@@ -0,0 +1,2 @@\n+def poll():\n+    return 1"
    assert logo.patch is None
    assert (snapshot.body, snapshot.ref.forge) == ("", "forgejo")


def test_fetch_authenticates_under_the_api_path_and_reads_the_diff() -> None:
    paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["Authorization"] == "token t"
        paths.append(request.url.path)
        if request.url.path.endswith(".diff"):
            return httpx2.Response(200, text=DIFF)
        if request.url.path.endswith(("/commits", "/files")):
            return httpx2.Response(
                200, json=[], headers={"X-Total-Count": "0"}
            )
        return httpx2.Response(200, json=PULL)

    forge(handler).fetch_snapshot(REF)
    assert paths == [
        "/api/v1/repos/o/r/pulls/1",
        "/api/v1/repos/o/r/pulls/1/commits",
        "/api/v1/repos/o/r/pulls/1/files",
        "/api/v1/repos/o/r/pulls/1.diff",
    ]


def test_a_listing_reads_until_it_has_the_total_even_on_short_pages() -> None:
    commits = [
        {"sha": f"{n:040d}", "commit": {"message": f"Commit {n}\n"}}
        for n in range(23)
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith(".diff"):
            return httpx2.Response(200, text="")
        if path.endswith("/commits"):
            # A server set to return at most 10 items returns pages of 10
            # whatever size is asked for.
            page = int(request.url.params["page"])
            return httpx2.Response(
                200,
                json=commits[(page - 1) * 10 : page * 10],
                headers={"X-Total-Count": str(len(commits))},
            )
        if path.endswith("/files"):
            return httpx2.Response(
                200, json=[], headers={"X-Total-Count": "0"}
            )
        return httpx2.Response(200, json=PULL)

    snapshot = forge(handler).fetch_snapshot(REF)
    assert len(snapshot.commits) == 23


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ForgeRejectedError),
        (404, ForgeRejectedError),
        (422, ForgeRejectedError),
        (429, ForgeUnavailableError),
        (502, ForgeUnavailableError),
    ],
)
def test_failures_are_classified_as_transient_or_permanent(
    status: int, error: type[Exception]
) -> None:
    with pytest.raises(error):
        forge(lambda _: httpx2.Response(status)).fetch_snapshot(REF)


def test_a_rate_limit_carries_the_wait_it_was_given() -> None:
    limited = forge(
        lambda _: httpx2.Response(429, headers={"Retry-After": "7"})
    )
    with pytest.raises(ForgeUnavailableError) as raised:
        limited.fetch_snapshot(REF)
    assert raised.value.retry_after == timedelta(seconds=7)


def test_a_network_failure_is_transient() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(ForgeUnavailableError, match="could not reach"):
        forge(refuse).fetch_snapshot(REF)


def test_only_a_comment_on_a_pull_request_is_polled() -> None:
    comment = {
        "id": 2,
        "body": "/dismiss ED-01 a reason",
        "user": {"login": "reviewer"},
        "updated_at": "2026-09-11T16:33:57Z",
        "issue_url": "",
        "pull_request_url": "http://forgejo.test/o/r/pulls/7",
    }
    polled = polled_comment_from_payload("o", "r", comment)
    assert polled is not None
    assert polled.ref == PullRequestRef(
        forge="forgejo", owner="o", repo="r", number=7
    )
    assert polled.author == "reviewer"
    on_issue = comment | {
        "pull_request_url": "",
        "issue_url": "http://forgejo.test/o/r/issues/7",
    }
    assert polled_comment_from_payload("o", "r", on_issue) is None


def test_pull_requests_are_listed_until_one_is_older_than_since() -> None:
    def pull(number: int, minute: int) -> dict[str, Any]:
        return {
            "number": number,
            "state": "open",
            "head": {"sha": "a" * 40},
            "title": "Add the poller",
            "body": "",
            "updated_at": f"2026-09-11T12:{minute:02d}:00Z",
            "closed_at": None,
        }

    asked: list[dict[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(dict(request.url.params))
        return httpx2.Response(
            200,
            json=[pull(3, 30), pull(2, 20), pull(1, 10)],
            headers={"X-Total-Count": "3"},
        )

    since = datetime(2026, 9, 11, 12, 15, tzinfo=UTC)
    pulls = forge(handler).updated_pull_requests("o", "r", since)
    assert [p.ref.number for p in pulls] == [3, 2]
    assert {p.ref.forge for p in pulls} == {"forgejo"}
    assert (asked[0]["state"], asked[0]["sort"]) == ("all", "recentupdate")


def test_closed_pull_requests_are_listed_until_the_total_is_read() -> None:
    def closed(number: int) -> dict[str, Any]:
        return {
            "number": number,
            "state": "closed",
            "head": {"sha": "a" * 40},
            "title": "Add the poller",
            "body": "",
            "updated_at": "2026-09-11T12:00:00Z",
            "closed_at": "2026-09-11T12:00:00Z",
        }

    asked: list[dict[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(dict(request.url.params))
        # A server that returns pages of 10 and has 23 closed pull requests.
        page = int(request.url.params["page"])
        numbers = list(range(23))[(page - 1) * 10 : page * 10]
        return httpx2.Response(
            200,
            json=[closed(n) for n in numbers],
            headers={"X-Total-Count": "23"},
        )

    pages = [
        forge(handler).closed_pull_requests("o", "r", p) for p in (1, 2, 3, 4)
    ]
    assert [len(p.pulls) for p in pages] == [10, 10, 3, 0]
    assert [p.last for p in pages] == [False, False, False, True]
    assert (asked[0]["state"], asked[0]["sort"]) == ("closed", "oldest")
    assert pages[0].pulls[0].ref.forge == "forgejo"
