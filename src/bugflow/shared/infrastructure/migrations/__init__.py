"""The scripts that bring a database's tables up to date.

Each script in ``versions/`` makes one change to the tables. A database
records the last script it ran in the table ``bugflow_schema_version``,
and ``upgrade`` runs the scripts it has not run yet, in order.

A script states the change in full. It does not import a table definition
from an adapter, so a script written today makes the same change when it is
run next year.

A deployment with tables of its own keeps their scripts in a directory of
its own, as a branch of this package's: each declares ``depends_on`` the
package script whose table it needs. ``upgrade`` and ``pending`` take those
directories, and run or list the package's scripts and the deployment's
together, recorded in the one version table.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from bugflow.shared.infrastructure.database import engine_url

#: Where a database records the last script it ran.
VERSION_TABLE = "bugflow_schema_version"

#: The setting that names a deployment's own script directories, each a
#: path or a package resource such as ``their_package.migrations:versions``,
#: separated by whitespace.
SCRIPTS_SETTING = "DATABASE_SCRIPTS"

# The advisory lock held while scripts run. Any number will do, so long
# as everything that runs these scripts uses the same one.
_LOCK = 4_812_163_577_031


def locations(setting: str | None) -> list[str]:
    """The script directories a deployment's ``DATABASE_SCRIPTS`` names."""
    return (setting or "").split()


def _config(scripts: Sequence[str]) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent))
    # A resource name holds a colon, so the locations are separated by a
    # line break rather than the path separator.
    config.set_main_option("path_separator", "newline")
    config.set_main_option(
        "version_locations",
        "\n".join([str(Path(__file__).parent / "versions"), *scripts]),
    )
    return config


def pending(database_url: str, scripts: Sequence[str] = ()) -> list[str]:
    """Return the names of the scripts the database has not run yet, in
    the order ``upgrade`` would run them. Empty when it is up to date.
    """
    directory = ScriptDirectory.from_config(_config(scripts))
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"version_table": VERSION_TABLE}
            )
            ran = context.get_current_heads()
    finally:
        engine.dispose()
    # Every script, newest first, less those the database has run and
    # their ancestors. A walk from the heads down to what was run would
    # miss a branch the database has not recorded yet.
    done = (
        {
            script.revision
            for script in directory.iterate_revisions(ran, "base")
        }
        if ran
        else set()
    )
    not_run = [
        script
        for script in directory.iterate_revisions("heads", "base")
        if script.revision not in done
    ]
    return [Path(script.path).stem for script in reversed(not_run)]


def upgrade(database_url: str, scripts: Sequence[str] = ()) -> None:
    """Run every script the database has not run yet.

    Programs that start at the same moment may all call this. One runs
    the scripts while the others wait, and then find nothing left to
    run.
    """
    _run(
        database_url, scripts, lambda config: command.upgrade(config, "heads")
    )


def downgrade(
    database_url: str, revision: str, scripts: Sequence[str] = ()
) -> None:
    """Reverse the scripts run after ``revision``, newest first, so a
    deployment can return to an earlier tag. A script that cannot be
    reversed raises and says why.
    """
    _run(
        database_url,
        scripts,
        lambda config: command.downgrade(config, revision),
    )


def _run(
    database_url: str,
    scripts: Sequence[str],
    run: Callable[[Config], None],
) -> None:
    config = _config(scripts)
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
                    run(config)
            finally:
                connection.execute(
                    sa.select(sa.func.pg_advisory_unlock(_LOCK))
                )
                connection.commit()
    finally:
        engine.dispose()
