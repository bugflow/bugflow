"""Tests of setting what a gnome does on a repository (ADR 008): each
change is recorded with who made it and what it replaced, and a gnome
or profile the deployment in force does not hold is refused."""

from datetime import UTC, datetime

import pytest

from bugflow.review.domain.facts import GNOME_SET
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.dtos.set_gnome import SetGnomeRequest
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.review.usecases.set_gnome import (
    SetGnomeUseCase,
    UnknownGnomeError,
)
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

PROFILES = {"pr-gnome": ("default", "strict"), "repo-gnome": ("default",)}


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 27, tzinfo=UTC)


def request(**changed: object) -> SetGnomeRequest:
    values: dict[str, object] = {
        "forge": "github",
        "repo": "example/widgets",
        "gnome": "pr-gnome",
        "behaviour": "advise",
        "set_by": "operator@example.org",
        "profiles": PROFILES,
    }
    return SetGnomeRequest.model_validate(values | changed)


def setting_up() -> tuple[
    InMemoryGnomeSettings, InMemoryJournal, SetGnomeUseCase
]:
    settings, journal = InMemoryGnomeSettings(), InMemoryJournal()
    return (
        settings,
        journal,
        SetGnomeUseCase(settings, journal, FixedClock(), "run-1"),
    )


def test_a_setting_is_saved_and_recorded_with_who_made_it() -> None:
    settings, journal, use_case = setting_up()

    answered = use_case.execute(request(profile="strict"))

    assert answered.changed
    assert answered.was_behaviour is None
    (held,) = settings.settings_of("github", "example/widgets")
    assert (held.gnome, held.behaviour, held.profile, held.set_by) == (
        "pr-gnome",
        "advise",
        "strict",
        "operator@example.org",
    )
    (entry,) = journal.entries
    assert entry.event_type == GNOME_SET
    assert entry.agent_id == "pr-gnome"
    assert entry.payload["set_by"] == "operator@example.org"


def test_a_change_records_what_it_replaced() -> None:
    _, journal, use_case = setting_up()
    use_case.execute(request(behaviour="observe"))

    answered = use_case.execute(request(behaviour="gate"))

    assert (answered.was_behaviour, answered.was_profile) == (
        "observe",
        "default",
    )
    assert journal.entries[-1].payload["was_behaviour"] == "observe"


def test_setting_a_gnome_to_what_it_is_records_nothing() -> None:
    _, journal, use_case = setting_up()
    use_case.execute(request())

    assert not use_case.execute(request(set_by="someone else")).changed
    assert len(journal.entries) == 1


@pytest.mark.parametrize(
    ("changed", "problem"),
    [
        ({"gnome": "other-gnome"}, "'other-gnome' is not a gnome"),
        ({"profile": "lenient"}, "'lenient' is not a profile of pr-gnome"),
    ],
)
def test_a_gnome_or_profile_not_in_force_is_refused(
    changed: dict[str, object], problem: str
) -> None:
    settings, journal, use_case = setting_up()
    with pytest.raises(UnknownGnomeError, match=problem):
        use_case.execute(request(**changed))
    assert settings.settings() == ()
    assert journal.entries == []


def test_a_behaviour_says_what_the_gnome_may_do() -> None:
    def gnome(behaviour: str) -> GnomeSetting:
        return GnomeSetting(
            forge="github",
            repo="example/widgets",
            gnome="pr-gnome",
            behaviour=behaviour,  # type: ignore[arg-type]
        )

    assert [
        (one.judges, one.publishes, one.gates)
        for one in map(gnome, ("off", "observe", "advise", "gate"))
    ] == [
        (False, False, False),
        (True, False, False),
        (True, True, False),
        (True, True, True),
    ]
    with pytest.raises(ValueError, match="'loud' is no behaviour"):
        gnome("loud")
