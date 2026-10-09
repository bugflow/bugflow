"""The archive host: a web server that stores sealed archives.

It speaks the remote archive protocol, which poslib defines. A sealing tool
on someone's machine sends it the events of a ledger and the files those
events refer to; it checks them, stores them, and serves them back.

Each ledger has its own host name: the ledger's id, a UUID, is the first
part of the name. A request for ledger ``1a2b...`` is sent to
``1a2b....archive.example``. One host name per ledger keeps a browser from
mixing up cookies or scripts between ledgers, since stored files are other
people's content.

This module does not implement the protocol. pyposlib's ``remote.handle``
reads each request and decides which operation it is. This module gives
``handle`` an object whose methods are the archive's use cases, and adds
what the protocol leaves to each server:

- Who is calling. Every request for a ledger needs a bearer token. No valid
  token answers 401, a caller without the right role 403, and a ledger that
  is not registered 404, checked in that order so that a stranger cannot
  find out which ledgers exist.
- How much may be sent. An append is limited to
  ``ARCHIVE_MAX_UPLOAD_BYTES``. A single block, or a list of block ids, is
  limited to 1 MiB. A body is not read until the caller is known to be
  allowed.
- How to sign in. A 401 gives a URL, and that URL answers, with no token
  needed, which identity provider to use, which client to sign in as and
  which scopes to ask for.

A request to a host name with no ledger id gets a health check at ``/`` and
nothing else.

Run it with ``uvicorn bugflow.apps.archive_host.host:from_environment
--factory``.
"""

import os
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request, Response
from pyposlib import remote
from pyposlib.archive_integrity import Refused, encoded
from starlette.concurrency import run_in_threadpool

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.dtos.append_event import AppendEventRequest
from bugflow.archive.dtos.describe_archive import DescribeArchiveRequest
from bugflow.archive.dtos.fetch_event import FetchEventRequest
from bugflow.archive.dtos.missing_blocks import MissingBlocksRequest
from bugflow.archive.dtos.put_block import PutBlockRequest
from bugflow.archive.dtos.read_archived import ReadArchivedRequest
from bugflow.archive.dtos.search_archive import SearchArchiveRequest
from bugflow.archive.infrastructure import schema
from bugflow.archive.infrastructure.pyposlib_keeping import PyposlibKeeping
from bugflow.archive.infrastructure.pyposlib_searching import PyposlibSearching
from bugflow.archive.infrastructure.role_archive_access import (
    RoleArchiveAccess,
)
from bugflow.archive.infrastructure.sqlalchemy_bindings import (
    SqlAlchemyBindings,
)
from bugflow.archive.infrastructure.sqlalchemy_block_puts import (
    SqlAlchemyBlockPuts,
)
from bugflow.archive.infrastructure.sqlalchemy_kept_events import (
    SqlAlchemyKeptEvents,
)
from bugflow.archive.infrastructure.sqlalchemy_search_index import (
    SqlAlchemyIndexedFiles,
    SqlAlchemyIndexPositions,
)
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
from bugflow.shared.infrastructure import sqlalchemy_journal
from bugflow.shared.infrastructure.jwt_bearer_token import (
    JwtBearerToken,
    published_keys,
)
from bugflow.shared.infrastructure.s3_object_store import S3ObjectStore
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal
from bugflow.shared.infrastructure.system_clock import SystemClock

#: The largest append accepted unless ARCHIVE_MAX_UPLOAD_BYTES says
#: otherwise. A whole append is held in memory while it is checked.
DEFAULT_MAX_UPLOAD_BYTES = 64 * 1024 * 1024

#: The protocol versions served unless ARCHIVE_PROTOCOLS says otherwise.
DEFAULT_PROTOCOLS: tuple[int, ...] = remote.VERSIONS

#: A ledger id: a lower-case UUID.
_LEDGER = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)

#: Headers sent with every answer. Stored files are other people's
#: content, so a browser is told not to guess a file's type and not to
#: run anything in it.
_UNTRUSTED = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
}


#: The scopes sealing tools are told to ask for unless ARCHIVE_SCOPES
#: says otherwise.
SCOPES: tuple[str, ...] = ("openid",)

#: The path that answers how to sign in (RFC 9728).
SIGN_IN_PATH = "/.well-known/oauth-protected-resource"


