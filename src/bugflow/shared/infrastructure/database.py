"""Normalising a database url, for every SQLAlchemy adapter."""


def engine_url(database_url: str) -> str:
    """Accept postgresql:// as a compose file writes it.

    SQLAlchemy needs the psycopg driver named explicitly.
    """
    prefix = "postgresql://"
    if database_url.startswith(prefix):
        return "postgresql+psycopg://" + database_url[len(prefix) :]
    return database_url
