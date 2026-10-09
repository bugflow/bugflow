"""The archive host: a keeper of the remote archive protocol, over HTTP.

A ledger bound here has a base URL of its own, the host whose first
label is the ledger's id, and the protocol's requests are made beneath
it. One origin for each ledger, because what an archive holds is
content somebody else wrote: served from an origin of its own, it can
reach nothing a browser holds for another.

The wire is the sealing library's: each request is handed to pyposlib's
``handle``, which reads it as the protocol writes it and asks a keeper.
The keeper it is given here is the archive context's use cases for the
ledger and the caller, so who may read and append is decided there, and
what is kept is verified there.

Every request to a ledger carries a bearer token, checked here before
anything else is read. A refused token answers 401, a caller without
access 403 and a ledger not bound 404, in that order, so nobody without
access learns which ledgers are kept. An append's body is not read
until its caller is known to be allowed the ledger, and is refused as
size beyond ``ARCHIVE_MAX_UPLOAD_BYTES``. Under version 2 of the
protocol a block is put on its own, at most one raw leaf, and the
blocks a client asks after come as a list; neither body is read beyond
a block's size, whatever an append is allowed. The versions served are
``ARCHIVE_PROTOCOLS``, and ``ARCHIVE_RETIRING`` names the date after
which one may stop being served.

A person's sealing tool has to get that token somewhere, so the host
says how, as the protocol lets a keeper say: a 401 names an address, and
at that address, with no token, is the issuer, the scopes to ask for and
the public client to sign in as.

Search is answered from an index kept beside the keeper, which the host
lists the modes of in describe.

A host that names no ledger answers its root as the healthcheck and
nothing else.

Run by uvicorn with --factory, as :func:`from_environment`.
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

#: The largest append taken when the environment sets no other. An
#: append is held whole in memory while it is verified.
DEFAULT_MAX_UPLOAD_BYTES = 64 * 1024 * 1024

#: The versions of the protocol served when the environment sets no
#: other: both, until version 1 is retired.
DEFAULT_PROTOCOLS: tuple[int, ...] = remote.VERSIONS

#: A ledger's id as a host's first label: a UUID as an event writes it.
_LEDGER = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)

#: Sent with every answer. What is read is what a scope sealed, so a
#: browser is told to take the declared type and to run nothing in it.
_UNTRUSTED = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
}


#: The scopes a sealing tool is told to ask for when the environment
#: names none: OpenID Connect's own, which every provider takes.
SCOPES: tuple[str, ...] = ("openid",)

#: Where the host says how to sign in, at its own origin (RFC 9728).
SIGN_IN_PATH = "/.well-known/oauth-protected-resource"


@dataclass(frozen=True)
class SignIn:
    """What the host tells a sealing tool about signing in: the issuer,
    the public client to sign in as, and the scopes to ask for."""

    issuer: str
    client_id: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class ArchiveUseCases:
    """The use cases the host serves, one for each of the protocol's
    operations."""

    describe: DescribeArchiveUseCase
    event: FetchEventUseCase
    held: MissingBlocksUseCase
    put: PutBlockUseCase
    append: AppendEventUseCase
    read: ReadArchivedUseCase
    #: None for a host that does not search, which describes no search
    #: member and refuses the operation as absent.
    search: SearchArchiveUseCase | None = None


def _refusing[T](operation: Callable[[], T]) -> T:
    """What the operation returns, its refusal carried as the wire's."""
    try:
        return operation()
    except ArchiveRefusedError as refused:
        raise Refused(refused.kind, str(refused)) from refused


