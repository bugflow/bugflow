"""What a host is promised about a composition under ``deployments/``,
and what a deployer is promised about the settings templates.

No container is run. Each test reads the files a deployer reads: the
compositions, the ``.env`` beside each, the templates under
``deployments/env/``, the ``Dockerfile``, the proxy's model list and
``docs/deploying.md``. The templates are rendered by the script a local
run renders them with.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import Environment, meta

from bugflow.apps.command.webhooks import REQUIRED as WEBHOOKS_REQUIRED
from bugflow.apps.worker.litellm_judge import MODEL_CLASS_DEFAULTS

ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENTS = ROOT / "deployments"
TEMPLATES = DEPLOYMENTS / "env"
RENDER = DEPLOYMENTS / "scripts" / "render_env.py"
GUIDE = ROOT / "docs" / "deploying.md"

#: The compositions, by the name of the environment each is for.
ENVIRONMENTS = sorted(
    path.parent.name for path in DEPLOYMENTS.glob("*/docker-compose.yml")
)

#: The services a host's proxy routes to. Each joins the edge network.
FRONTED = {"ingress", "api", "mcp", "temporal-ui"}

#: The services told one address in the composition, with no file of
#: settings.
WITHOUT_SETTINGS = {"temporal-ui"}

#: The services that read another service's settings.
SHARED_SETTINGS = {"webhooks": "worker"}

#: What a hosting platform supplies to the templates. Every other
#: variable is the deployer's, and is named for the solution.
PLATFORM_FACTS = {
    "project_build_sha",
    "project_oidc_issuer",
    "project_oidc_audience",
    "project_oidc_clients",
}

#: The files a deployer copies, builds or mounts, which name no
#: organisation.
SHIPPED = sorted(
    path
    for path in [
        ROOT / "Dockerfile",
        ROOT / ".dockerignore",
        ROOT / ".env.example",
        *(ROOT / "litellm").rglob("*"),
        *DEPLOYMENTS.rglob("*"),
    ]
    if path.is_file()
    and "__pycache__" not in path.parts
    and DEPLOYMENTS / "tests" not in path.parents
)

#: A host name under a top-level domain an organisation registers.
HOST_NAME = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|ai|app|cloud|co)\b"
)

#: The host names that may appear: the registries images are pulled
#: from.
REGISTRIES = {"ghcr.io"}

#: Words a vendor's model is named with.
MODEL_WORDS = re.compile(
    r"claude|sonnet|haiku|opus|gemini|gpt|llama|mistral", re.IGNORECASE
)


def composition(environment: str) -> dict[str, Any]:
    text = (DEPLOYMENTS / environment / "docker-compose.yml").read_text()
    loaded: dict[str, Any] = yaml.safe_load(text)
    return loaded


def identity(environment: str) -> dict[str, str]:
    lines = (DEPLOYMENTS / environment / ".env").read_text().splitlines()
    return dict(
        line.split("=", 1)
        for line in lines
        if "=" in line and not line.startswith("#")
    )


def settings_files(service: dict[str, Any]) -> list[str]:
    files = service.get("env_file", [])
    return [files] if isinstance(files, str) else list(files)


def template_names() -> set[str]:
    return {
        path.name.removesuffix(".env.j2")
        for path in TEMPLATES.glob("*.env.j2")
    }


def template_variables() -> set[str]:
    """Every variable a template names."""
    found: set[str] = set()
    for path in TEMPLATES.glob("*.env.j2"):
        found |= meta.find_undeclared_variables(
            Environment().parse(path.read_text())
        )
    return found


def rendered(values: str, directory: Path) -> subprocess.CompletedProcess[str]:
    """Run the rendering script over ``values`` into ``directory``."""
    source = directory / "values"
    source.write_text(values)
    return subprocess.run(
        [sys.executable, str(RENDER), str(source), str(directory / "env")],
        capture_output=True,
        text=True,
        check=False,
    )


def test_there_is_an_example_composition() -> None:
    assert "example" in ENVIRONMENTS


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_composition_is_named_for_the_solution(environment: str) -> None:
    """A host selects a solution's containers by the compose project's
    name, so the name is the solution's and is written once, in the
    ``.env`` beside the composition."""
    assert composition(environment)["name"] == "${SOLUTION}"


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_identity_is_three_names(environment: str) -> None:
    declared = identity(environment)
    assert set(declared) == {"CLIENT", "SOLUTION", "ENVIRONMENT"}
    assert declared["ENVIRONMENT"] == environment
    assert all(declared.values())


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_solution_is_the_only_value_interpolated(environment: str) -> None:
    """Compose fills ``${NAME}`` from the ``.env`` beside the file,
    which is committed. A secret written that way would be a secret in
    the repository, so every other setting is in a service's own file."""
    text = (DEPLOYMENTS / environment / "docker-compose.yml").read_text()
    without_escapes = text.replace("$$", "")
    assert set(re.findall(r"\$\{?(\w+)", without_escapes)) == {"SOLUTION"}


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_no_service_publishes_a_port(environment: str) -> None:
    """A host port is a number two solutions on one host could both
    want, and it is reachable by everything on the host. The way in is
    the host's proxy, over the edge network."""
    for name, service in composition(environment)["services"].items():
        assert "ports" not in service, name
        assert service.get("network_mode") != "host", name


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_only_network_shared_with_the_host_is_the_edge(
    environment: str,
) -> None:
    networks = composition(environment)["networks"]
    assert networks == {"edge": {"external": True, "name": "${SOLUTION}-edge"}}


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_each_fronted_service_joins_the_edge_under_an_alias(
    environment: str,
) -> None:
    """The alias begins with the solution's name, because a bare
    ``ingress`` is a name two solutions on one host could both want."""
    services = composition(environment)["services"]
    joined = {
        name: service["networks"]
        for name, service in services.items()
        if "networks" in service
    }
    assert set(joined) == FRONTED
    for name, networks in joined.items():
        assert set(networks) == {"default", "edge"}, name
        assert networks["edge"]["aliases"] == [f"${{SOLUTION}}-{name}"], name


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_every_service_reads_a_file_of_its_own_settings(
    environment: str,
) -> None:
    services = composition(environment)["services"]
    for name, service in services.items():
        if name in WITHOUT_SETTINGS:
            assert settings_files(service) == [], name
            continue
        reads = SHARED_SETTINGS.get(name, name)
        assert settings_files(service) == [f"../../env/{reads}.env"], name


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_every_settings_file_has_a_template_and_every_template_a_reader(
    environment: str,
) -> None:
    """A file with no template is a service started with no settings. A
    template with no reader is a file of secrets nothing needs."""
    read = {
        Path(path).name.removesuffix(".env")
        for service in composition(environment)["services"].values()
        for path in settings_files(service)
    }
    assert read == template_names()


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_every_image_is_pinned(environment: str) -> None:
    for name, service in composition(environment)["services"].items():
        if "image" not in service:
            continue
        _, _, tag = service["image"].rpartition(":")
        assert tag and tag != "latest" and "/" not in tag, name


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_everything_built_or_mounted_is_in_the_repository(
    environment: str,
) -> None:
    directory = DEPLOYMENTS / environment
    for name, service in composition(environment)["services"].items():
        if "build" in service:
            context = (directory / service["build"]).resolve()
            assert context == ROOT, name
            assert (context / "Dockerfile").is_file(), name
        for volume in service.get("volumes", []):
            source = volume.split(":", 1)[0]
            if source.startswith("."):
                assert (directory / source).is_file(), (name, source)


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_programs_start_after_the_database_is_brought_up_to_date(
    environment: str,
) -> None:
    services = composition(environment)["services"]
    assert services["migrate"]["command"] == ["bugflow", "migrate"]
    for name in ("worker", "ingress", "api", "webhooks"):
        assert services[name]["depends_on"]["migrate"] == {
            "condition": "service_completed_successfully"
        }, name


