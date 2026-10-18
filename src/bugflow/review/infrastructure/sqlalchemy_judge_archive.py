"""The store of judge exchanges in a Postgres table.

An exchange is stored under a hash of its request and response. The
table is made by the scripts in ``migrations``.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert

from bugflow.review.domain.errors import ExchangeNotFoundError
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.shared.domain.errors import ContentTooLargeError
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()
exchanges = sa.Table(
    "judge_exchanges",
    metadata,
    sa.Column("exchange_id", sa.Text, primary_key=True),
    sa.Column(
        "stored_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("request", JSONB, nullable=False),
    sa.Column("response", JSONB, nullable=False),
)


class SqlAlchemyJudgeArchive:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def put(self, exchange: JudgeExchange) -> str:
        exchange_id = exchange.exchange_id
        statement = (
            insert(exchanges)
            .values(
                exchange_id=exchange_id,
                request=exchange.request,
                response=exchange.response,
            )
            .on_conflict_do_nothing(index_elements=["exchange_id"])
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
        return exchange_id

    def get(self, exchange_id: str) -> JudgeExchange:
        query = sa.select(exchanges.c.request, exchanges.c.response).where(
            exchanges.c.exchange_id == exchange_id
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).one_or_none()
        if row is None:
            raise ExchangeNotFoundError(f"no archived exchange {exchange_id}")
        return JudgeExchange(request=row.request, response=row.response)

    def get_bounded(
        self, exchange_id: str, max_bytes: int
    ) -> tuple[JudgeExchange, int]:
        size: sa.ColumnElement[int] = sa.literal(1024)
        for column in (exchanges.c.request, exchanges.c.response):
            size = size + sa.func.octet_length(
                sa.func.convert_to(sa.cast(column, sa.Text), "UTF8")
            )
        query = sa.select(
            size.label("bytes"),
            sa.case((size <= max_bytes, exchanges.c.request)).label("request"),
            sa.case((size <= max_bytes, exchanges.c.response)).label(
                "response"
            ),
        ).where(exchanges.c.exchange_id == exchange_id)
        with self._engine.connect() as connection:
            row = connection.execute(query).one_or_none()
        if row is None:
            raise ExchangeNotFoundError(f"no archived exchange {exchange_id}")
        if row.bytes > max_bytes:
            raise ContentTooLargeError("exchange exceeds the byte allowance")
        return JudgeExchange(
            request=row.request, response=row.response
        ), row.bytes
