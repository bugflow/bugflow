"""Who is let through to a kept ledger, and what the rest are told."""

import pytest

from bugflow.archive.domain.admission import admitted, reader
from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.infrastructure.role_archive_access import (
    RoleArchiveAccess,
)
from bugflow.shared.domain.values.caller import Caller

#: The roles the access adapter is told open the archives.
ARCHIVE_READER = "an-archive-reader"
ARCHIVE_WRITER = "an-archive-writer"

LEDGER = "0f1e2d3c-4b5a-4968-8778-a6b5c4d3e2f1"
UNBOUND = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
BOUND = ArchiveBinding(ledger_id=LEDGER, forge="github", repo="some/one")


def caller(*roles: str) -> Caller:
    return Caller(subject="someone", client="a-client", roles=frozenset(roles))


def bindings() -> InMemoryBindings:
    held = InMemoryBindings()
    held.save(BOUND)
    return held


def refused(operation: object) -> str:
    assert callable(operation)
    with pytest.raises(ArchiveRefusedError) as refusal:
        operation()
    return refusal.value.kind


@pytest.mark.parametrize(
    "roles,reads,appends",
    [
        ((), False, False),
        (("some-other-role",), False, False),
        ((ARCHIVE_READER,), True, False),
        ((ARCHIVE_WRITER,), True, True),
        ((ARCHIVE_READER, ARCHIVE_WRITER), True, True),
    ],
)
def test_two_roles_open_the_archives_and_the_writer_s_reads_too(
    roles: tuple[str, ...], reads: bool, appends: bool
) -> None:
    """A client that seals asks what is kept before it sends, so one
    who may append may read."""
    access = RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER)

    assert access.may_read(caller(*roles), LEDGER) is reads
    assert access.may_append(caller(*roles), LEDGER) is appends


def test_one_who_is_allowed_gets_the_bound_ledger_s_binding() -> None:
    assert admitted(True, bindings(), LEDGER) == BOUND
    assert (
        reader(
            RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER),
            bindings(),
            caller(ARCHIVE_READER),
            LEDGER,
        )
        == BOUND
    )


def test_a_ledger_nobody_bound_is_absent_to_one_who_is_allowed() -> None:
    assert refused(lambda: admitted(True, bindings(), UNBOUND)) == "absent"


@pytest.mark.parametrize("ledger", [LEDGER, UNBOUND])
def test_one_who_is_not_allowed_is_refused_the_same_for_any_ledger(
    ledger: str,
) -> None:
    """So that a caller with no role cannot learn which ledgers are
    kept."""
    assert refused(lambda: admitted(False, bindings(), ledger)) == "access"
    assert (
        refused(
            lambda: reader(
                RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER),
                bindings(),
                caller(),
                ledger,
            )
        )
        == "access"
    )
