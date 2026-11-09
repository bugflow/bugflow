"""Helpers for database URLs and engines, used by every adapter that
talks to Postgres through SQLAlchemy.
"""

import threading

import sqlalchemy as sa


def engine_url(database_url: str) -> str:
    """Turn ``postgresql://...`` into ``postgresql+psycopg://...``.

    Configuration usually gives the short form. SQLAlchemy needs the driver
    named, and this project uses psycopg. Any other URL is returned
    unchanged.
    """
    prefix = "postgresql://"
    if database_url.startswith(prefix):
        return "postgresql+psycopg://" + database_url[len(prefix) :]
    return database_url


_engines: dict[str, sa.Engine] = {}
_lock = threading.Lock()


def shared_engine(database_url: str) -> sa.Engine:
    """The engine for a database, one for each process.

    Every adapter gets its engine here, so a process holds one pool of
    connections to each database, however many adapters it builds. The
    engine checks each connection before it lends it out.
    """
    url = engine_url(database_url)
    with _lock:
        engine = _engines.get(url)
        if engine is None:
            engine = _engines[url] = sa.create_engine(url, pool_pre_ping=True)
        return engine


def dispose_engine(database_url: str) -> None:
    """Close the engine for a database and its connections. The next
    ``shared_engine`` for it makes a new one."""
    with _lock:
        engine = _engines.pop(engine_url(database_url), None)
    if engine is not None:
        engine.dispose()
