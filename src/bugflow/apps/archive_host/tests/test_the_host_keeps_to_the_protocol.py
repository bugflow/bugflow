"""Tests that the archive host follows the remote archive protocol.

The protocol comes with recorded conversations, called tapes. A tape is a
JSON file listing requests in order and the answer a correct server must
give to each. They are written by poslib, the library that defines the
protocol. The files in ``tapes/`` are copies of poslib's.

The main test here plays each tape's requests at the host and fails if any
answer differs from the recording. It uses pyposlib's own client to send
them, so the requests are exactly what a real sealing tool sends.

The other tests cover what the protocol leaves to each server: checking who
is calling, working out which ledger a request is for, and limiting how
much a request may send.

The host under test keeps everything in memory. Tokens are looked up in a
small table here; real token checking has its own tests.
"""

import asyncio
import json
import threading
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from pyposlib import remote
from pyposlib.archive_integrity import Refused

from bugflow.apps.archive_host.host import (
    ArchiveUseCases,
    SignIn,
    create_archive_host,
    from_environment,
)
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.infrastructure.immediate_indexing import ImmediateIndexing
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.infrastructure.in_memory_block_puts import (
    InMemoryBlockPuts,
)
from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)
from bugflow.archive.infrastructure.in_memory_search_index import (
    InMemoryIndexedFiles,
    InMemoryIndexPositions,
)
from bugflow.archive.infrastructure.pyposlib_keeping import PyposlibKeeping
from bugflow.archive.infrastructure.pyposlib_searching import PyposlibSearching
from bugflow.archive.infrastructure.role_archive_access import (
    RoleArchiveAccess,
)
from bugflow.archive.tests.sealed_scope import LEDGER, Scope
from bugflow.archive.usecases.append_event import AppendEventUseCase
from bugflow.archive.usecases.describe_archive import (
    DescribeArchiveUseCase,
)
from bugflow.archive.usecases.fetch_event import FetchEventUseCase
from bugflow.archive.usecases.missing_blocks import MissingBlocksUseCase
from bugflow.archive.usecases.put_block import PutBlockUseCase
from bugflow.archive.usecases.read_archived import ReadArchivedUseCase
from bugflow.archive.usecases.search_archive import SearchArchiveUseCase
from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.services.bearer_token import BearerTokenService
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)

#: The roles the access adapter is told open the archives.
ARCHIVE_READER = "an-archive-reader"
ARCHIVE_WRITER = "an-archive-writer"

TAPES = sorted((Path(__file__).parent / "tapes").glob("tape-*.json"))
UNBOUND = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
CALLERS = {
    # The token the tapes' requests bear.
    "tape-token": Caller("412345", "a-client", frozenset({ARCHIVE_WRITER})),
    "reader": Caller("412346", "a-client", frozenset({ARCHIVE_READER})),
    "ungranted": Caller("412347", "a-client", frozenset()),
}
CLAIMS = {"remote": "git@forge.example:some/one.git", "dirty": "false"}


class Tokens:
    def verify(self, token: str) -> Caller:
        try:
            return CALLERS[token]
        except KeyError as exc:
            raise TokenRefusedError("no such token") from exc


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 1, tzinfo=UTC)