@dataclass(frozen=True)
class SignIn:
    """What the host tells a sealing tool about signing in: the identity
    provider's address, the client id to sign in as, and the scopes to ask
    for.
    """

    issuer: str
    client_id: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class ArchiveUseCases:
    """The archive's use cases, one for each operation of the protocol."""

    describe: DescribeArchiveUseCase
    event: FetchEventUseCase
    held: MissingBlocksUseCase
    put: PutBlockUseCase
    append: AppendEventUseCase
    read: ReadArchivedUseCase
    #: None for a host with no search. It then says nothing about search
    #: in its description and answers a search request 404.
    search: SearchArchiveUseCase | None = None


def _refusing[T](operation: Callable[[], T]) -> T:
    """Run ``operation``. If the archive refuses, raise the error type that
    pyposlib's ``handle`` turns into an HTTP answer.
    """
    try:
        return operation()
    except ArchiveRefusedError as refused:
        raise Refused(refused.kind, str(refused)) from refused


class _Kept:
    """One ledger as seen by one caller, in the shape pyposlib's ``handle``
    expects: a method for each protocol operation. Each method calls the
    matching use case.

    ``handle`` asks for the ledger's description before an append, and the
    append answers with one too. The description is remembered until
    something changes it, so the ledger is not read twice for one request.
    """

    def __init__(
        self,
        usecases: ArchiveUseCases,
        ledger_id: str,
        caller: Caller,
        protocols: Sequence[int] = DEFAULT_PROTOCOLS,
    ) -> None:
        self._usecases = usecases
        self._ledger_id = ledger_id
        self._caller = caller
        self.protocols = tuple(protocols)
        self._described: dict[str, Any] | None = None

    def _description(self, kept: Any) -> dict[str, Any]:
        described = {
            "protocol": kept.protocols[0],
            # The protocol reports a ledger's id only once it has an event.
            "ledger_id": kept.ledger_id if kept.events else None,
            "head": kept.head,
            "events": kept.events,
            "root": kept.root,
            "erased": list(kept.erased),
        }
        # Version 1 had no "protocols" or "retiring" fields, so a host
        # serving version 1 only leaves them out.
        if tuple(kept.protocols) != (1,):
            described["protocols"] = list(kept.protocols)
            if kept.retiring:
                described["retiring"] = {
                    str(version): date for version, date in kept.retiring
                }
        if self._usecases.search is not None:
            described["search"] = {"modes": list(self._usecases.search.modes)}
        return described

    def describe(self) -> dict[str, Any]:
        if self._described is None:
            self._described = self._description(
                _refusing(
                    lambda: self._usecases.describe.execute(
                        DescribeArchiveRequest(
                            ledger_id=self._ledger_id, caller=self._caller
                        )
                    )
                )
            )
        return self._described

    def event(self, number: int) -> bytes:
        return _refusing(
            lambda: self._usecases.event.execute(
                FetchEventRequest(
                    ledger_id=self._ledger_id,
                    caller=self._caller,
                    number=number,
                )
            )
        ).data

    def held(self, cids: Sequence[str]) -> list[str]:
        return list(
            _refusing(
                lambda: self._usecases.held.execute(
                    MissingBlocksRequest(
                        ledger_id=self._ledger_id,
                        caller=self._caller,
                        cids=tuple(cids),
                    )
                )
            ).missing
        )

    def put(self, cid: str, data: bytes) -> bool:
        self._described = None
        return _refusing(
            lambda: self._usecases.put.execute(
                PutBlockRequest(
                    ledger_id=self._ledger_id,
                    caller=self._caller,
                    cid=cid,
                    data=data,
                )
            )
        ).new

    def append(
        self,
        name: str,
        event: bytes,
        files: Mapping[str, bytes],
        claims: Mapping[str, str],
        following: Sequence[tuple[str, bytes]] = (),
    ) -> dict[str, Any]:
        self._described = None
        return self._description(
            _refusing(
                lambda: self._usecases.append.execute(
                    AppendEventRequest(
                        ledger_id=self._ledger_id,
                        caller=self._caller,
                        name=name,
                        data=event,
                        files=dict(files),
                        claims=dict(claims),
                        following=tuple(following),
                    )
                )
            )
        )

    def read(self, cid: str, path: str = "") -> bytes:
        return _refusing(
            lambda: self._usecases.read.execute(
                ReadArchivedRequest(
                    ledger_id=self._ledger_id,
                    caller=self._caller,
                    cid=cid,
                    path=path,
                )
            )
        ).data

    def search(
        self,
        query: str | None,
        mode: str | None = None,
        limit: int | None = None,
        within: str | None = None,
    ) -> list[dict[str, Any]]:
        searching = self._usecases.search
        if searching is None:
            raise Refused("absent", "This keeper does not search")
        if not query:
            raise Refused("request", "Expected q, the query")
        hits = _refusing(
            lambda: searching.execute(
                SearchArchiveRequest(
                    ledger_id=self._ledger_id,
                    caller=self._caller,
                    query=query,
                    mode=mode,
                    limit=limit,
                    within=within,
                )
            )
        ).hits
        answered: list[dict[str, Any]] = []
        for hit in hits:
            # The JSON shape section 12 of the protocol gives a hit.
            wired: dict[str, Any] = {
                "ref": hit.ref,
                "range": {"lines": [hit.first_line, hit.last_line]},
                "passage": hit.passage,
            }
            if hit.score is not None:
                wired["score"] = hit.score
            answered.append(wired)
        return answered


