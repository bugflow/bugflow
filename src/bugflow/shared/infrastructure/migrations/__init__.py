"""The scripts that bring a database's tables up to date.

Each script in ``versions/`` makes one change to the tables. A database
records the last script it ran in the table ``bugflow_schema_version``,
and ``upgrade`` runs the scripts it has not run yet, in order.

A script states the change in full. It does not import a table definition
from an adapter, so a script written today makes the same change when it is
run next year.
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from bugflow.shared.infrastructure.database import engine_url

#: Where a database records the last script it ran.
VERSION_TABLE = "bugflow_schema_version"

# The advisory lock held while scripts run. Any number will do, so long
# as everything that runs these scripts uses the same one.
_LOCK = 4_812_163_577_031


def upgrade(database_url: str) -> None:
    """Run every script the database has not run yet.

    Programs that start at the same moment may all call this. One runs
    the scripts while the others wait, and then find nothing left to
    run.
    """
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent))
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            # The lock belongs to the connection, not to a transaction,
            # so it is held until it is released below.
            connection.execute(sa.select(sa.func.pg_advisory_lock(_LOCK)))
            connection.commit()
            try:
                config.attributes["connection"] = connection
                with connection.begin():
                    command.upgrade(config, "head")
            finally:
                connection.execute(
                    sa.select(sa.func.pg_advisory_unlock(_LOCK))
                )
                connection.commit()
    finally:
        engine.dispose()
