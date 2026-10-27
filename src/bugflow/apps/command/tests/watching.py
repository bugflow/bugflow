"""Settings that watch repositories, for the tests of the commands that
read the watched repositories from a database."""

from datetime import UTC, datetime

from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)


def watching(database_url: str, *names: str) -> None:
    """Set a gnome to observe each repository named, as ``owner/repo``
    on github.com."""
    settings = SqlAlchemyGnomeSettings(database_url)
    for name in names:
        settings.save(
            GnomeSetting(
                forge="github",
                repo=name,
                gnome="prose",
                behaviour="observe",
                set_by="a test",
                set_at=datetime.now(UTC),
            )
        )
