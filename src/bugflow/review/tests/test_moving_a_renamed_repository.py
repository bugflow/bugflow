"""Tests of moving a renamed repository's settings and declarations to
its new name (ADR 008).

Each gnome set on the old name is set the same on the new, unless the
new name has its own setting, and is switched off on the old. The old
name's boundaries and withheld share go with it where the new name has
declared none, so the new name never stands watched without its
boundary. Each change is recorded as any setting or declaration is.
"""

from dataclasses import dataclass

from bugflow.review.domain.facts import (
    BOUNDARY_DECLARED,
    GNOME_SET,
    WITHHOLDING_DECLARED,
)
from bugflow.review.domain.models.gnome_setting import Behaviour, GnomeSetting
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.domain.models.withholding import Withholding
from bugflow.review.dtos.move_repository_settings import (
    MoveRepositorySettingsRequest,
)
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.review.infrastructure.in_memory_layer_boundaries import (
    InMemoryLayerBoundaries,
)
from bugflow.review.infrastructure.in_memory_withholding import (
    InMemoryWithholding,
)
from bugflow.review.tests.test_setting_a_gnome import FixedClock
from bugflow.review.usecases.move_repository_settings import (
    MoveRepositorySettingsUseCase,
)
from bugflow.review.usecases.set_gnome import SetGnomeUseCase
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

MOVE = MoveRepositorySettingsRequest(
    forge="github", repo="o/old", to="o/new", set_by="bugflow poll"
)


@dataclass
class Server:
    settings: InMemoryGnomeSettings
    boundaries: InMemoryLayerBoundaries
    withholding: InMemoryWithholding
    journal: InMemoryJournal

    @property
    def mover(self) -> MoveRepositorySettingsUseCase:
        clock = FixedClock()
        return MoveRepositorySettingsUseCase(
            self.settings,
            SetGnomeUseCase(self.settings, self.journal, clock, "run-1"),
            self.boundaries,
            self.withholding,
            self.journal,
            clock,
            "run-1",
        )

    def what(self, repo: str) -> set[tuple[str, ...]]:
        return {
            (one.tenant, one.gnome, one.behaviour, one.profile, one.set_by)
            for one in self.settings.settings_of("github", repo)
        }

    def behaviours(self, repo: str) -> set[str]:
        return {one[2] for one in self.what(repo)}

    def events(self) -> list[str]:
        return [entry.event_type for entry in self.journal.entries]


def holding(
    *settings: GnomeSetting,
    boundaries: tuple[LayerBoundary, ...] = (),
    withheld: tuple[Withholding, ...] = (),
) -> Server:
    server = Server(
        InMemoryGnomeSettings(),
        InMemoryLayerBoundaries(),
        InMemoryWithholding(),
        InMemoryJournal(),
    )
    for one in settings:
        server.settings.save(one)
    for boundary in boundaries:
        server.boundaries.declare(boundary)
    for share in withheld:
        server.withholding.declare(share)
    return server


def setting(
    repo: str,
    gnome: str,
    behaviour: Behaviour,
    profile: str = "default",
    tenant: str = "default",
) -> GnomeSetting:
    return GnomeSetting(
        forge="github",
        repo=repo,
        gnome=gnome,
        behaviour=behaviour,
        profile=profile,
        tenant=tenant,
    )


def boundary(repo: str, layer: str, at: str) -> LayerBoundary:
    return LayerBoundary(forge="github", repo=repo, layer=layer, boundary=at)


def test_each_gnome_moves_to_the_new_name_as_it_was() -> None:
    server = holding(
        setting("o/old", "pr-gnome", "advise", profile="strict"),
        setting("o/old", "repo-gnome", "gate", tenant="acme"),
    )

    moved = server.mover.execute(MOVE)

    assert moved.moved == ("acme/repo-gnome", "pr-gnome")
    assert moved.kept == ()
    assert server.what("o/new") == {
        ("default", "pr-gnome", "advise", "strict", "bugflow poll"),
        ("acme", "repo-gnome", "gate", "default", "bugflow poll"),
    }
    assert server.behaviours("o/old") == {"off"}
    assert server.events() == [GNOME_SET] * 4
    assert {entry.payload["set_by"] for entry in server.journal.entries} == {
        "bugflow poll"
    }


def test_the_new_names_own_setting_is_kept() -> None:
    server = holding(
        setting("o/old", "pr-gnome", "gate"),
        setting("o/new", "pr-gnome", "observe"),
    )

    moved = server.mover.execute(MOVE)

    assert (moved.moved, moved.kept) == ((), ("pr-gnome",))
    assert server.behaviours("o/new") == {"observe"}
    assert server.behaviours("o/old") == {"off"}


def test_a_gnome_already_off_is_not_moved() -> None:
    server = holding(setting("o/old", "pr-gnome", "off"))

    moved = server.mover.execute(MOVE)

    assert (moved.moved, moved.kept) == ((), ())
    assert server.what("o/new") == set()
    assert server.events() == []


def test_the_boundaries_go_with_the_gnomes_and_before_them() -> None:
    server = holding(
        setting("o/old", "pr-gnome", "advise"),
        boundaries=(
            boundary("o/old", "pull-request", "60s"),
            boundary("o/old", "weekly", "SUN 23:30"),
            boundary("o/new", "weekly", "MON 09:00"),
        ),
    )

    moved = server.mover.execute(MOVE)

    assert moved.boundaries == ("pull-request",)
    assert server.boundaries.boundary("github", "o/new", "pull-request") == (
        "60s"
    )
    # The new name's own boundary is kept, and the old name keeps its.
    assert server.boundaries.boundary("github", "o/new", "weekly") == (
        "MON 09:00"
    )
    assert server.boundaries.boundary("github", "o/old", "pull-request") == (
        "60s"
    )
    assert server.events()[0] == BOUNDARY_DECLARED
    (declared,) = (
        e for e in server.journal.entries if e.event_type == BOUNDARY_DECLARED
    )
    assert declared.repo == "o/new"
    assert declared.payload == {
        "layer": "pull-request",
        "boundary": "60s",
        "was": None,
        "declared_by": "bugflow poll",
        "from": "o/old",
    }


def test_the_withheld_share_goes_with_it_unless_the_new_name_has_one() -> None:
    server = holding(
        withheld=(Withholding(forge="github", repo="o/old", share=0.25),)
    )

    assert server.mover.execute(MOVE).withholding
    assert server.withholding.share_for("github", "o/new") == 0.25
    assert server.events() == [WITHHOLDING_DECLARED]

    kept = holding(
        withheld=(
            Withholding(forge="github", repo="o/old", share=0.25),
            Withholding(forge="github", repo="o/new", share=0.5),
        )
    )
    assert not kept.mover.execute(MOVE).withholding
    assert kept.withholding.share_for("github", "o/new") == 0.5