class _Kept:
    """One ledger, for one caller, as the keeper the wire asks: the
    operations, each answered by its use case. ``protocols`` is what the
    wire reads to refuse a request in a version not served.

    What it last described is kept until an append or a put, so that
    the wire's question before an append, how many events there are, is
    not asked of the ledger a second time.
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
            # The protocol's describe names a ledger by what its events
            # say, so a ledger with none has no id yet.
            "ledger_id": kept.ledger_id if kept.events else None,
            "head": kept.head,
            "events": kept.events,
            "root": kept.root,
            "erased": list(kept.erased),
        }
        # A keeper of version 1 alone describes as that version did.
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
            # The wire's shape, as section 12 of the protocol has it.
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
    """The ledger a host names by its first label, or None."""
    label = host.split(":", 1)[0].split(".", 1)[0].lower()
    return label if _LEDGER.fullmatch(label) else None


def _answer(status: int, kind: str, body: bytes) -> Response:
    return Response(body, status, _UNTRUSTED, kind)


def _refusal(kind: str, message: str, status: int | None = None) -> Response:
    """A refusal as the protocol writes one: the status its kind has,
    and the kind and a message for a person."""
    return _answer(
        status or remote.STATUS.get(kind, 422),
        remote.JSON,
        encoded({"refused": kind, "message": message}),
    )


def _origin(request: Request) -> str:
    """The origin the request was made to. The edge ends TLS and says so,
    and without an edge the request's own scheme is the one."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.headers.get('host', '')}"


def _path(request: Request) -> str:
    """The request's path as it was sent, its percent-encoding intact,
    with its query: the wire decodes a read's path and a search's
    parameters itself."""
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
    """The host over ``usecases``. ``protocols`` is what the wire refuses
    by; the keeping side the use cases wrap is given the same, and lists
    it in describe. ``on_start`` is run once, when the server starts and
    before it takes a request."""

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
        """The request's body, or None for one larger than ``limit``."""
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
        """How large a body the request may have, and what to call it: an
        append as much as is taken, a block or a list of CIDs one block."""
        if request.method == "POST" and _path(request) == "/events":
            return max_upload_bytes, "An append"
        return remote.BLOCK_LIMIT, "A block"

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT"])
    async def wire(request: Request) -> Response:
        """One request of the remote archive protocol, to the ledger the
        host names."""
        if (
            sign_in is not None
            and request.method == "GET"
            and request.url.path == SIGN_IN_PATH
        ):
            # Asked with no token, of any host: it is how one is had.
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
            # A deploy's probe asks a route's root whether it answers,
            # and names no ledger when it does.
            if request.method == "GET" and request.url.path == "/":
                return _answer(200, remote.JSON, encoded({"ok": True}))
            return _refusal("absent", "This host names no ledger")
        # On a thread, as every call below that waits is: checking a
        # token may fetch the issuer's keys, and the wait would hold
        # every other request here.
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
    """The archive host as uvicorn runs it, with --factory.

    It does not start without what it cannot work without:

    - ARCHIVE_ISSUER, ARCHIVE_AUDIENCE and ARCHIVE_CLIENTS, since with
      any missing no token could be checked;
    - ARCHIVE_ROLES_CLAIM, the claim of a token that carries a person's
      roles, and ARCHIVE_READER_ROLE and ARCHIVE_WRITER_ROLE, the roles
      that read and append, since with none named nobody is admitted;
    - the bucket its blocks are kept in, since a keeper with nowhere to
      keep them would record events whose bytes it does not hold;
    - DATABASE_URL, where the ledgers' events and the journal are.

    ARCHIVE_SCOPES is the scopes a sealing tool is told to ask for at
    sign-in, separated by spaces, "openid" unless set: a provider that
    puts roles or an audience in a token only when asked has its own
    names for asking. ARCHIVE_PROTOCOLS, "1,2" unless set, is the
    versions of the protocol served, and ARCHIVE_RETIRING, as
    "1=2027-01-31", the date after which a version may stop being
    served. BUILD_SHA, where set, is stamped on every fact recorded.

    When the server starts it creates the tables its database lacks.
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
    # The index beside the keeper, reading through the keeper's own
    # reading operations.
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
        # The first client named is the one a sealing tool signs in as.
        SignIn(
            issuer,
            clients[0],
            tuple(environ.get("ARCHIVE_SCOPES", "").split()) or SCOPES,
        ),
        protocols,
        create_tables,
    )


def _protocols(setting: str) -> tuple[int, ...]:
    """The versions ARCHIVE_PROTOCOLS names, "1,2" by default. A version
    this keeper's library does not speak is refused at start."""
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
    """The dates ARCHIVE_RETIRING names, as "1=2027-01-31", by version."""
    dates: dict[int, str] = {}
    for part in setting.split(","):
        if part.strip():
            version, _, date = part.partition("=")
            dates[int(version)] = date.strip()
    return dates