def test_every_template_variable_is_named_for_the_solution() -> None:
    """A deployer's variable begins ``bugflow_`` and a secret
    ``vault_bugflow_``. The rest are the four a hosting platform
    supplies."""
    for variable in template_variables() - PLATFORM_FACTS:
        assert variable.startswith(("bugflow_", "vault_bugflow_")), variable


def test_every_template_variable_is_in_the_guide() -> None:
    documented = set(re.findall(r"`([a-z][a-z0-9_]+)`", GUIDE.read_text()))
    assert template_variables() - documented == set()


def test_the_guide_describes_no_variable_the_templates_do_not_name() -> None:
    documented = set(
        re.findall(
            r"`((?:vault_bugflow|bugflow|project)_[a-z0-9_]+)`",
            GUIDE.read_text(),
        )
    )
    assert documented - template_variables() == set()


def test_no_secret_has_a_default_value() -> None:
    """A default is how a server runs with a password everyone can
    read. A secret that is optional defaults to nothing."""
    for path in TEMPLATES.glob("*.env.j2"):
        defaults = re.findall(
            r"vault_bugflow_\w+ \| default\(([^)]*)\)", path.read_text()
        )
        assert set(defaults) <= {"''"}, path.name


def test_the_templates_render_before_a_platform_supplies_anything(
    tmp_path: Path,
) -> None:
    """The first render on a host comes before its identity provider
    has registered a client, and a local run has no platform at all."""
    done = rendered((ROOT / ".env.example").read_text(), tmp_path)

    assert done.returncode == 0, done.stderr
    written = {path.name for path in (tmp_path / "env").iterdir()}
    assert written == {f"{name}.env" for name in template_names()}
    api = (tmp_path / "env" / "api.env").read_text()
    assert "API_CLIENTS" not in api
    assert "BUILD_SHA" not in api
    assert "EVALUATION_ADMIN_ROLE" not in api
    assert "EVALUATION_IDENTITIES" not in api