class Host:
    """The archive host set up for a test: one ledger registered, nothing
    stored in it yet, everything kept in memory.

    ``protocols`` is which protocol versions it serves. ``searches`` is
    which search modes it offers; when given, the search index is updated
    straight after every append, so a test can search at once.
    """

    def __init__(
        self,
        max_upload_bytes: int = 1024 * 1024,
        sign_in: SignIn | None = None,
        protocols: tuple[int, ...] = remote.VERSIONS,
        searches: tuple[str, ...] = (),
        tokens: BearerTokenService | None = None,
    ) -> None:
        bindings = InMemoryBindings()
        bindings.save(
            ArchiveBinding(ledger_id=LEDGER, forge="github", repo="some/one")
        )
        access = RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER)
        self.events = InMemoryKeptEvents()
        self.puts = InMemoryBlockPuts()
        self.journal = InMemoryJournal()
        self.store = InMemoryObjectStore()
        keeping = PyposlibKeeping(self.events, self.store, protocols)
        searching = (
            PyposlibSearching(
                keeping,
                InMemoryIndexedFiles(),
                InMemoryIndexPositions(),
                searches,
            )
            if searches
            else None
        )
        self.client = TestClient(
            create_archive_host(
                tokens or Tokens(),
                ArchiveUseCases(
                    describe=DescribeArchiveUseCase(bindings, access, keeping),
                    event=FetchEventUseCase(bindings, access, keeping),
                    held=MissingBlocksUseCase(bindings, access, keeping),
                    put=PutBlockUseCase(bindings, access, keeping, self.puts),
                    append=AppendEventUseCase(
                        bindings,
                        access,
                        keeping,
                        self.journal,
                        Clock(),
                        "run",
                        ImmediateIndexing(searching) if searching else None,
                    ),
                    read=ReadArchivedUseCase(bindings, access, keeping),
                    search=SearchArchiveUseCase(bindings, access, searching)
                    if searching
                    else None,
                ),
                max_upload_bytes,
                sign_in,
                protocols,
            )
        )
        self.app = self.client.app

    def request(
        self,
        method: str,
        path: str,
        token: str | None = "tape-token",
        ledger: str | None = LEDGER,
        headers: Mapping[str, str] | None = None,
        body: bytes | Iterator[bytes] | None = None,
    ) -> Any:
        sent = dict(headers or {})
        sent["Host"] = (
            f"{ledger}.archive.example" if ledger else "archive.example"
        )
        if token is not None:
            sent["Authorization"] = f"Bearer {token}"
        return self.client.request(method, path, headers=sent, content=body)

    def keeper(self, token: str = "tape-token") -> Any:
        """pyposlib's protocol client, wired to send its requests to this
        host.
        """

        def send(
            method: str, url: str, headers: Mapping[str, str], body: bytes
        ) -> tuple[int, bytes]:
            answered = self.client.request(
                method,
                url.removeprefix("https://archive.example"),
                headers={**headers, "Host": f"{LEDGER}.archive.example"},
                content=body,
            )
            return answered.status_code, answered.content

        return remote.HttpRemoteArchive("https://archive.example", token, send)


def refused(answered: Any) -> tuple[int, str]:
    return answered.status_code, answered.json()["refused"]


def test_there_are_tapes_to_hold_it_to() -> None:
    """Check that all seven tapes are present. If the directory were empty,
    the replay test below would run zero times and look like a pass.
    """
    assert [tape.name for tape in TAPES] == [
        "tape-blocks.json",
        "tape-first-events-unnamed.json",
        "tape-refused.json",
        "tape-replay.json",
        "tape-seal.json",
        "tape-search.json",
        "tape-version-2-only.json",
    ]


