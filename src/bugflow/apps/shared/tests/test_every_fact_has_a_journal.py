"""Every event type a context names belongs to one journal (ADR 006).

A fact is written to the journal of its kind, by the map in the shared
kernel, and the adapter refuses a type the map does not have. So a new
fact constant in a context's facts module must have its kind here, or
the first write of it fails on the server rather than in review.
"""

import importlib
import pkgutil

import bugflow
from bugflow.shared.domain.models.journal_kind import KIND_OF, KINDS, kind_of


def facts_named_by_the_contexts() -> set[str]:
    named: set[str] = set()
    for module_info in pkgutil.walk_packages(bugflow.__path__, "bugflow."):
        if not module_info.name.endswith(".domain.facts"):
            continue
        module = importlib.import_module(module_info.name)
        named.update(
            value
            for name, value in vars(module).items()
            if name.isupper() and isinstance(value, str) and "." in value
        )
    return named


def test_every_fact_a_context_names_has_a_journal() -> None:
    named = facts_named_by_the_contexts()
    assert named, "no facts module was found to check"
    assert named <= set(KIND_OF), sorted(named - set(KIND_OF))


def test_every_kind_in_the_map_is_a_journal() -> None:
    assert set(KIND_OF.values()) == set(KINDS)


def test_an_unplaced_fact_is_refused() -> None:
    import pytest

    from bugflow.shared.domain.models.journal_kind import UnplacedFactError

    with pytest.raises(UnplacedFactError):
        kind_of("nobody.wrote")
