"""What this deployment will let a run spend, against a real database.

Skipped unless DATABASE_URL names a Postgres server. The in-memory
double answers the same questions, and the two are kept alike on
purpose.
"""

import uuid

import sqlalchemy as sa

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.infrastructure.sqlalchemy_spend_bindings import (
    SqlAlchemySpendBindings,
)
from bugflow.shared.domain.values.budget import Budget


def repo() -> str:
    return f"example/{uuid.uuid4()}"


def bind(
    bindings: SqlAlchemySpendBindings, scope: SpendScope, usd: float
) -> None:
    bindings.declare(
        SpendBinding(scope=scope, budget=Budget(usd=usd, turns=10))
    )


def allowed(
    bindings: SqlAlchemySpendBindings,
    name: str,
    layer: str = "weekly",
    agent: str = "safety",
) -> list[float | None]:
    return [
        one.budget.usd
        for one in bindings.binding_for("github", name, layer, agent)
    ]


def test_a_ceiling_bound_to_a_repository_applies_to_it(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    bind(bindings, SpendScope(forge="github", repo=name), 2.5)
    assert allowed(bindings, name) == [2.5]


def test_a_scope_nothing_bound_is_allowed_nothing(
    engine: sa.Engine, database_url: str
) -> None:
    """Empty rather than a figure: silence is not consent."""
    bindings = SqlAlchemySpendBindings(database_url)
    assert allowed(bindings, repo()) == []


def test_every_binding_that_matches_is_answered(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    bind(bindings, SpendScope(forge="github", repo=name), 2.5)
    bind(
        bindings,
        SpendScope(
            forge="github", repo=name, layer="weekly", agent_id="safety"
        ),
        9.0,
    )
    assert allowed(bindings, name) == [9.0, 2.5]
    # And the repository's own ceiling still covers everything else.
    assert allowed(bindings, name, "pull-request", "style") == [2.5]


def test_one_repositorys_ceiling_is_not_anothers(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemySpendBindings(database_url)
    mine, theirs = repo(), repo()
    bind(bindings, SpendScope(forge="github", repo=mine), 2.5)
    assert allowed(bindings, theirs) == []


def test_declaring_a_scope_twice_replaces_its_ceiling(
    engine: sa.Engine, database_url: str
) -> None:
    """A cap is changed by writing it again, which is the point of
    keeping it out of the code."""
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    scope = SpendScope(forge="github", repo=name)
    bind(bindings, scope, 2.5)
    bind(bindings, scope, 7.0)
    assert allowed(bindings, name) == [7.0]


def test_every_ceiling_can_be_listed_most_specific_first(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    bind(bindings, SpendScope(forge="github", repo=name), 2.5)
    bind(
        bindings,
        SpendScope(forge="github", repo=name, agent_id="safety"),
        9.0,
    )
    mine = [one for one in bindings.bindings() if one.scope.repo == name]
    assert [one.scope.parts for one in mine] == [3, 2]


def test_a_ceiling_bound_to_nothing_covers_everything(
    engine: sa.Engine, database_url: str
) -> None:
    """One row caps the whole deployment. The unscoped row is a single
    key, so writing it twice replaces it rather than accumulating: empty
    columns and not nulls, because null is not equal to null and two
    unscoped rows would both be allowed in."""
    bindings = SqlAlchemySpendBindings(database_url)
    bind(bindings, SpendScope(), 1.0)
    bind(bindings, SpendScope(), 3.0)
    assert allowed(bindings, repo(), "nightly", "anyone") == [3.0]


def test_a_binding_says_what_shares_it_and_defaults_to_one_run(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    bind(bindings, SpendScope(forge="github", repo=name), 2.5)
    (one,) = [
        binding
        for binding in bindings.bindings()
        if binding.scope.repo == name
    ]
    assert one.per == "event"


def test_a_weekly_allowance_is_stored_as_the_same_row(
    engine: sa.Engine, database_url: str
) -> None:
    """Same table, same scope, one field apart: what shares it."""
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    bindings.declare(
        SpendBinding(
            scope=SpendScope(forge="github", repo=name),
            budget=Budget(usd=50.0, turns=0),
            per="weekly",
        )
    )
    (one,) = [
        binding
        for binding in bindings.bindings()
        if binding.scope.repo == name
    ]
    assert (one.per, one.budget.usd) == ("weekly", 50.0)


def test_one_scope_holds_a_limit_per_event_and_per_period(
    engine: sa.Engine, database_url: str
) -> None:
    """The denominator is part of the key. Were the key the scope alone,
    binding an allowance per night to a repository would replace the
    one per event bound to the same repository, and nothing would be
    allowed per event."""
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    scope = SpendScope(forge="github", repo=name)
    bindings.declare(
        SpendBinding(scope=scope, budget=Budget(usd=2.5, turns=60))
    )
    bindings.declare(
        SpendBinding(
            scope=scope, budget=Budget(usd=10.0, turns=None), per="nightly"
        )
    )
    # This repository's own rows: an unscoped binding matches everything
    # and would collapse into the same denominator here.
    found = {
        one.per: one.budget.usd
        for one in bindings.binding_for("github", name, "weekly", "safety")
        if one.scope.repo == name
    }
    assert found == {"event": 2.5, "nightly": 10.0}


def test_declaring_one_denominator_leaves_the_other(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    scope = SpendScope(forge="github", repo=name)
    bindings.declare(
        SpendBinding(scope=scope, budget=Budget(usd=2.5, turns=60))
    )
    bindings.declare(
        SpendBinding(
            scope=scope, budget=Budget(usd=10.0, turns=None), per="nightly"
        )
    )
    bindings.declare(
        SpendBinding(
            scope=scope, budget=Budget(usd=20.0, turns=None), per="nightly"
        )
    )
    found = {
        one.per: one.budget.usd
        for one in bindings.binding_for("github", name, "weekly", "safety")
        if one.scope.repo == name
    }
    assert found == {"event": 2.5, "nightly": 20.0}


def test_revoking_one_denominator_leaves_the_other(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    scope = SpendScope(forge="github", repo=name)
    bindings.declare(
        SpendBinding(scope=scope, budget=Budget(usd=2.5, turns=60))
    )
    bindings.declare(
        SpendBinding(
            scope=scope, budget=Budget(usd=10.0, turns=None), per="nightly"
        )
    )
    bindings.revoke(scope, "nightly")
    mine = [
        one
        for one in bindings.binding_for("github", name, "weekly", "safety")
        if one.scope.repo == name
    ]
    assert [(one.per, one.budget.usd) for one in mine] == [("event", 2.5)]


def test_revoking_what_was_never_bound_changes_nothing(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemySpendBindings(database_url)
    name = repo()
    bindings.revoke(SpendScope(forge="github", repo=name), "nightly")
    assert [
        one
        for one in bindings.binding_for("github", name, "", "")
        if one.scope.repo == name
    ] == []
