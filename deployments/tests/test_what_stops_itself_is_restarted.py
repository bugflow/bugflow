"""A program that stops itself is one its container runtime starts
again.

The worker and the ingress read the policy deployment in force when
they start, and stop when a different one is put in force, so that the
next start reads it. With no restart policy the first deployment a
server is sent would stop both, and they would stay stopped.

Two things are held. The programs that stop themselves are the ones
named here, so another cannot be added without its service being
added too. And each of their services, and the API's, has a restart
policy that starts a container again after it exits with status 0.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
APPS = ROOT / "src" / "bugflow" / "apps"
DEPLOYMENTS = ROOT / "deployments"
ENVIRONMENTS = sorted(
    path.parent.name for path in DEPLOYMENTS.glob("*/docker-compose.yml")
)

#: The module that stops its program, and the service that runs it.
STOPS_ITSELF = {
    "ingress/ingress.py": "ingress",
    "worker/review.py": "worker",
}

#: The services that must be started again. The API stops only when it
#: fails, and is started again so that it comes up once its settings
#: name an identity provider.
RESTARTED = sorted({*STOPS_ITSELF.values(), "api"})

#: The policies that start a container again after it exits with status
#: 0, which is how these programs stop themselves. ``on-failure`` does
#: not.
RESTARTS = {"unless-stopped", "always"}


def services(environment: str) -> dict[str, Any]:
    text = (DEPLOYMENTS / environment / "docker-compose.yml").read_text()
    loaded: dict[str, Any] = yaml.safe_load(text)["services"]
    return loaded


def test_the_programs_that_stop_themselves_are_the_ones_named_here() -> None:
    calling = {
        str(path.relative_to(APPS))
        for path in APPS.rglob("*.py")
        if "tests" not in path.parts
        and "stop_on_new_deployment(" in path.read_text()
    }
    assert calling == set(STOPS_ITSELF)


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("service", RESTARTED)
def test_each_is_started_again_when_it_stops(
    environment: str, service: str
) -> None:
    assert services(environment)[service].get("restart") in RESTARTS


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("service", ["migrate", "webhooks"])
def test_what_runs_once_is_not_started_again(
    environment: str, service: str
) -> None:
    assert services(environment)[service].get("restart") == "no"
