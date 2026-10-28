"""Tests of the settings routes and the page (ADR 008), over in-memory
stores."""

from bugflow.apps.api.tests.doubles import (
    ADMINISTRATOR,
    DEPLOYER,
    READER,
    Server,
    bearer,
)
from bugflow.forge.domain.models.forge_repository import ListedRepository
from bugflow.method.tests.policy_files import READ
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.domain.models.layer_boundary import LayerBoundary

REPOSITORY = "example-org/pull-request-policies"
WIDGETS = "/api/settings/github/example-org/widgets/prose"


def deployed(server: Server, files: dict[str, str] = READ) -> None:
    answered = server.client.post(
        "/api/policy-deployments",
        json={
            "repository": REPOSITORY,
            "commit": "c1",
            "files": [{"path": p, "text": t} for p, t in files.items()],
        },
        headers=bearer(DEPLOYER),
    )
    assert answered.status_code == 200


def bounded(server: Server) -> None:
    server.boundaries.declare(
        LayerBoundary(
            forge="github",
            repo="example-org/widgets",
            layer="pull-request",
            boundary="60s",
        )
    )


def test_the_settings_need_the_role() -> None:
    server = Server()
    assert server.client.get("/api/settings").status_code == 401
    assert (
        server.client.get("/api/settings", headers=bearer(READER)).status_code
        == 403
    )


def test_every_known_repository_is_listed_with_each_gnomes_profiles() -> None:
    server = Server()
    deployed(server)
    server.repositories.keep(
        ListedRepository(
            forge="github",
            name="example-org/widgets",
            forge_key="1",
            private=True,
        )
    )
    answered = server.client.get(
        "/api/settings", headers=bearer(ADMINISTRATOR)
    )
    assert answered.status_code == 200
    held = answered.json()
    assert held["profiles"] == {"prose": ["default"]}
    assert held["repositories"] == [
        {
            "forge": "github",
            "name": "example-org/widgets",
            "archived": False,
            "private": True,
            "gnomes": {},
        }
    ]


def test_each_gnome_says_what_it_reads_runs_and_judges_by() -> None:
    """So that the page can say what a column is, without the person
    opening the binding, and where the profiles are defined."""
    server = Server()
    deployed(server)
    held = server.client.get(
        "/api/settings", headers=bearer(ADMINISTRATOR)
    ).json()
    (prose,) = held["gnomes"].values()
    assert prose["summary"]
    assert prose["runs"] == ["evaluate-pull-request, each pull request"]
    assert set(prose["profiles"]) == {"default"}
    assert set(prose["policies"]) <= set(prose["profiles"]["default"])
    assert held["deployment"] == {"repository": REPOSITORY, "commit": "c1"}


def test_a_gnome_is_set_and_recorded_as_set_by_the_caller() -> None:
    server = Server()
    deployed(server)
    bounded(server)

    answered = server.client.put(
        WIDGETS, json={"behaviour": "advise"}, headers=bearer(ADMINISTRATOR)
    )

    assert answered.status_code == 200
    prose = answered.json()["gnomes"]["prose"]
    assert (prose["behaviour"], prose["profile"]) == ("advise", "default")
    assert prose["set_by"] == "machine-user-1"
    assert server.journal.entries[-1].event_type == "gnome.set"


def test_a_repository_a_worker_could_not_watch_is_refused() -> None:
    """With no boundary on a layer and no default, a worker watching the
    repository would not start, so the setting is refused before it is
    made."""
    server = Server()
    deployed(server)

    answered = server.client.put(
        WIDGETS, json={"behaviour": "observe"}, headers=bearer(ADMINISTRATOR)
    )

    assert answered.status_code == 409
    assert "has no boundary on" in answered.json()["detail"]
    assert server.settings.settings() == ()


def test_a_layers_default_boundary_lets_the_gnome_be_set() -> None:
    server = Server()
    deployed(
        server,
        READ
        | {
            "pace-layers.toml": READ["pace-layers.toml"].replace(
                'cadence = "event"\n',
                'cadence = "event"\ndefault_boundary = "60s"\n',
            )
        },
    )
    answered = server.client.put(
        WIDGETS, json={"behaviour": "observe"}, headers=bearer(ADMINISTRATOR)
    )
    assert answered.status_code == 200


def test_a_gnome_or_profile_not_in_force_is_refused() -> None:
    server = Server()
    deployed(server)
    bounded(server)
    for path, body in (
        (WIDGETS.replace("prose", "other"), {"behaviour": "observe"}),
        (WIDGETS, {"behaviour": "observe", "profile": "strict"}),
    ):
        answered = server.client.put(
            path, json=body, headers=bearer(ADMINISTRATOR)
        )
        assert answered.status_code == 422


def test_a_gnome_may_be_switched_off_with_nothing_in_force() -> None:
    server = Server()
    answered = server.client.put(
        WIDGETS, json={"behaviour": "off"}, headers=bearer(ADMINISTRATOR)
    )
    assert answered.status_code == 200
    assert answered.json()["gnomes"]["prose"]["behaviour"] == "off"


def test_the_page_and_where_it_signs_in_need_no_token() -> None:
    server = Server()
    page = server.client.get("/settings")
    assert page.status_code == 200
    assert "<title>Gnome settings</title>" in page.text
    assert server.client.get("/settings/config").json() == {
        "issuer": "https://issuer.example",
        "client_id": "settings-page",
        "scope": "openid profile",
    }


def test_a_repository_this_server_does_not_read_is_refused() -> None:
    server = Server()
    for path in (
        "/api/settings/gitlab/example-org/widgets/prose",
        "/api/settings/github/example-org/wid%20gets/prose",
    ):
        answered = server.client.put(
            path, json={"behaviour": "off"}, headers=bearer(ADMINISTRATOR)
        )
        assert answered.status_code == 422
    assert server.settings.settings() == ()


def test_a_gnome_set_to_a_profile_that_is_gone_takes_the_default() -> None:
    """The page offers no profile where a gnome has one, so a gnome kept
    at a profile no longer deployed is set to the default."""
    server = Server()
    deployed(server)
    bounded(server)
    server.settings.save(
        GnomeSetting(
            forge="github",
            repo="example-org/widgets",
            gnome="prose",
            behaviour="off",
            profile="strict",
        )
    )

    answered = server.client.put(
        WIDGETS, json={"behaviour": "observe"}, headers=bearer(ADMINISTRATOR)
    )

    assert answered.status_code == 200
    assert answered.json()["gnomes"]["prose"]["profile"] == "default"