def _ledger_of(host: str) -> str | None:
    """The ledger id in a host name, or None if the name's first part is not a
    UUID.
    """
    label = host.split(":", 1)[0].split(".", 1)[0].lower()
    return label if _LEDGER.fullmatch(label) else None


def _answer(status: int, kind: str, body: bytes) -> Response:
    return Response(body, status, _UNTRUSTED, kind)


def _refusal(kind: str, message: str, status: int | None = None) -> Response:
    """An HTTP answer that refuses the request, in the protocol's form: a JSON
    object with the kind of refusal and a message for a person.
    """
    return _answer(
        status or remote.STATUS.get(kind, 422),
        remote.JSON,
        encoded({"refused": kind, "message": message}),
    )


def _origin(request: Request) -> str:
    """The scheme and host the client used, such as ``https://x.example``.
    When a proxy in front of the host handled TLS, it says so in
    ``X-Forwarded-Proto``.
    """
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.headers.get('host', '')}"


def _path(request: Request) -> str:
    """The request's path and query exactly as the client sent them, still
    percent-encoded. ``handle`` does the decoding, and decoding here as
    well would decode twice.
    """
    raw = request.scope.get("raw_path")
    path = raw.decode("latin-1") if raw else quote(request.url.path)
    path = path.rstrip("/") or "/"
    query = request.scope.get("query_string", b"").decode("latin-1")
    return f"{path}?{query}" if query else path