@pytest.mark.parametrize("tape", TAPES, ids=lambda tape: tape.stem)
def test_a_tape_s_requests_are_answered_as_it_records(tape: Path) -> None:
    """Play one tape at a fresh host and compare every answer with the
    recording: the status and the body, or for a refusal the kind of
    refusal.

    A tape may say which ledger, protocol versions and search modes its
    server had. The host is set up to match.
    """
    recorded = json.loads(tape.read_text())
    assert recorded.get("ledger_id", LEDGER) == LEDGER
    host = Host(
        protocols=tuple(recorded.get("protocols", remote.VERSIONS)),
        searches=tuple(recorded.get("search", ())),
    )
    answered: dict[str, Any] = {}

    def send(
        method: str, url: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[int, bytes]:
        response = host.request(
            method,
            url.removeprefix(recorded["url"]),
            token=None,
            headers=headers,
            body=body,
        )
        answered.update(status=response.status_code, body=response.content)
        return response.status_code, response.content

    client = remote.HttpRemoteArchive(recorded["url"], recorded["token"], send)
    for index, exchange in enumerate(recorded["exchanges"]):
        call = exchange["call"]
        try:
            if call["operation"] == "describe":
                client.describe()
            elif call["operation"] == "event":
                client.event(call["number"])
            elif call["operation"] == "read":
                client.read(call["cid"], call.get("path", ""))
            elif call["operation"] == "held":
                client.held(call["cids"])
            elif call["operation"] == "put":
                client.put(call["cid"], call["block"].encode())
            elif call["operation"] == "search":
                client.search(
                    call["q"],
                    call.get("mode"),
                    call.get("limit"),
                    call.get("within"),
                )
            else:
                client.append(
                    call["name"],
                    call["event"].encode(),
                    {k: v.encode() for k, v in call["files"].items()},
                    call["claims"],
                    [
                        (later["name"], later["event"].encode())
                        for later in call.get("following", [])
                    ],
                )
        except Refused:
            pass
        expected = exchange["response"]
        assert answered["status"] == expected["status"], index
        if "refused" in exchange:
            kind = json.loads(answered["body"])["refused"]
            assert kind == exchange["refused"], index
        else:
            assert answered["body"] == expected["body"].encode(), index


def test_a_request_with_no_token_is_refused() -> None:
    answered = Host().request("GET", "/", token=None)

    assert refused(answered) == (401, "access")
    assert answered.headers["WWW-Authenticate"] == "Bearer"


SIGN_IN = SignIn(
    "https://issuer.example", "a-public-client", ("openid", "a-scope")
)
WELL_KNOWN = "/.well-known/oauth-protected-resource"


def test_a_refusal_for_want_of_a_token_says_where_to_learn_to_sign_in() -> (
    None
):
    """A request with no token is refused, and the refusal gives a URL that
    explains how to sign in. The URL uses https when the proxy in front of
    the host says the request arrived over https.
    """
    answered = Host(sign_in=SIGN_IN).request(
        "GET", "/", token=None, headers={"X-Forwarded-Proto": "https"}
    )

    assert refused(answered) == (401, "access")
    assert answered.headers["WWW-Authenticate"] == (
        f'Bearer resource_metadata="https://{LEDGER}.archive.example{WELL_KNOWN}"'
    )


def test_how_to_sign_in_is_told_to_anyone_at_any_host() -> None:
    """The sign-in instructions need no token, and are the same whichever host
    name is asked: a registered ledger's, an unregistered one's, or none.
    """
    host = Host(sign_in=SIGN_IN)

    for ledger in (LEDGER, UNBOUND, None):
        answered = host.request("GET", WELL_KNOWN, token=None, ledger=ledger)
        told = answered.json()
        assert answered.status_code == 200
        assert told["authorization_servers"] == ["https://issuer.example"]
        assert told["client_id"] == "a-public-client"
        assert told["scopes_supported"] == ["openid", "a-scope"]
        assert told["resource"].startswith("http://")


def test_a_host_told_nothing_of_signing_in_says_nothing_of_it() -> None:
    host = Host()

    challenge = host.request("GET", "/", token=None).headers
    assert challenge["WWW-Authenticate"] == "Bearer"
    assert refused(host.request("GET", WELL_KNOWN, token=None)) == (
        401,
        "access",
    )


def test_a_token_that_vouches_for_nobody_is_refused() -> None:
    assert refused(Host().request("GET", "/", token="forged")) == (
        401,
        "access",
    )


class SlowTokens:
    """A token checker that takes a while, like a real one fetching keys over
    the network. It records whether another request was answered while it
    was busy.
    """

    def __init__(self) -> None:
        self.waiting = threading.Event()
        self.another_answered = threading.Event()
        self.answered_meanwhile = False

    def verify(self, token: str) -> Caller:
        self.waiting.set()
        self.answered_meanwhile = self.another_answered.wait(2)
        return CALLERS["reader"]


def test_a_token_check_that_waits_holds_no_other_request() -> None:
    tokens = SlowTokens()
    app = Host(tokens=tokens).app

    async def two_requests() -> tuple[int, int]:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="https://archive.example",
        ) as client:
            checked = asyncio.create_task(
                client.get(
                    "/",
                    headers={
                        "Host": f"{LEDGER}.archive.example",
                        "Authorization": "Bearer any",
                    },
                )
            )
            # Not asked until the check is waiting. The healthcheck,
            # which checks no token.
            await asyncio.to_thread(tokens.waiting.wait, 5)
            other = await client.get("/")
            tokens.another_answered.set()
            return (await checked).status_code, other.status_code

    assert asyncio.run(two_requests()) == (200, 200)
    assert tokens.answered_meanwhile


def test_a_caller_without_a_role_cannot_tell_which_ledgers_are_kept() -> None:
    host = Host()

    assert refused(host.request("GET", "/", token="ungranted")) == (
        403,
        "access",
    )
    assert refused(
        host.request("GET", "/", token="ungranted", ledger=UNBOUND)
    ) == (403, "access")


def test_a_ledger_nobody_bound_is_absent_to_one_who_may_read() -> None:
    assert refused(
        Host().request("GET", "/", token="reader", ledger=UNBOUND)
    ) == (404, "absent")


def test_a_host_that_names_no_ledger_answers_only_its_healthcheck() -> None:
    """A request to a host name with no ledger id in it gets a health check at
    ``/`` and nothing else. Deployment tools use this to see that the
    server is up.
    """
    host = Host()

    answered = host.request("GET", "/", token=None, ledger=None)
    assert (answered.status_code, answered.json()) == (200, {"ok": True})
    assert refused(host.request("GET", "/events/1", ledger=None)) == (
        404,
        "absent",
    )


