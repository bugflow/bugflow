"""The search index, in Postgres.

The index is a copy of the text in the stored files, arranged for
searching. It can be deleted and rebuilt from the stored files at any time.

Three tables:

- one row for each file looked at, text or not, so that no file is fetched
  twice;
- one row for each line of each text file;
- one row for each ledger, saying how many of its events the index has
  covered.

Files are identified by CID, so a file that appears in several ledgers is
indexed once.

Matching is done by Postgres: ``strpos`` for the literal mode and the ``~``
operator for regex. Postgres regular expressions include everything ``grep
-E`` accepts, and more.

A search has a time limit. Some regular expressions are very slow:
``^(aa+)\\1+$`` took 0.8 seconds on one line of 10,007 characters and 8.6
seconds on one of 30,011, on a laptop running Postgres 16. Other parts of
the system use the same database, so a search that runs over the limit is
stopped and refused.
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

#: How many lines are inserted in one statement. A very long file is written in
#: several statements, so no single one is huge.
LINES_AT_ONCE = 5000

#: The time limit for one search, in seconds, unless the adapter is given
#: another.
SEARCH_WITHIN_SECONDS = 10.0

#: The SQL condition used for each search mode.
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
                # Already in the index, from an earlier catch-up or one running
                # at the same time. Nothing to do: a CID always names the same
                # content.
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
                # The time limit applies to this transaction only, so the
                # connection returns to the pool without it.
                connection.execute(
                    sa.text(
                        "SELECT set_config('statement_timeout', :within, true)"
                    ),
                    {"within": str(self._within_ms)},
                )
                rows = connection.execute(statement).all()
        except sa.exc.DataError as error:
            # Postgres could not parse the regular expression.
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
