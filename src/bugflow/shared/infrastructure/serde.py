"""Turning domain objects into what a database column holds, and back.

Domain objects are frozen dataclasses. A database stores them in one of
two ways: as JSON in a single column, or as typed values across several
columns. The four functions here do both conversions in both directions,
so that every adapter writes and reads the same way.

They use pydantic's ``TypeAdapter``, which reads a class's type
annotations. That is what lets the reading functions rebuild the exact
types: a tuple comes back as a tuple, although JSON only has lists.
"""

from typing import Any

from pydantic import TypeAdapter


def to_json(obj: Any) -> dict[str, Any]:
    """Convert a domain object to a dictionary that can be stored as
    JSON. A UUID or a time becomes a string."""
    dumped = TypeAdapter(type(obj)).dump_python(obj, mode="json")
    return dict(dumped)


def from_json[T](kind: type[T], data: Any) -> T:
    """Rebuild a domain object of type ``kind`` from what ``to_json``
    produced."""
    return TypeAdapter(kind).validate_python(data)


def to_columns(obj: Any) -> dict[str, Any]:
    """Convert a domain object to a dictionary of typed values, one for
    each column. Unlike ``to_json``, a UUID stays a UUID and a time stays
    a time, because the database driver wants the Python objects."""
    dumped = TypeAdapter(type(obj)).dump_python(obj)
    return dict(dumped)


def from_columns[T](kind: type[T], row: Any) -> T:
    """Rebuild a domain object of type ``kind`` from a database row whose
    columns are named after its fields."""
    return TypeAdapter(kind).validate_python(dict(row))