def test_one_who_may_only_read_appends_nothing(tmp_path: Path) -> None:
    host = Host()
    name, data, files = Scope(tmp_path).seal("first", {"a.txt": b"first"})

    with pytest.raises(Refused) as refusal:
        host.keeper("reader").append(name, data, files, CLAIMS)

    assert refusal.value.kind == "access"
    assert host.events.of_ledger(LEDGER) == []
    assert host.journal.entries == []


def test_an_append_is_recorded_with_who_sent_it_and_what_they_claimed(
    tmp_path: Path,
) -> None:
    host = Host()
    name, data, files = Scope(tmp_path).seal("first", {"a.txt": b"first"})

    kept = host.keeper().append(name, data, files, CLAIMS)

    (fact,) = host.journal.entries
    assert kept["events"] == 1
    assert fact.event_type == "archive.sealed"
    assert fact.payload["caller"] == "412345"
    assert fact.payload["claims"] == CLAIMS


def test_what_is_read_is_served_as_bytes_a_browser_must_not_run(
    tmp_path: Path,
) -> None:
    """Stored files are other people's content, so a file is served as plain
    bytes with headers telling a browser not to run it, even when it is
    HTML with a script in it.
    """
    host = Host()
    name, data, files = Scope(tmp_path).seal(
        "first", {"page.html": b"<script>alert(1)</script>"}
    )
    host.keeper().append(name, data, files, CLAIMS)
    (cid,) = files

    answered = host.request("GET", f"/ipfs/{cid}", token="reader")

    assert answered.content == b"<script>alert(1)</script>"
    assert answered.headers["Content-Type"] == "application/octet-stream"
    assert answered.headers["X-Content-Type-Options"] == "nosniff"
    assert answered.headers["Content-Security-Policy"] == "sandbox"


def test_a_path_is_decoded_once(tmp_path: Path) -> None:
    """A file name containing ``%20`` is fetched correctly. The client
    percent-encodes the path and the server must decode it exactly once;
    decoding twice would turn the name into a different one.
    """
    host = Host()
    scope = Scope(tmp_path)
    name, data, files = scope.seal("first", {"a%20b.txt": b"first"})
    host.keeper().append(name, data, files, CLAIMS)

    read = host.keeper("reader").read(scope.cids()["first"], "a%20b.txt")

    assert read == b"first"


def test_an_append_larger_than_is_taken_is_refused_and_keeps_nothing(
    tmp_path: Path,
) -> None:
    host = Host(max_upload_bytes=64)
    name, data, files = Scope(tmp_path).seal("first", {"a.txt": b"first"})

    with pytest.raises(Refused) as refusal:
        host.keeper().append(name, data, files, CLAIMS)

    assert refusal.value.kind == "size"
    assert host.events.of_ledger(LEDGER) == []


def test_a_block_is_put_before_its_event_and_the_put_is_recorded(
    tmp_path: Path,
) -> None:
    """Protocol version 2 uploads a file in pieces, called blocks, before the
    event that refers to them. The client asks which blocks the server
    lacks, uploads those, then sends the event. Each upload is recorded
    with the ledger and the caller, and uploading the same block again is
    reported as not new.
    """
    host = Host()
    name, data, files = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    (cid,) = files
    keeper = host.keeper()
    assert keeper.held([cid]) == [cid]
    with pytest.raises(Refused) as refusal:
        keeper.append(name, data, {}, CLAIMS)
    assert refusal.value.kind == "entry"
    assert keeper.put(cid, files[cid]) is True
    assert keeper.put(cid, files[cid]) is False
    assert keeper.held([cid]) == []
    assert keeper.append(name, data, {}, CLAIMS)["events"] == 1
    (put,) = host.puts.of_ledger(LEDGER)
    assert (put.cid, put.caller, put.size, put.new) == (
        cid,
        "412345",
        len(files[cid]),
        True,
    )
    assert host.puts.renewed == [(LEDGER, cid)]
    assert host.keeper("reader").read(cid) == b"first"


def test_one_who_may_only_read_puts_nothing_and_asks_after_nothing(
    tmp_path: Path,
) -> None:
    host = Host()
    _, _, files = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    (cid,) = files
    asks: tuple[Callable[[], object], ...] = (
        lambda: host.keeper("reader").put(cid, files[cid]),
        lambda: host.keeper("reader").held([cid]),
    )
    for ask in asks:
        with pytest.raises(Refused) as refusal:
            ask()
        assert refusal.value.kind == "access"
    assert host.puts.of_ledger(LEDGER) == []
    assert not host.store.objects