def test_the_templates_render_what_a_platform_supplies(
    tmp_path: Path,
) -> None:
    values = (ROOT / ".env.example").read_text() + (
        "project_build_sha=" + "a" * 40 + "\n"
        "project_oidc_issuer=https://idp.example\n"
        "project_oidc_audience=project-1\n"
        "project_oidc_clients.policies-pipeline.client_id=pipeline-1\n"
    )

    done = rendered(values, tmp_path)

    assert done.returncode == 0, done.stderr
    api = (tmp_path / "env" / "api.env").read_text().splitlines()
    assert "API_ISSUER=https://idp.example" in api
    assert "API_AUDIENCE=project-1" in api
    assert "API_CLIENTS=pipeline-1" in api
    for name in ("api", "ingress", "worker", "migrate"):
        lines = (tmp_path / "env" / f"{name}.env").read_text().splitlines()
        assert "BUILD_SHA=" + "a" * 40 in lines, name


def test_a_missing_value_is_named_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    values = "".join(
        line + "\n"
        for line in (ROOT / ".env.example").read_text().splitlines()
        if not line.startswith("vault_bugflow_webhook_secret=")
    )

    done = rendered(values, tmp_path)

    assert done.returncode == 1
    assert "vault_bugflow_webhook_secret" in done.stderr
    assert not (tmp_path / "env").exists()


def test_the_managed_agent_is_set_only_where_a_runner_is_named(
    tmp_path: Path,
) -> None:
    without = rendered((ROOT / ".env.example").read_text(), tmp_path)
    assert without.returncode == 0, without.stderr
    assert "REVIEW_" not in (tmp_path / "env" / "worker.env").read_text()

    values = (ROOT / ".env.example").read_text() + (
        "bugflow_review_runner=managed\n"
        "bugflow_review_agent_model=example-model\n"
        "vault_bugflow_review_runner_api_key=key\n"
        "vault_bugflow_review_repository_token=token\n"
    )
    named = rendered(values, tmp_path)
    assert named.returncode == 0, named.stderr
    worker = (tmp_path / "env" / "worker.env").read_text().splitlines()
    assert "REVIEW_RUNNER=managed" in worker
    assert "REVIEW_AGENT_MODEL=example-model" in worker


def test_the_worker_is_given_no_doctrine_path() -> None:
    """Doctrine reaches a server in a policy deployment, not on a path
    in the image."""
    assert "DOCTRINE" not in (TEMPLATES / "worker.env.j2").read_text()


def test_the_worker_s_settings_run_the_webhooks_command() -> None:
    """``bugflow webhooks`` is run with the worker's settings, so every
    variable it does not run without is in the worker's template."""
    template = (TEMPLATES / "worker.env.j2").read_text()
    supplied = set(re.findall(r"^([A-Z_]+)=", template, re.MULTILINE))
    assert set(WEBHOOKS_REQUIRED) <= supplied


