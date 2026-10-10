"""The journal's build is stamped in one place, so no program forgets it.

A build is read from the environment by the program and handed to the
adapter, which writes it on every row. A program that built the adapter
itself would pass no build, and the rows it wrote would be null among
rows that are not: a gap that looks like history rather than an
omission.

Statically, because the failure is a program nobody ran in a test.
"""

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[3]

#: Where the adapter is defined, and the one place that builds it.
ALLOWED = {
    "shared/infrastructure/sqlalchemy_journal.py",
    "apps/shared/journals.py",
}


def constructors() -> list[str]:
    """Every module outside a tests directory that constructs the
    adapter. A test builds it against its own database."""
    return sorted(
        str(path.relative_to(SOURCE))
        for path in SOURCE.rglob("*.py")
        if "tests" not in path.relative_to(SOURCE).parts
        and re.search(r"\bSqlAlchemyJournal\(", path.read_text())
    )


def test_the_journal_is_built_where_its_build_is_known() -> None:
    assert set(constructors()) <= ALLOWED, constructors()


def test_the_one_place_builds_it() -> None:
    """A check that finds nothing passes whatever the code does."""
    assert "apps/shared/journals.py" in constructors()