def create_archive_host(
    tokens: BearerTokenService,
    usecases: ArchiveUseCases,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    sign_in: SignIn | None = None,
    protocols: Sequence[int] = DEFAULT_PROTOCOLS,
    on_start: Callable[[], None] | None = None,
) -> FastAPI:
    """Build the web application.

    ``tokens`` checks bearer tokens. ``usecases`` are the archive's use
    cases. ``protocols`` is which protocol versions to serve. ``on_start``,
    if given, is called once when the server starts, before it takes any
    request.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if on_start is not None:
            await run_in_threadpool(on_start)
        yield

    app = FastAPI(title="bugflow archive host", lifespan=lifespan)

    def caller(authorization: str) -> Caller | None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            return tokens.verify(token.strip())
        except TokenRefusedError:
            return None

    async def body_of(request: Request, limit: int) -> bytes | None:
        """Read the request body, or return None if it is larger than
        ``limit``.
        """
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            return None
        received = bytearray()
        async for chunk in request.stream():
            received += chunk
            if len(received) > limit:
                return None
        return bytes(received)

    def limit_of(request: Request) -> tuple[int, str]:
        """The size limit for this request's body, and a word for it to use in
        an error message. An append gets the configured limit; a block or a
        list of block ids gets 1 MiB.
        """
        if request.method == "POST" and _path(request) == "/events":
            return max_upload_bytes, "An append"
        return remote.BLOCK_LIMIT, "A block"

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT"])
    async def wire(request: Request) -> Response:
        """Handle one request: find the ledger from the host name, check the
        token, read the body, and pass the request to pyposlib's
        ``handle``.
        """
        if (
            sign_in is not None
            and request.method == "GET"
            and request.url.path == SIGN_IN_PATH
        ):
            # Answered without a token, on any host name: this is how a
            # client learns to get a token.
            return _answer(
                200,
                remote.JSON,
                encoded(
                    {
                        "resource": _origin(request),
                        "authorization_servers": [sign_in.issuer],
                        "scopes_supported": list(sign_in.scopes),
                        "client_id": sign_in.client_id,
                        "bearer_methods_supported": ["header"],
                    }
                ),
            )
        ledger_id = _ledger_of(request.headers.get("host", ""))
        if ledger_id is None:
            # A health check, for deployment tools.
            if request.method == "GET" and request.url.path == "/":
                return _answer(200, remote.JSON, encoded({"ok": True}))
            return _refusal("absent", "This host names no ledger")
        # Run on a thread. Checking a token may fetch the provider's
        # keys over the network, and waiting for that here would stop
        # the server answering anyone else.
        who = await run_in_threadpool(
            caller, request.headers.get("authorization", "")
        )
        if who is None:
            denied = _refusal("access", "A bearer token is required", 401)
            if sign_in is None:
                denied.headers["WWW-Authenticate"] = "Bearer"
            else:
                told = _origin(request) + SIGN_IN_PATH
                denied.headers["WWW-Authenticate"] = (
                    f'Bearer resource_metadata="{told}"'
                )
            return denied
        kept = _Kept(usecases, ledger_id, who, protocols)
        body = b""
        if request.method in ("POST", "PUT"):
            try:
                await run_in_threadpool(kept.describe)
            except Refused as refusal:
                return _refusal(refusal.kind, str(refusal))
            limit, what = limit_of(request)
            received = await body_of(request, limit)
            if received is None:
                return _refusal("size", f"{what} is at most {limit} bytes")
            body = received
        status, kind, answer = await run_in_threadpool(
            remote.handle,
            kept,
            request.method,
            _path(request),
            dict(request.headers),
            body,
        )
        return _answer(status, kind, answer)

    return app


def from_environment(
    environ: Mapping[str, str] | None = None,
    key: Callable[[str], object] | None = None,
) -> FastAPI:
    """Build the archive host from environment variables. This is what uvicorn
    calls.

    Required, and the host refuses to start without them:

    - ``ARCHIVE_ISSUER``: the identity provider's address.
    - ``ARCHIVE_AUDIENCE``: the audience a token must be addressed to.
    - ``ARCHIVE_CLIENTS``: client ids a token may come from, comma-
      separated. The first is the one sealing tools are told to sign in as.
    - ``ARCHIVE_ROLES_CLAIM``: the name of the token claim that lists a
      person's roles.
    - ``ARCHIVE_READER_ROLE`` and ``ARCHIVE_WRITER_ROLE``: the role that
      may read every ledger, and the role that may also append.
    - ``ARCHIVE_S3_ENDPOINT``, ``ARCHIVE_S3_BUCKET``,
      ``ARCHIVE_S3_ACCESS_KEY`` and ``ARCHIVE_S3_SECRET_KEY``: the bucket
      files are stored in.
    - ``DATABASE_URL``: the Postgres database for events and the journal.

    Optional:

    - ``ARCHIVE_S3_REGION``: defaults to ``us-east-1``.
    - ``ARCHIVE_SCOPES``: scopes sealing tools are told to ask for, space-
      separated. Defaults to ``openid``.
    - ``ARCHIVE_MAX_UPLOAD_BYTES``: the largest append accepted. Defaults
      to 64 MiB.
    - ``ARCHIVE_PROTOCOLS``: protocol versions to serve, such as ``1,2``.
      Defaults to both.
    - ``ARCHIVE_RETIRING``: the date after which a version may be dropped,
      such as ``1=2027-01-31``. Clients are told, so they can warn.
    - ``BUILD_SHA``: recorded with every journal entry, to show which build
      wrote it.

    When the server starts it creates any of its database tables that are
    missing.

    ``key`` replaces the lookup of the provider's signing keys, for tests.
    """
    environ = os.environ if environ is None else environ
    issuer = environ.get("ARCHIVE_ISSUER", "")
    audience = environ.get("ARCHIVE_AUDIENCE", "")
    clients = [
        client.strip()
        for client in environ.get("ARCHIVE_CLIENTS", "").split(",")
        if client.strip()
    ]
    if not (issuer and audience and clients):
        raise ValueError(
            "ARCHIVE_ISSUER, ARCHIVE_AUDIENCE and ARCHIVE_CLIENTS are "
            "required; the archive host does not start without a way to "
            "check a token"
        )
    endpoint = environ.get("ARCHIVE_S3_ENDPOINT", "")
    bucket = environ.get("ARCHIVE_S3_BUCKET", "")
    access_key = environ.get("ARCHIVE_S3_ACCESS_KEY", "")
    secret_key = environ.get("ARCHIVE_S3_SECRET_KEY", "")
    if not (endpoint and bucket and access_key and secret_key):
        raise ValueError(
            "ARCHIVE_S3_ENDPOINT, ARCHIVE_S3_BUCKET, ARCHIVE_S3_ACCESS_KEY "
            "and ARCHIVE_S3_SECRET_KEY are required; the archive host does "
            "not start without somewhere to keep what is sealed"
        )
    roles_claim = environ.get("ARCHIVE_ROLES_CLAIM", "")
    reader = environ.get("ARCHIVE_READER_ROLE", "")
    writer = environ.get("ARCHIVE_WRITER_ROLE", "")
    if not (roles_claim and reader and writer):
        raise ValueError(
            "ARCHIVE_ROLES_CLAIM, ARCHIVE_READER_ROLE and "
            "ARCHIVE_WRITER_ROLE are required; the archive host does not "
            "start without the roles that read and append and the claim "
            "that carries them, since with none named nobody is admitted"
        )
    database_url = environ.get("DATABASE_URL", "")
    if not database_url:
        raise ValueError(
            "DATABASE_URL is required; the archive host does not start "
            "without the database its ledgers' events and its journal "
            "are in"
        )
    protocols = _protocols(environ.get("ARCHIVE_PROTOCOLS", ""))
    retiring = _retiring(environ.get("ARCHIVE_RETIRING", ""))
    bindings = SqlAlchemyBindings(database_url)
    access = RoleArchiveAccess(reader, writer)
    keeping = PyposlibKeeping(
        SqlAlchemyKeptEvents(database_url),
        S3ObjectStore(
            endpoint=endpoint,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            region=environ.get("ARCHIVE_S3_REGION") or "us-east-1",
        ),
        protocols,
        retiring,
    )
    # The search index. It reads files through the keeper.
    searching = PyposlibSearching(
        keeping,
        SqlAlchemyIndexedFiles(database_url),
        SqlAlchemyIndexPositions(database_url),
    )

    def create_tables() -> None:
        sqlalchemy_journal.create_tables(database_url)
        schema.create_tables(database_url)

    return create_archive_host(
        JwtBearerToken(
            issuer,
            audience,
            clients,
            key or published_keys(issuer),
            roles_claim,
        ),
        ArchiveUseCases(
            describe=DescribeArchiveUseCase(bindings, access, keeping),
            event=FetchEventUseCase(bindings, access, keeping),
            held=MissingBlocksUseCase(bindings, access, keeping),
            put=PutBlockUseCase(
                bindings, access, keeping, SqlAlchemyBlockPuts(database_url)
            ),
            append=AppendEventUseCase(
                bindings,
                access,
                keeping,
                SqlAlchemyJournal(
                    database_url, build=environ.get("BUILD_SHA") or None
                ),
                SystemClock(),
                uuid.uuid4().hex,
            ),
            read=ReadArchivedUseCase(bindings, access, keeping),
            search=SearchArchiveUseCase(bindings, access, searching),
        ),
        int(
            environ.get("ARCHIVE_MAX_UPLOAD_BYTES") or DEFAULT_MAX_UPLOAD_BYTES
        ),
        # Sealing tools are told to sign in as the first client listed.
        SignIn(
            issuer,
            clients[0],
            tuple(environ.get("ARCHIVE_SCOPES", "").split()) or SCOPES,
        ),
        protocols,
        create_tables,
    )


def _protocols(setting: str) -> tuple[int, ...]:
    """Parse ``ARCHIVE_PROTOCOLS``, such as ``"1,2"``. Empty means every
    version pyposlib supports. A version it does not support is an error.
    """
    chosen = (
        tuple(sorted(int(part) for part in setting.split(",") if part.strip()))
        or DEFAULT_PROTOCOLS
    )
    unknown = [v for v in chosen if v not in remote.VERSIONS]
    if unknown:
        raise ValueError(
            f"ARCHIVE_PROTOCOLS names versions {unknown} the keeping "
            f"library does not speak; it speaks {list(remote.VERSIONS)}"
        )
    return chosen


def _retiring(setting: str) -> dict[int, str]:
    """Parse ``ARCHIVE_RETIRING``, such as ``"1=2027-01-31"``, into a date for
    each version.
    """
    dates: dict[int, str] = {}
    for part in setting.split(","):
        if part.strip():
            version, _, date = part.partition("=")
            dates[int(version)] = date.strip()
    return dates