def test_the_proxy_publishes_the_roles_the_classes_ask_for() -> None:
    """Each role reads its model and its key from the environment, and
    the proxy's template supplies each of those names."""
    config = yaml.safe_load((ROOT / "litellm" / "config.yaml").read_text())
    roles = {entry["model_name"]: entry for entry in config["model_list"]}
    assert set(roles) == set(MODEL_CLASS_DEFAULTS.values())

    template = (TEMPLATES / "litellm.env.j2").read_text()
    supplied = set(re.findall(r"^([A-Z_]+)=", template, re.MULTILINE))
    read = {config["general_settings"]["master_key"]}
    for name, entry in roles.items():
        assert set(entry["litellm_params"]) == {"model", "api_key"}, name
        read |= set(entry["litellm_params"].values())
    assert all(value.startswith("os.environ/") for value in read)
    assert {value.removeprefix("os.environ/") for value in read} == supplied


def test_git_is_installed_before_a_git_dependency_is_fetched() -> None:
    """uv fetches a git source by running git, and the slim image has
    none, so the failure would be a build error on a host."""
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"][
        "uv"
    ]["sources"]
    assert any("git" in source for source in sources.values())
    dockerfile = (ROOT / "Dockerfile").read_text()
    first_sync = dockerfile.index("uv sync --locked --no-dev")
    assert "install -y --no-install-recommends git" in dockerfile[:first_sync]


def test_the_image_runs_the_worker_unless_told_otherwise() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text().splitlines()
    assert "EXPOSE 8000" in dockerfile
    assert 'CMD ["bugflow", "worker"]' in dockerfile


@pytest.mark.parametrize(
    "path", SHIPPED, ids=lambda path: str(path.relative_to(ROOT))
)
def test_what_a_deployer_copies_names_no_organisation(path: Path) -> None:
    """No host name but an image registry's, and no vendor's model. The
    one setting the worker reads that is named for a vendor is the key
    its managed agent's sessions are started with."""
    text = path.read_text().replace("REVIEW_ANTHROPIC_API_KEY", "")
    assert set(HOST_NAME.findall(text)) <= REGISTRIES
    assert MODEL_WORDS.findall(text) == []


def test_nothing_a_deployer_needs_is_ignored_by_git() -> None:
    """A deployer deploys what a clone holds. A rule that keeps rendered
    secrets out of the repository must not also keep out a
    composition's ``.env`` or a template."""
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    environ = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GIT_")
    }
    ignored = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=ROOT,
        env=environ,
        input="\n".join(str(path.relative_to(ROOT)) for path in SHIPPED),
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert ignored == []


def test_evaluation_access_and_interactive_clients_render(
    tmp_path: Path,
) -> None:
    identities = [
        {
            "issuer": "https://idp.example",
            "subject": "stable-user-id",
            "emails": ["commits@example.test", "old-commits@example.test"],
        }
    ]
    values = (ROOT / ".env.example").read_text() + (
        "project_oidc_clients.policies-pipeline.client_id=pipeline-1\n"
        "bugflow_api_clients=pipeline-1,interactive-1\n"
        "bugflow_evaluation_admin_role=evaluation-admin\n"
        "bugflow_evaluation_identities=" + json.dumps(identities) + "\n"
    )
    done = rendered(values, tmp_path)
    assert done.returncode == 0, done.stderr
    lines = (tmp_path / "env" / "api.env").read_text().splitlines()
    assert "API_CLIENTS=pipeline-1,interactive-1" in lines
    assert "API_CLIENTS=pipeline-1" not in lines
    assert "EVALUATION_ADMIN_ROLE=evaluation-admin" in lines
    assert "EVALUATION_IDENTITIES='" + json.dumps(identities) + "'" in lines


