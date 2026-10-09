"""Tests of ``engine_url``, which adds the driver name to a Postgres URL."""

from bugflow.shared.infrastructure.database import engine_url


def test_a_plain_postgres_url_is_given_the_psycopg_driver() -> None:
    assert (
        engine_url("postgresql://someone:secret@db.invalid:5432/kept")
        == "postgresql+psycopg://someone:secret@db.invalid:5432/kept"
    )


def test_a_url_that_names_a_driver_is_left_as_it_is() -> None:
    for url in (
        "postgresql+psycopg://someone@db.invalid/kept",
        "sqlite:///kept.db",
    ):
        assert engine_url(url) == url