def test_a_block_larger_than_one_leaf_is_refused_whatever_an_append_may_be(
    tmp_path: Path,
) -> None:
    """A block is limited to 1 MiB even when the limit for a whole append is
    set higher.
    """
    host = Host(max_upload_bytes=4 * remote.BLOCK_LIMIT)
    _, _, files = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    (cid,) = files
    answered = host.request(
        "PUT", f"/blocks/{cid}", body=b"x" * (remote.BLOCK_LIMIT + 1)
    )
    assert refused(answered) == (413, "size")
    assert not host.store.objects


def test_the_versions_served_are_the_host_s_to_say() -> None:
    """The host can be set to serve protocol version 1 only, 2 only, or both,
    and its description of itself says which. A version 2 only host refuses
    files sent inside an append; a version 1 only host has no block upload.
    """
    only_two = Host(protocols=(2,)).keeper().describe()
    assert (only_two["protocol"], only_two["protocols"]) == (2, [2])
    only_one = Host(protocols=(1,)).keeper().describe()
    assert only_one["protocol"] == 1
    assert "protocols" not in only_one


def test_a_body_that_does_not_say_its_length_is_held_to_the_same() -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(4):
            yield b"x" * 32

    answered = Host(max_upload_bytes=64).request(
        "POST", "/events", body=chunks()
    )

    assert refused(answered) == (413, "size")


def test_a_caller_without_a_role_is_refused_before_the_body_is_weighed() -> (
    None
):
    answered = Host(max_upload_bytes=64).request(
        "POST", "/events", token="ungranted", body=b"x" * 128
    )

    assert refused(answered) == (403, "access")


ENVIRONMENT = {
    "ARCHIVE_ISSUER": "https://issuer.example",
    "ARCHIVE_AUDIENCE": "an-audience",
    "ARCHIVE_CLIENTS": "a-client",
    "ARCHIVE_ROLES_CLAIM": "the-roles",
    "ARCHIVE_READER_ROLE": "a-reader",
    "ARCHIVE_WRITER_ROLE": "a-writer",
    "ARCHIVE_S3_ENDPOINT": "https://objects.example",
    "ARCHIVE_S3_BUCKET": "a-bucket",
    "ARCHIVE_S3_ACCESS_KEY": "an-access-key",
    "ARCHIVE_S3_SECRET_KEY": "a-secret-key",
    # Nothing is asked of it until a request needs it.
    "DATABASE_URL": "postgresql://nobody@db.invalid/none",
}


@pytest.mark.parametrize(
    "missing",
    [
        "ARCHIVE_ISSUER",
        "ARCHIVE_AUDIENCE",
        "ARCHIVE_CLIENTS",
        "ARCHIVE_ROLES_CLAIM",
        "ARCHIVE_READER_ROLE",
        "ARCHIVE_WRITER_ROLE",
        "ARCHIVE_S3_ENDPOINT",
        "ARCHIVE_S3_BUCKET",
        "ARCHIVE_S3_ACCESS_KEY",
        "ARCHIVE_S3_SECRET_KEY",
        "DATABASE_URL",
    ],
)
def test_it_does_not_start_without_a_way_to_check_or_to_keep(
    missing: str,
) -> None:
    """The host refuses to start when a required setting is missing, and the
    error names the setting.
    """
    environ = dict(ENVIRONMENT)
    del environ[missing]

    with pytest.raises(ValueError, match=missing):
        from_environment(environ, key=lambda _: None)


def told_to_sign_in(environ: Mapping[str, str]) -> Any:
    return (
        TestClient(from_environment(environ, key=lambda _: None))
        .get(WELL_KNOWN, headers={"Host": "archive.example"})
        .json()
    )


def test_the_scopes_to_sign_in_with_are_the_environment_s() -> None:
    """The sign-in instructions list the scopes from the ``ARCHIVE_SCOPES``
    setting, or just ``openid`` when it is not set.
    """
    assert told_to_sign_in(ENVIRONMENT)["scopes_supported"] == ["openid"]
    assert told_to_sign_in(
        {**ENVIRONMENT, "ARCHIVE_SCOPES": "openid a-scope  another"}
    )["scopes_supported"] == ["openid", "a-scope", "another"]