def test_compose_preserves_identity_json_as_literal_data(
    tmp_path: Path,
) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is not installed")
    available = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    )
    if available.returncode:
        pytest.skip("Docker Compose is not installed")
    identities = [
        {
            "issuer": "https://idp.example",
            "subject": "login@example.test",
            "emails": [
                "o'connor@example.test",
                "${COMMIT_ALIAS}@example.test",
                'quote"and\\slash@example.test',
            ],
        }
    ]
    values = (ROOT / ".env.example").read_text() + (
        "bugflow_evaluation_identities=" + json.dumps(identities) + "\n"
    )
    done = rendered(values, tmp_path)
    assert done.returncode == 0, done.stderr
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        yaml.safe_dump(
            {
                "name": "evaluation-settings-test",
                "services": {
                    "api": {"image": "unused", "env_file": "env/api.env"}
                },
            }
        )
    )
    checked = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ, COMMIT_ALIAS="must-not-be-substituted"),
    )
    assert checked.returncode == 0, checked.stderr
    environment = json.loads(checked.stdout)["services"]["api"]["environment"]
    # Compose escapes literal dollars when serializing reusable configuration.
    encoded = environment["EVALUATION_IDENTITIES"].replace("$$", "$")
    assert json.loads(encoded) == identities


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_mcp_is_opt_in_and_depends_only_on_the_api(environment: str) -> None:
    service = composition(environment)["services"]["mcp"]
    assert service["profiles"] == ["mcp"]
    assert service["depends_on"] == {"api": {"condition": "service_healthy"}}
    assert service["command"] == [
        "uvicorn",
        "bugflow.apps.mcp.server:mcp_from_environment",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    assert service["restart"] == "unless-stopped"
    assert "DATABASE_URL" not in (TEMPLATES / "mcp.env.j2").read_text()


def test_unconfigured_mcp_renders_without_enabling_or_sharing_credentials(
    tmp_path: Path,
) -> None:
    done = rendered((ROOT / ".env.example").read_text(), tmp_path)
    assert done.returncode == 0, done.stderr
    lines = (tmp_path / "env" / "mcp.env").read_text().splitlines()
    settings = dict(
        line.split("=", 1)
        for line in lines
        if "=" in line and not line.startswith("#")
    )
    assert settings.pop("MCP_API_URL") == "http://api:8000"
    assert settings.pop("MCP_EXCHANGE_CLIENT_SECRET") == "''"
    assert all(value == "" for value in settings.values())
    assert all(name.startswith("MCP_") for name in settings)


def test_mcp_renders_its_own_identity_and_api_settings(tmp_path: Path) -> None:
    from bugflow.apps.mcp.server import REQUIRED as MCP_REQUIRED

    supplied = {
        "bugflow_mcp_issuer": "https://identity.example",
        "bugflow_mcp_audience": "mcp-project",
        "bugflow_mcp_clients": "work-client,other-client",
        "bugflow_mcp_roles_claim": "project-roles",
        "bugflow_mcp_exchange_client_id": "mcp-exchange",
        "vault_bugflow_mcp_exchange_client_secret": "exchange-secret",
        "bugflow_mcp_api_audience": "api-project",
        "bugflow_mcp_api_url": "https://api.example",
        "bugflow_mcp_public_url": "https://mcp.example",
    }
    values = (ROOT / ".env.example").read_text() + "\n".join(
        f"{name}={value}" for name, value in supplied.items()
    )
    done = rendered(values, tmp_path)
    assert done.returncode == 0, done.stderr
    lines = (tmp_path / "env" / "mcp.env").read_text().splitlines()
    settings = dict(
        line.split("=", 1)
        for line in lines
        if "=" in line and not line.startswith("#")
    )
    assert set(settings) == set(MCP_REQUIRED)
    assert settings == {
        "MCP_ISSUER": "https://identity.example",
        "MCP_AUDIENCE": "mcp-project",
        "MCP_CLIENTS": "work-client,other-client",
        "MCP_ROLES_CLAIM": "project-roles",
        "MCP_EXCHANGE_CLIENT_ID": "mcp-exchange",
        "MCP_EXCHANGE_CLIENT_SECRET": "'exchange-secret'",
        "MCP_API_AUDIENCE": "api-project",
        "MCP_API_URL": "https://api.example",
        "MCP_PUBLIC_URL": "https://mcp.example",
    }


def test_compose_preserves_the_exchange_secret(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is not installed")
    available = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    )
    if available.returncode:
        pytest.skip("Docker Compose is not installed")
    secret = r"${EXCHANGE_SECRET}'back\slash"
    values = (ROOT / ".env.example").read_text() + (
        f"vault_bugflow_mcp_exchange_client_secret={secret}\n"
    )
    done = rendered(values, tmp_path)
    assert done.returncode == 0, done.stderr
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        yaml.safe_dump(
            {
                "name": "mcp-settings-test",
                "services": {
                    "mcp": {"image": "unused", "env_file": "env/mcp.env"}
                },
            }
        )
    )
    checked = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ, EXCHANGE_SECRET="must-not-be-substituted"),
    )
    assert checked.returncode == 0, checked.stderr
    settings = json.loads(checked.stdout)["services"]["mcp"]["environment"]
    assert settings["MCP_EXCHANGE_CLIENT_SECRET"].replace("$$", "$") == secret
