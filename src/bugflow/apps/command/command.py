"""The ``bugflow`` command.

It has two subcommands::

    bugflow deploy-policies DIRECTORY --repository OWNER/NAME
        --commit SHA --api URL [--check]
    bugflow migrate [--check]

``deploy-policies`` is what a policy repository's pipeline runs. It
reads the reviewers, policies and doctrine under DIRECTORY and sends
them to the server at URL, which puts them in force. With ``--check``
the server parses them and stores nothing, which is what a pipeline
runs on a pull request.

The pipeline signs in to the identity provider as a client with no
person behind it. Four settings in its environment say how:

- ``POLICY_DEPLOY_ISSUER``: the identity provider's address.
- ``POLICY_DEPLOY_CLIENT_ID`` and ``POLICY_DEPLOY_CLIENT_SECRET``: the
  client's id and secret.
- ``POLICY_DEPLOY_AUDIENCE``: the id of the server's project at the
  provider.

Exit status: 0 if the server accepted the call. 1 if the files are not a
deployment or the server refused them. 2 if the call could not be made
or was not allowed.

``migrate`` brings the database named by ``DATABASE_URL`` up to date by
running the scripts it has not run. With ``--check`` it runs nothing
and prints the scripts that would be run, one a line.

Exit status: 0 if the database is up to date, or was brought up to
date. 1 if ``--check`` found scripts to run. 2 if ``DATABASE_URL`` is
not set.
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx2

from bugflow.method.domain.errors import (
    PoliciesRefusedError,
    PolicyDeploymentError,
    PolicyServerError,
)
from bugflow.method.dtos.send_policies import (
    SendPoliciesRequest,
    SendPoliciesResponse,
)
from bugflow.method.infrastructure.http_policy_server import (
    HttpPolicyServer,
    PipelineSignIn,
)
from bugflow.method.infrastructure.policy_directory import PolicyDirectory
from bugflow.method.usecases.send_policies import SendPoliciesUseCase
from bugflow.shared.infrastructure import migrations

#: The settings a pipeline signs in with.
SETTINGS = (
    "POLICY_DEPLOY_ISSUER",
    "POLICY_DEPLOY_CLIENT_ID",
    "POLICY_DEPLOY_CLIENT_SECRET",
    "POLICY_DEPLOY_AUDIENCE",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bugflow")
    commands = parser.add_subparsers(dest="command", required=True)
    deploy_policies = commands.add_parser(
        "deploy-policies",
        help="send the reviewers, policies and doctrine a directory "
        "holds to a server, which puts them in force",
    )
    deploy_policies.add_argument(
        "directory",
        type=Path,
        help="the directory holding one directory per reviewer",
    )
    deploy_policies.add_argument(
        "--repository",
        required=True,
        help="the policy repository the files are from, as owner/name",
    )
    deploy_policies.add_argument(
        "--commit",
        required=True,
        help="the commit of that repository the files are from",
    )
    deploy_policies.add_argument(
        "--api",
        required=True,
        help="the address of the server. The command signs in with "
        + ", ".join(SETTINGS),
    )
    deploy_policies.add_argument(
        "--check",
        action="store_true",
        help="have the server parse the files and say what is wrong "
        "with them, storing nothing",
    )
    migrate = commands.add_parser(
        "migrate",
        help="bring the database named by DATABASE_URL up to date by "
        "running the scripts it has not run",
    )
    migrate.add_argument(
        "--check",
        action="store_true",
        help="run nothing; print the scripts that would be run and "
        "exit 1 if there are any",
    )
    return parser


def _said(answered: SendPoliciesResponse) -> str:
    """The line printed when the server accepted the call."""
    in_force = answered.in_force
    now = (
        f"{in_force.repository} at {in_force.commit}, "
        f"content {in_force.content_hash[:12]}"
        if in_force
        else "nothing"
    )
    sent = f"{answered.files} files, content {answered.content_hash[:12]}"
    if answered.outcome == "deployed":
        return f"deployed {sent}; in force: {now}"
    if answered.outcome == "already_in_force":
        return f"already in force, nothing changed: {now}"
    return f"checked {sent}, nothing stored; in force: {now}"


def run(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] = os.environ,
    transport: httpx2.BaseTransport | None = None,
) -> int:
    """Run the command and return its exit status.

    ``transport`` replaces the network, for tests.
    """
    args = _parser().parse_args(argv)
    if args.command == "migrate":
        return _migrate(args.check, environ)
    if not args.directory.is_dir():
        print(f"error: {args.directory} is not a directory", file=sys.stderr)
        return 2
    missing = [name for name in SETTINGS if not environ.get(name)]
    if missing:
        print(
            f"error: {', '.join(missing)} not set; they say how this "
            "pipeline signs in to the identity provider",
            file=sys.stderr,
        )
        return 2
    send = SendPoliciesUseCase(
        PolicyDirectory(args.directory),
        HttpPolicyServer(
            args.api,
            PipelineSignIn(
                issuer=environ["POLICY_DEPLOY_ISSUER"],
                client_id=environ["POLICY_DEPLOY_CLIENT_ID"],
                client_secret=environ["POLICY_DEPLOY_CLIENT_SECRET"],
                audience=environ["POLICY_DEPLOY_AUDIENCE"],
            ),
            transport,
        ),
    )
    try:
        answered = send.execute(
            SendPoliciesRequest(
                repository=args.repository,
                commit=args.commit,
                check_only=args.check,
            )
        )
    except PolicyDeploymentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except PoliciesRefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except PolicyServerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_said(answered))
    return 0


def _migrate(check: bool, environ: Mapping[str, str]) -> int:
    database_url = environ.get("DATABASE_URL")
    if not database_url:
        print(
            "error: DATABASE_URL not set; it names the database to bring "
            "up to date",
            file=sys.stderr,
        )
        return 2
    if check:
        not_run = migrations.pending(database_url)
        for name in not_run:
            print(name)
        return 1 if not_run else 0
    migrations.upgrade(database_url)
    return 0


def main() -> None:
    sys.exit(run())
