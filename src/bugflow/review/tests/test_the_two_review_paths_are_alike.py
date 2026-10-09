"""Tests that a stocktake's review and a pull request's review ask the
same things of the world.

The four steps of a review are written twice: once for a pull request,
in four modules, and once for a stocktake's range, in ``review_range``.
Two copies of one job can drift apart. These tests fail if one copy
starts to call something the other does not.

What is compared is the set of calls each use case makes on the objects
it was given, such as ``self._agent.dispatch``. The calls are read from
the source of the whole class, so a call made in a helper method counts.

A copy may differ from the other only in the ways listed in ``PAIRS``.
"""

import ast
from pathlib import Path

from bugflow.review import usecases

USECASES = Path(usecases.__file__).resolve().parent
RANGE = "review_range.py"

#: For each step: the pull request's module and class, the stocktake's
#: class, and the calls only the pull request's makes.
#:
#: - Dispatch. A pull request's review may be given a prepared
#:   worktree. It also looks in the journal for a verdict already given
#:   on the same commit, to use it again. A range is reviewed once, and
#:   its runner fetches the repository itself.
#: - Collect. A pull request's write-up is stored in the write-up
#:   store. A stocktake's is recorded in its journal entry.
PAIRS: tuple[tuple[str, str, str, set[str]], ...] = (
    (
        "dispatch_review.py",
        "DispatchReviewUseCase",
        "DispatchRangeReviewUseCase",
        {"_worktrees.prepare", "_journal.events_for_pull_request"},
    ),
    ("wait_review.py", "WaitReviewUseCase", "WaitRangeReviewUseCase", set()),
    (
        "collect_review.py",
        "CollectReviewUseCase",
        "CollectRangeReviewUseCase",
        {"_write_ups.put"},
    ),
    (
        "grade_review.py",
        "GradeReviewUseCase",
        "GradeRangeReviewUseCase",
        set(),
    ),
)


def calls(module: str, class_name: str) -> set[str]:
    """Every call the class makes on an object it holds, written as
    ``_attribute.method``."""
    found: set[str] = set()
    for node in ast.parse((USECASES / module).read_text()).body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            method = call.func
            if not isinstance(method, ast.Attribute):
                continue
            held = method.value
            if (
                isinstance(held, ast.Attribute)
                and isinstance(held.value, ast.Name)
                and held.value.id == "self"
                and held.attr.startswith("_")
            ):
                found.add(f"{held.attr}.{method.attr}")
    return found


def test_each_step_makes_the_same_calls_in_both_paths() -> None:
    drifted = {
        class_name: (
            sorted(calls(module, class_name) - only_the_pull_requests),
            sorted(calls(RANGE, copy)),
        )
        for module, class_name, copy, only_the_pull_requests in PAIRS
        if calls(module, class_name) - only_the_pull_requests
        != calls(RANGE, copy)
    }
    assert not drifted, (
        "the two review paths differ; make the same change to the other, "
        f"or list the difference in PAIRS: {drifted}"
    )


def test_a_listed_difference_is_a_real_one() -> None:
    for module, class_name, copy, only_the_pull_requests in PAIRS:
        assert only_the_pull_requests <= calls(module, class_name), class_name
        assert not only_the_pull_requests & calls(RANGE, copy), copy


def test_every_class_compared_makes_some_call() -> None:
    for module, class_name, copy, _ in PAIRS:
        assert calls(module, class_name), class_name
        assert calls(RANGE, copy), copy
