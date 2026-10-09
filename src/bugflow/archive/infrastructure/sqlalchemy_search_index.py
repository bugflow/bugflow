"""The search index in the domain Postgres.

Operational storage, not the journal, and not the keeper's: a view of
what the kept blocks hold as text, apart from the bucket and the kept
events, that can be dropped and read again from them. One row
per line of each text file read, by the CID of the file, which is the
same under every ledger that enrols it; one row per file read, text or
not, so a file is read once; and one row per ledger for how many of its
events are read. The tables are created from their definitions here.

Matching is Postgres's: ``strpos`` for literal, and ``~`` for regex,
whose expressions are POSIX's as ``grep -E`` takes them and more. The
more includes back-references, which Postgres matches by backtracking:
``^(aa+)\\1+$`` took 0.8 seconds over one line of 10,007 characters and
8.6 over one of 30,011, measured on a laptop's Postgres 16. The
database is the one the journal and the worker use, so a search is
given a time, and one that outruns it is refused as request.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from psycopg import errors
from sqlalchemy.dialects.postgresql import ARRAY, insert

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.indexed_file import (
    FoundLine,
    IndexedFile,
)
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

archive_index_files = sa.Table(
    "archive_index_files",
    metadata,
    sa.Column("cid", sa.Text, primary_key=True),
    sa.Column("lines", sa.Integer, nullable=False),
    sa.Column("text", sa.Boolean, nullable=False),
    sa.Column(
        "indexed_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

archive_index_lines = sa.Table(
    "archive_index_lines",
    metadata,
    sa.Column("cid", sa.Text, primary_key=True),
    sa.Column("number", sa.Integer, primary_key=True),
    sa.Column("text", sa.Text, nullable=False),
)

archive_index_positions = sa.Table(
    "archive_index_positions",
    metadata,
    sa.Column("ledger_id", sa.Text, primary_key=True),
    sa.Column("events", sa.Integer, nullable=False),
    sa.Column(
        "indexed_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

#: Lines written in one statement. A file of a hundred thousand lines
#: is a few statements rather than one the driver holds whole.
LINES_AT_ONCE = 5000

#: How long a search may take in Postgres before it is refused, unless
#: the adapter is told otherwise.
SEARCH_WITHIN_SECONDS = 10.0

#: How a mode is asked of Postgres, as a condition on a line's text.
_MATCH = {
    "literal": "strpos(line.text, :query) > 0",
    "regex": "line.text ~ :query",
}


class SqlAlchemyIndexedFiles:
    def __init__(
        self, database_url: str, within_seconds: float = SEARCH_WITHIN_SECONDS
    ) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )
        self._within_ms = max(1, round(within_seconds * 1000))

    def indexed(self, cids: Sequence[str]) -> set[str]:
        if not cids:
            return set()
        query = sa.select(archive_index_files.c.cid).where(
            archive_index_files.c.cid.in_(list(cids))
        )
        with self._engine.connect() as connection:
            return {row[0] for row in connection.execute(query)}

    def keep(self, file: IndexedFile) -> None:
        lines = file.lines or ()
        with self._engine.begin() as connection:
            claimed = connection.execute(
                insert(archive_index_files)
                .values(cid=file.cid, lines=len(lines), text=file.is_text)
                .on_conflict_do_nothing(index_elements=["cid"])
                .returning(archive_index_files.c.cid)
            ).first()
            if claimed is None:
                # Indexed already, by an earlier catch-up or one running
                # beside this: the bytes a CID names do not change.
                return
            for start in range(0, len(lines), LINES_AT_ONCE):
                connection.execute(
                    insert(archive_index_lines),
                    [
                        {
                            "cid": file.cid,
                            "number": start + offset + 1,
                            "text": text,
                        }
                        for offset, text in enumerate(
                            lines[start : start + LINES_AT_ONCE]
                        )
                    ],
                )

    def find(
        self, cids: Sequence[str], query: str, mode: str, limit: int
    ) -> list[FoundLine]:
        if not cids:
            return []
        statement = sa.text(
            "SELECT wanted.ordinality - 1 AS position, line.number, line.text "
            "FROM unnest(:cids) WITH ORDINALITY AS wanted(cid, ordinality) "
            "JOIN archive_index_lines AS line ON line.cid = wanted.cid "
            f"WHERE {_MATCH[mode]} "
            "ORDER BY wanted.ordinality, line.number "
            "LIMIT :limit"
        ).bindparams(
            sa.bindparam("cids", list(cids), type_=ARRAY(sa.Text)),
            sa.bindparam("query", query),
            sa.bindparam("limit", limit),
        )
        try:
            with self._engine.begin() as connection:
                # For this transaction alone, so the connection goes back
                # to the pool with no limit of its own.
                connection.execute(
                    sa.text(
                        "SELECT set_config('statement_timeout', :within, true)"
                    ),
                    {"within": str(self._within_ms)},
                )
                rows = connection.execute(statement).all()
        except sa.exc.DataError as error:
            # An expression Postgres does not take.
            raise ArchiveRefusedError(
                "request", f"Not a regular expression: {query}"
            ) from error
        except sa.exc.OperationalError as error:
            if not isinstance(error.orig, errors.QueryCanceled):
                raise
            raise ArchiveRefusedError(
                "request",
                f"The search took longer than {self._within_ms / 1000:g} "
                "seconds; ask a narrower one",
            ) from error
        return [
            FoundLine(position=int(position), number=number, text=text)
            for position, number, text in rows
        ]


class SqlAlchemyIndexPositions:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def position(self, ledger_id: str) -> int:
        query = sa.select(archive_index_positions.c.events).where(
            archive_index_positions.c.ledger_id == ledger_id
        )
        with self._engine.connect() as connection:
            found = connection.execute(query).scalar()
        return int(found) if found is not None else 0

    def advance(self, ledger_id: str, events: int) -> None:
        statement = (
            insert(archive_index_positions)
            .values(ledger_id=ledger_id, events=events)
            .on_conflict_do_update(
                index_elements=["ledger_id"],
                set_={
                    "events": sa.func.greatest(
                        archive_index_positions.c.events, events
                    ),
                    "indexed_at": sa.func.now(),
                },
            )
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
