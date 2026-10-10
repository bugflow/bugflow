"""The ``bugflow`` command.

It has five subcommands::

    bugflow deploy-policies DIRECTORY --repository OWNER/NAME
        --commit SHA --api URL [--check]
    bugflow install-policies DIRECTORY --repository OWNER/NAME
        --commit SHA [--check]
    bugflow migrate [--check]
    bugflow poll [--once]
    bugflow webhooks

``deploy-policies`` is what a policy repository's pipeline runs. It
reads the reviewers, policies and doctrine under DIRECTORY and sends
them to the server at URL, which puts them in force. With ``--check``
the server parses them and stores nothing, which is what a pipeline
runs on a pull request.

``install-policies`` is the same act on the host, for a server no
pipeline reaches yet and for the first deployment of one. It stores
what DIRECTORY holds in the database named by ``DATABASE_URL`` and
puts it in force, writing the declarations the deployment carries.
``BUILD_SHA`` and ``POLICY_CHECKS`` are read as the API reads them.
With ``--check`` it parses the files and stores nothing.

Exit status: 0 if the database holds the deployment afterwards, or
with ``--check`` if the files parse. 1 if the files are not a
deployment, do not parse, or the commit is held with other content. 2
if ``DATABASE_URL`` is not set or DIRECTORY is not a directory.

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

``poll`` stands in for a forge's webhook where the forge cannot reach
the ingress: it lists the watched repositories' pull requests and posts
each change to the ingress as a signed delivery, every
``POLL_INTERVAL_SECONDS`` until stopped, or with ``--once`` one time.
Its settings are described in ``bugflow.apps.poller.poller``.

Exit status: 0 when stopped, or after a single poll with no failures.
1 if a single poll had failures. 2 if a setting is missing or wrong.

``webhooks`` registers this server's webhook on each repository
``WATCHED_REPOSITORIES`` names, pointing at ``INGRESS_URL`` and signing
with ``WEBHOOK_SECRET``, and changes nothing where the forge already
agrees. It records what it did in the database ``DATABASE_URL`` names.

Exit status: 0 if every repository agrees with the declaration. 1 if any
could not be reconciled. 2 if a setting is missing or wrong.
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx2

from bugflow.apps.command.webhooks import HookSettings, run_webhooks
from bugflow.apps.poller.poller import (
    PollerSettings,
    poller_from_settings,
    run_poller,
)
from bugflow.apps.shared.deploying import (
    checks_from,
    deploying_over,
    run_install_policies,
)
from bugflow.apps.shared.journals import build_sha, stamped_journal
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.forge.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
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
from bugflow.shared.infrastructure.system_clock import SystemClock

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
    install_policies = commands.add_parser(
        "install-policies",
        help="store the reviewers, policies and doctrine a directory "
        "holds as a deployment in the database DATABASE_URL names, and "
        "put it in force",
    )
    install_policies.add_argument(
        "directory",
        type=Path,
        help="the directory holding one directory per reviewer",
    )
    install_policies.add_argument(
        "--repository",
        required=True,
        help="the policy repository the files are from, as owner/name",
    )
    install_policies.add_argument(
        "--commit",
        required=True,
        help="the commit of that repository the files are from",
    )
    install_policies.add_argument(
        "--check",
        action="store_true",
        help="parse the files and say what is wrong with them, storing "
        "nothing",
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
    poll = commands.add_parser(
        "poll",
        help="list the pull requests of the repositories POLL_REPOSITORIES "
        "names and post each change to the ingress at INGRESS_URL, in "
        "place of a webhook the forge cannot deliver",
    )
    poll.add_argument(
        "--once",
        action="store_true",
        help="poll one time and exit 1 if any delivery failed",
    )
    commands.add_parser(
        "webhooks",
        help="register this server's webhook on each repository "
        "WATCHED_REPOSITORIES names, pointing at INGRESS_URL",
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
    if args.command == "install-policies":
        return _install_policies(args, environ)
    if args.command == "poll":
        return _poll(args.once, environ)
    if args.command == "webhooks":
        return _webhooks(environ, transport)
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


def _install_policies(
    args: argparse.Namespace, environ: Mapping[str, str]
) -> int:
    if not args.directory.is_dir():
        print(f"error: {args.directory} is not a directory", file=sys.stderr)
        return 2
    database_url = environ.get("DATABASE_URL")
    if not database_url:
        print(
            "error: DATABASE_URL not set; it names the database the "
            "deployment is stored in",
            file=sys.stderr,
        )
        return 2
    checks = checks_from(environ)
    return run_install_policies(
        args.directory,
        args.repository,
        args.commit,
        deploying_over(database_url, build_sha(environ), checks),
        checks,
        check_only=args.check,
    )


def _poll(once: bool, environ: Mapping[str, str]) -> int:
    try:
        settings = PollerSettings.from_environment(environ)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run_poller(poller_from_settings(settings), settings, once=once)


def _webhooks(
    environ: Mapping[str, str], transport: httpx2.BaseTransport | None
) -> int:
    database_url = environ.get("DATABASE_URL")
    if not database_url:
        print(
            "error: DATABASE_URL not set; it names the database what was "
            "registered is recorded in",
            file=sys.stderr,
        )
        return 2
    try:
        settings = HookSettings.from_environment(environ)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run_webhooks(
        settings,
        GitHubForge(settings.token, transport),
        stamped_journal(database_url, build_sha(environ)),
        SqlAlchemyJournalQueries(database_url),
        SystemClock(),
        sys.stdout,
    )


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
