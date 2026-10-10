"""The journal, composed: where the facts go and which build is writing.

The build is a property of the process, not of any fact it records, so
it is read once, by the program, and handed to the journal's adapter to
stamp on every row. Every program that records a fact builds its
journal here rather than constructing the adapter itself, so no program
can be the one that forgets the build. A static test holds the code to
it.

A build is a full git sha or nothing. A branch name, a build number or
``latest`` in the column would read as authoritative and identify no
source tree, so a malformed value raises at startup instead of being
recorded.
"""

import re
from collections.abc import Mapping

from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

#: What a deployment sets to the git sha of the tree its image was built
#: from. Unset locally and in tests, where there is no build to name.
BUILD_VARIABLE = "BUILD_SHA"

_SHA = re.compile(r"[0-9a-f]{40}\Z")


def build_sha(environ: Mapping[str, str]) -> str | None:
    """Return the build this process is, or None where nothing said.

    Raises ``ValueError`` if the value is not a full git sha.
    """
    value = environ.get(BUILD_VARIABLE, "").strip()
    if not value:
        return None
    if not _SHA.match(value):
        raise ValueError(f"{BUILD_VARIABLE} is not a full git sha: {value!r}")
    return value


def stamped_journal(database_url: str, build: str | None) -> SqlAlchemyJournal:
    """Return the Postgres journal, stamping ``build`` on every row it
    writes. ``build`` is what ``build_sha`` read."""
    return SqlAlchemyJournal(database_url, build=build)
