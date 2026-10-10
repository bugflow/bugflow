"""Tests of a doctrine read from a directory or a file, and of finding
one clause in it."""

from pathlib import Path

import pytest

from bugflow.method.domain.errors import DoctrineNotFoundError
from bugflow.method.domain.models.doctrine import Doctrine
from bugflow.method.infrastructure.doctrine_directory import DirectoryDoctrine
from bugflow.method.infrastructure.doctrine_file import FileDoctrine
from bugflow.method.infrastructure.fixed_doctrine import FixedDoctrine
from bugflow.method.infrastructure.no_doctrine import NoDoctrine


def test_the_files_are_read_in_filename_order(tmp_path: Path) -> None:
    (tmp_path / "02-git.md").write_text("# Git\n\n**RULE-2.** A branch.\n")
    (tmp_path / "01-voice.md").write_text("# Voice\n\n**RULE-1.** Terse.\n")
    (tmp_path / "notes.txt").write_text("not doctrine\n")
    text = DirectoryDoctrine(tmp_path).load().text
    assert (
        text
        == "# Voice\n\n**RULE-1.** Terse.\n# Git\n\n**RULE-2.** A branch.\n"
    )


def test_a_directory_with_no_doctrine_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DoctrineNotFoundError, match="no doctrine under"):
        DirectoryDoctrine(tmp_path).load()


def test_one_file_is_read_as_it_is(tmp_path: Path) -> None:
    one = tmp_path / "01-voice.md"
    one.write_text("**RULE-1.** Terse.\n")
    assert FileDoctrine(one).load().text == "**RULE-1.** Terse.\n"


def test_a_doctrine_already_read_is_given_back() -> None:
    held = Doctrine(text="**RULE-1.** Terse.\n")
    assert FixedDoctrine(held).load() is held


def test_a_server_with_nothing_deployed_has_an_empty_doctrine() -> None:
    assert NoDoctrine().load().text == ""


def test_a_clause_is_quoted_as_it_is_written() -> None:
    doctrine = Doctrine(
        text=(
            "**RULE-1.** Terse.\n\n"
            "**RULE-2. Narrating yourself.** Say what changed,\n"
            "not what you did.\n\n"
            "An example of it.\n"
        )
    )
    assert doctrine.clause("RULE-1") == "**RULE-1.** Terse."
    assert doctrine.clause("RULE-2") == (
        "**RULE-2. Narrating yourself.** Say what changed,\nnot what you did."
    )
    assert doctrine.clause("RULE-3") is None


def test_the_version_follows_the_text() -> None:
    one = Doctrine(text="**RULE-1.** Terse.\n")
    assert len(one.version) == 12
    assert one.version != Doctrine(text="**RULE-1.** Plain.\n").version
