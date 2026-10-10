"""Readers for a mapping that ``tomllib`` parsed.

A context that reads its own TOML takes typed values out of the parsed
``dict`` and raises an error naming the file when a key is missing or
of the wrong type. The two readers here are the one implementation, so
no two contexts copy them and drift.

A context binds its own ``SchemaError`` subclass into them, so a caller
catches exactly the failure it expects::

    class TopologyError(SchemaError):
        \"\"\"The topology file was not one.\"\"\"

    _require = functools.partial(require, error=TopologyError)
"""

from pathlib import Path

from bugflow.shared.domain.errors import SchemaError


def require[T](
    path: Path,
    mapping: dict[str, object],
    key: str,
    type_: type[T],
    *,
    error: type[SchemaError] = SchemaError,
) -> T:
    """Return ``mapping[key]``, which must be present and of ``type_``.

    The return type follows ``type_``, so ``require(p, m, "k", str)``
    is a ``str`` to the type checker with no narrowing at the call.

    Raises ``error`` naming the path if the key is absent or its value
    is of another type.
    """
    if key not in mapping:
        raise error(path, f"missing required key {key!r}")
    value = mapping[key]
    if not isinstance(value, type_):
        raise error(
            path,
            f"{key!r} must be {type_.__name__}, got {type(value).__name__}",
        )
    return value


def optional[T](
    path: Path,
    mapping: dict[str, object],
    key: str,
    type_: type[T],
    *,
    error: type[SchemaError] = SchemaError,
) -> T | None:
    """Return ``mapping[key]`` if present, else None.

    When present, the value must be of ``type_`` or ``error`` is
    raised, exactly as in ``require``.
    """
    if key not in mapping:
        return None
    value = mapping[key]
    if not isinstance(value, type_):
        raise error(
            path,
            f"{key!r} must be {type_.__name__}, got {type(value).__name__}",
        )
    return value
