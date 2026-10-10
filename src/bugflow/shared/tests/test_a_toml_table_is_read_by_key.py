"""Tests of the readers that take typed values out of a parsed TOML
table: a path-prefixed message, what is present, absent or of the
wrong type, and a context's own error class."""

from pathlib import Path

import pytest

from bugflow.shared.domain.errors import SchemaError
from bugflow.shared.infrastructure.toml_validation import optional, require

_PATH = Path("a/file.toml")


class _OwnError(SchemaError):
    """Stand-in for a context's own subclass."""


def test_require_returns_the_value_when_present_and_typed() -> None:
    assert require(_PATH, {"k": "v"}, "k", str) == "v"


def test_require_raises_on_a_missing_key() -> None:
    with pytest.raises(SchemaError, match="missing required key 'k'"):
        require(_PATH, {}, "k", str)


def test_require_raises_on_the_wrong_type() -> None:
    with pytest.raises(SchemaError, match="'k' must be str, got int"):
        require(_PATH, {"k": 3}, "k", str)


def test_the_message_opens_with_the_path() -> None:
    with pytest.raises(SchemaError) as raised:
        require(_PATH, {}, "k", str)
    assert str(raised.value) == "a/file.toml: missing required key 'k'"
    assert (raised.value.path, raised.value.message) == (
        _PATH,
        "missing required key 'k'",
    )


def test_optional_returns_none_when_absent() -> None:
    assert optional(_PATH, {}, "k", str) is None


def test_optional_returns_the_value_when_present() -> None:
    assert optional(_PATH, {"k": "v"}, "k", str) == "v"


def test_optional_raises_on_the_wrong_type() -> None:
    with pytest.raises(SchemaError, match="'k' must be str, got int"):
        optional(_PATH, {"k": 3}, "k", str)


def test_the_error_argument_selects_a_contexts_own_subclass() -> None:
    with pytest.raises(_OwnError):
        require(_PATH, {}, "k", str, error=_OwnError)
    with pytest.raises(_OwnError):
        optional(_PATH, {"k": 3}, "k", str, error=_OwnError)
