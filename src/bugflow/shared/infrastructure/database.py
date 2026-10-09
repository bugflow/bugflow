"""A helper for database URLs, used by every adapter that talks to Postgres
through SQLAlchemy.
"""


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
