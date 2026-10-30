"""The ``bugflow`` command.

Its subcommands include::

    bugflow allow [REPOSITORY] [--layer LAYER] [--agent REVIEWER]
        [--usd DOLLARS | --no-money-limit]
        [--turns TURNS | --no-turn-limit] [--per CADENCE]
    bugflow cadence CADENCE [--boundary BOUNDARY]
    bugflow declare REPOSITORY [--layer LAYER --boundary BOUNDARY]
        [--withhold SHARE]
    bugflow declared [REPOSITORY]
    bugflow deploy-policies DIRECTORY --repository OWNER/NAME
        --commit SHA --api URL [--check]
    bugflow install-policies DIRECTORY --repository OWNER/NAME
        --commit SHA [--check]
    bugflow discover
    bugflow migrate [--check]
    bugflow repository-origins [--apply MAPPINGS.json]
    bugflow reproduce EXCHANGE_ID
    bugflow poll [--once]
    bugflow prune-webhooks OLD_INGRESS_URL [--dry-run]
    bugflow revoke [REPOSITORY] [--layer LAYER] [--agent REVIEWER]
        --per CADENCE
    bugflow set REPOSITORY GNOME BEHAVIOUR [--profile PROFILE]
    bugflow settings [REPOSITORY]
    bugflow webhooks
    bugflow worker

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

``discover`` lists the repositories of each owner ``DISCOVERY_OWNERS``
names, or that ``FORGE_TOKENS_BY_OWNER`` holds a token for, and keeps
each that is new, renamed, archived or unarchived, in the database
``DATABASE_URL`` names (ADR 008). Every gnome on a repository found
archived is switched off. The worker does the same once a day.

Exit status: 0 if every owner was listed. 1 if any could not be. 2 if a
setting is missing.

``set`` and ``settings`` write and read what each gnome does on each
repository (ADR 008), in the database ``DATABASE_URL`` names. ``set``
sets one gnome on one repository to a BEHAVIOUR, ``off``, ``observe``,
``advise`` or ``gate``, judging by a PROFILE of the deployment in
force, and records who set it. ``settings`` prints what is set. A
repository is watched, judged and published to as its gnomes are set.

``declare``, ``allow``, ``revoke``, ``cadence`` and ``declared`` write
and read what a repository is reviewed under, in the database
``DATABASE_URL`` names. A REPOSITORY is ``owner/name`` on GitHub or
``forgejo:owner/name`` on a Forgejo. Each prints what the database
holds afterwards, read back and not echoed.

``declare`` says, for one repository, any of: where its period on one
layer begins, and the share of its warnings withheld from its pull
requests. Only what the call names is written.

``allow`` binds what a run may spend, in dollars and turns, to a scope:
a repository or every repository of one owner, a layer and a reviewer,
each of which may be left out to mean any. ``--per`` names the cadence
the allowance is counted per, and is ``event`` if left out. ``revoke``
removes one allowance, which is not the same as allowing zero.

``cadence`` says where this server's periods of one cadence begin,
which is what an allowance is counted over where no repository's own
boundary answers. Without ``--boundary`` it prints what is held.

``declared`` prints every declaration and every allowance, or with a
REPOSITORY those that bear on it.

A boundary on a clock is read in the timezone ``PERIODS_TIMEZONE``
names, as the worker reads it.

Exit status: 0 if the command wrote or read what it was asked to. 2 if
``DATABASE_URL`` is not set, if ``PERIODS_TIMEZONE`` is not a timezone,
or if the command refused what it was asked, and then nothing was
written.

``reproduce`` runs an archived judgement again, for calibration: it
sends the request of the exchange EXCHANGE_ID, which a judged finding
names, to the model once more, archives the new exchange, and prints
the violations each found.

Exit status: 0 if the model reported the same violations. 1 if it did
not. 2 if a setting is missing, no exchange has the id, or the model
did not answer.

``migrate`` brings the database named by ``DATABASE_URL`` up to date by
running the scripts it has not run: the package's, and those in the
directories ``DATABASE_SCRIPTS`` names, a deployment's own branch. With
``--check`` it runs nothing and prints the scripts that would be run,
one a line.

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

``webhooks`` registers this server's webhook on each repository on
github.com that a gnome judges, by the settings in the database
``DATABASE_URL`` names, pointing at ``INGRESS_URL`` and signing
with ``WEBHOOK_SECRET``, and changes nothing where the forge already
agrees. It records what it did in the database ``DATABASE_URL`` names.

Exit status: 0 if every repository agrees with the settings. 1 if any
could not be reconciled. 2 if a setting is missing or wrong.

``prune-webhooks`` deletes, from each repository a gnome judges, the
webhook pointing at
OLD_INGRESS_URL, the public address this server answered on before it
moved. Only a webhook whose URL is exactly that address's
``/webhooks/github`` is deleted. It refuses an OLD_INGRESS_URL that is
``INGRESS_URL``, the address it answers on now. With ``--dry-run`` it
lists what it would delete and deletes nothing. It records nothing.

Exit status: 0 if every repository was read, and changed where it had
to be. 1 if any could not be. 2 if a setting is missing or wrong, or
the prune was refused.

``migrate``, ``poll``, ``webhooks`` and ``worker`` write their log
lines as JSON and export traces as ``bugflow.apps.shared.telemetry``
describes, when ``LOG_FORMAT`` and ``OTEL_EXPORTER_OTLP_ENDPOINT`` say
so.

``worker`` runs the worker until it is stopped: it connects to the
Temporal server ``TEMPORAL_ADDRESS`` names, listens on the task queue
``TEMPORAL_TASK_QUEUE`` names, keeps the archive's search index up to
date and reviews pull requests under the policy deployment in force.
Its settings are described in ``bugflow.apps.worker.worker`` and
``bugflow.apps.worker.review``.

Exit status: 0 when stopped. 2 if a setting is missing or wrong, if
the worker has nothing to do, if it refuses to start, or if Temporal
cannot be reached.
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx2

from bugflow.apps.command.declaring import (
    UNNAMED,
    Unnamed,
    run_allow,
    run_cadence,
    run_declare,
    run_declared,
    run_revoke,
)
from bugflow.apps.command.repository_origins import apply_mapping, inventory
from bugflow.apps.command.reproducing import run_reproduce
from bugflow.apps.command.setting import run_set, run_settings
from bugflow.apps.command.webhooks import (
    HookSettings,
    PruneSettings,
    run_prune,
    run_webhooks,
)
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
from bugflow.apps.shared.discovering import (
    discover,
    discovering_from,
    said,
)
from bugflow.apps.shared.journals import build_sha, stamped_journal
from bugflow.apps.shared.telemetry import configure_telemetry
from bugflow.apps.shared.temporal import TemporalUnavailableError
from bugflow.apps.worker import worker
from bugflow.apps.worker.reviewers import periods_timezone
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.forge.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.forge.usecases.prune_webhooks import PruneRefusedError
from bugflow.method.domain.errors import (
    PoliciesRefusedError,
    PolicyDeploymentError,
    PolicyServerError,
    ReviewAgentError,
)
from bugflow.method.domain.models.pace_layer import CADENCES, EVENT
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
from bugflow.review.domain.models.gnome_setting import BEHAVIOURS
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    AssociationRecordMissingError,
)
from bugflow.shared.infrastructure import migrations
from bugflow.shared.infrastructure.system_clock import SystemClock

#: The subcommands that write and read what a repository is reviewed
#: under.
DECLARING = (
    "allow",
    "cadence",
    "declare",
    "declared",
    "revoke",
    "set",
    "settings",
)

#: The subcommands a deployment runs as a service, and the name each
#: exports its telemetry under. The others are run by a person or a
#: pipeline, whose output stays as it is.
SERVICES = {
    "migrate": "migrate",
    "poll": "poller",
    "webhooks": "webhooks",
    "worker": "worker",
}

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
    origins = commands.add_parser(
        "repository-origins",
        help="inventory retained repository references as JSON; optionally "
        "apply explicit per-record origin mappings",
    )
    origins.add_argument("--apply", type=Path, metavar="MAPPINGS.json")
    commands.add_parser(
        "discover",
        help="list the repositories of the owners this server can reach "
        "and keep each that is new, renamed or archived",
    )
    reproduce = commands.add_parser(
        "reproduce",
        help="run an archived judgement again and compare what the model "
        "finds now, for calibration (calls the judge's model once)",
    )
    reproduce.add_argument(
        "exchange_id", help="the exchange a judged finding names"
    )
    poll = commands.add_parser(
        "poll",
        help="list the pull requests of the repositories a gnome judges "
        "and post each change to the ingress at INGRESS_URL, in place of "
        "a webhook the forge cannot deliver",
    )
    poll.add_argument(
        "--once",
        action="store_true",
        help="poll one time and exit 1 if any delivery failed",
    )
    commands.add_parser(
        "webhooks",
        help="register this server's webhook on each repository on "
        "github.com a gnome judges, pointing at INGRESS_URL",
    )
    prune = commands.add_parser(
        "prune-webhooks",
        help="delete the webhook pointing at the address this server "
        "answered on before it moved, from each repository a gnome "
        "judges",
    )
    prune.add_argument(
        "old_ingress_url",
        metavar="OLD_INGRESS_URL",
        help="the public address the server answered on before; refused "
        "if it is INGRESS_URL",
    )
    prune.add_argument(
        "--dry-run",
        action="store_true",
        help="list the webhooks it would delete, and delete nothing",
    )
    commands.add_parser(
        "worker",
        help="run the worker on the task queue TEMPORAL_TASK_QUEUE names: "
        "it keeps the archive's search index up to date and reviews pull "
        "requests under the policy deployment in force",
    )
    _declaring_parsers(commands)
    return parser


def _declaring_parsers(
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    repository = "owner/name, or forgejo:owner/name for one on a Forgejo"
    # An allowance can also name every repository of one owner.
    allowed = (
        "owner/name, or owner/* for every repository of that owner, "
        "either after forgejo: for a Forgejo"
    )
    set_gnome = commands.add_parser(
        "set",
        help="set what one gnome does on one repository, and the profile "
        "of its policies it judges by",
    )
    set_gnome.add_argument("repository", help=repository)
    set_gnome.add_argument("gnome", help="the gnome's reviewer id")
    set_gnome.add_argument(
        "behaviour",
        choices=BEHAVIOURS,
        help="off judges nothing; observe judges and posts nothing; "
        "advise posts its comment and a status that never fails; gate "
        "also fails its status on a fail verdict and decides the label",
    )
    set_gnome.add_argument(
        "--profile",
        help="a profile of the gnome the deployment in force holds. "
        "Omitted, the gnome keeps its profile there, or default",
    )
    settings = commands.add_parser(
        "settings", help="print what each gnome is set to on each repository"
    )
    settings.add_argument(
        "repository",
        nargs="?",
        default="",
        help=repository + ", or omitted for every repository",
    )
    declare = commands.add_parser(
        "declare",
        help="say where a repository's period on a layer begins, the "
        "share of its warnings withheld, and a ledger whose archive this "
        "server keeps",
    )
    declare.add_argument("repository", help=repository)
    declare.add_argument(
        "--layer",
        default="",
        help="the pace layer a --boundary applies to, named as the "
        "deployment's pace-layers.toml names it",
    )
    declare.add_argument(
        "--boundary",
        help="where this repository's period on --layer begins. For a "
        "layer an event fires, the window a burst of deliveries settles "
        "in, as seconds: 60s. For a layer a clock fires, a time, a day "
        "and a time, a day of the month and a time, or a date and a "
        "time: 23:30, 'SUN 23:30', '1 23:30', '2026-09-01 09:00'. Omit "
        "the flag to leave it as it is; an empty value withdraws it",
    )
    declare.add_argument(
        "--withhold",
        type=float,
        metavar="SHARE",
        help="the share of this repository's warnings kept from its "
        "pull requests, between 0 and 1, drawn by finding, so that what "
        "becomes of a warning nobody read can be compared with one "
        "somebody could have. Omit the flag to leave it as it is; a "
        "repository that has declared none withholds nothing",
    )
    declare.add_argument(
        "--archive",
        metavar="LEDGER",
        help="the id of a ledger whose archive this server keeps, for "
        "this repository: the UUID in lower case that the ledger's "
        "events carry. The archive host refuses a ledger nobody bound. "
        "Binding a ledger again to the same place changes nothing. "
        "An unresolved binding can move; a known origin must be retained",
    )
    declare.add_argument(
        "--archive-origin",
        metavar="ORIGIN",
        help="explicit repository origin for --archive; accepts canonical, "
        "HTTPS or SSH spelling. An established ledger origin cannot change",
    )
    declare.add_argument(
        "--scope",
        metavar="PATH",
        help="the scope within the repository the ledger's archive is "
        "kept for, as a path, with --archive. Omitted, or '.', is the "
        "repository's root",
    )
    cadence = commands.add_parser(
        "cadence",
        help="say where this server's periods of one cadence begin: "
        "what an allowance is counted over where no repository's own "
        "boundary answers",
    )
    cadence.add_argument(
        "cadence",
        help="one of " + ", ".join(_clock_cadences()),
    )
    cadence.add_argument(
        "--boundary",
        help="where its periods begin: a time, a day and a time, a day "
        "of the month and a time, or a date and a time. A fortnight, a "
        "quarter and a year can only be said the last way. Omit the "
        "flag to read what is declared; an empty value withdraws it",
    )
    allow = commands.add_parser(
        "allow",
        help="bind what a run may spend to a repository, a layer and a "
        "reviewer; a reviewer nothing allows is not dispatched",
    )
    allow.add_argument(
        "repository",
        nargs="?",
        default="",
        help=allowed + ", or omitted for every repository",
    )
    allow.add_argument(
        "--usd",
        type=float,
        default=None,
        help="dollars. Omitted leaves the money as it is, so a call "
        "about the turns does not rewrite it; pass --no-money-limit to "
        "say unlimited",
    )
    allow.add_argument(
        "--no-money-limit",
        action="store_true",
        help="this allowance does not limit the money",
    )
    allow.add_argument(
        "--turns",
        type=float,
        default=None,
        help="turns. Omitted leaves the turns as they are; pass "
        "--no-turn-limit to say unlimited",
    )
    allow.add_argument(
        "--no-turn-limit",
        action="store_true",
        help="this allowance does not limit turns",
    )
    allow.add_argument(
        "--layer", default="", help="one pace layer, or any when omitted"
    )
    allow.add_argument(
        "--agent", default="", help="one reviewer, or any when omitted"
    )
    allow.add_argument(
        "--per",
        default=EVENT.name,
        choices=tuple(CADENCES),
        help=f"the cadence the allowance is counted per (default: "
        f"{EVENT.name}, which is one run). A cadence a clock fires asks "
        f"what the scope has spent in that calendar period, in the "
        f"timezone PERIODS_TIMEZONE names, and refuses a run once it "
        f"has none left",
    )
    revoke = commands.add_parser(
        "revoke",
        help="remove one allowance; not the same as allowing zero, "
        "which refuses everything",
    )
    revoke.add_argument(
        "repository",
        nargs="?",
        default="",
        help=allowed + ", or omitted for the allowance bound to every "
        "repository",
    )
    revoke.add_argument(
        "--layer", default="", help="the layer the allowance names, if any"
    )
    revoke.add_argument(
        "--agent",
        default="",
        help="the reviewer the allowance names, if any",
    )
    revoke.add_argument(
        "--per",
        required=True,
        choices=tuple(CADENCES),
        help="which of that scope's allowances to remove. Required: a "
        "scope holds one per cadence, and writing the wrong one again "
        "writes a figure and not the one that was there",
    )
    declared = commands.add_parser(
        "declared",
        help="print every declaration and every allowance, which says "
        "whether a review that did not happen was a fault or a setting",
    )
    declared.add_argument(
        "repository",
        nargs="?",
        default="",
        help=repository + ", or omitted for everything",
    )


def _clock_cadences() -> list[str]:
    return [name for name, one in CADENCES.items() if one.on_a_clock]


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
    if args.command in SERVICES:
        configure_telemetry(SERVICES[args.command], environ)
    if args.command == "migrate":
        return _migrate(args.check, environ)
    if args.command == "repository-origins":
        return _repository_origins(args.apply, environ)
    if args.command == "reproduce":
        return run_reproduce(args.exchange_id, environ)
    if args.command == "install-policies":
        return _install_policies(args, environ)
    if args.command == "poll":
        return _poll(args.once, environ)
    if args.command == "webhooks":
        return _webhooks(environ, transport)
    if args.command == "prune-webhooks":
        return _prune_webhooks(
            args.old_ingress_url, args.dry_run, environ, transport
        )
    if args.command == "worker":
        return _worker(environ)
    if args.command == "discover":
        return _discover(environ)
    if args.command in DECLARING:
        return _declaring(args, environ)
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


def _discover(environ: Mapping[str, str]) -> int:
    try:
        discovering = discovering_from(environ, build_sha(environ))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if discovering is None:
        print(
            "error: discovery needs DATABASE_URL, a GitHub token, and an "
            "owner: DISCOVERY_OWNERS, or FORGE_TOKENS_BY_OWNER",
            file=sys.stderr,
        )
        return 2
    found = discover(discovering)
    for line in said(found):
        print(line)
    return 1 if found.failures else 0


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


def _limit(unlimited: bool, figure: float | None) -> float | Unnamed | None:
    """What the call said about one resource: a figure, no limit, or
    nothing, which leaves the allowance as it is."""
    if unlimited:
        return None
    return UNNAMED if figure is None else figure


def _declaring(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    database_url = environ.get("DATABASE_URL")
    if not database_url:
        print(
            "error: DATABASE_URL not set; it names the database the "
            "declarations are kept in",
            file=sys.stderr,
        )
        return 2
    if args.command == "declared":
        return run_declared(database_url, args.repository)
    if args.command == "settings":
        return run_settings(database_url, args.repository)
    try:
        zone = periods_timezone(environ)
        build = build_sha(environ)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.command == "allow":
        return run_allow(
            database_url,
            args.repository,
            _limit(args.no_money_limit, args.usd),
            _limit(args.no_turn_limit, args.turns),
            layer=args.layer,
            agent=args.agent,
            per=args.per,
            build=build,
        )
    if args.command == "revoke":
        return run_revoke(
            database_url,
            args.repository,
            layer=args.layer,
            agent=args.agent,
            per=args.per,
            build=build,
        )
    if args.command == "cadence":
        return run_cadence(
            database_url, args.cadence, args.boundary, zone, build=build
        )
    if args.command == "set":
        return run_set(
            database_url,
            args.repository,
            args.gnome,
            args.behaviour,
            args.profile,
            checks_from(environ),
            build,
        )

    return run_declare(
        database_url,
        args.repository,
        layer=args.layer,
        boundary=args.boundary,
        withhold=args.withhold,
        archive=args.archive,
        archive_origin=args.archive_origin,
        scope=args.scope,
        zone=zone,
        build=build,
        checks=checks_from(environ),
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


def _prune_webhooks(
    old_ingress_url: str,
    dry_run: bool,
    environ: Mapping[str, str],
    transport: httpx2.BaseTransport | None,
) -> int:
    try:
        settings = PruneSettings.from_environment(environ, old_ingress_url)
        return run_prune(
            settings,
            GitHubForge(settings.token, transport),
            sys.stdout,
            dry_run=dry_run,
        )
    except PruneRefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _worker(environ: Mapping[str, str]) -> int:
    try:
        asyncio.run(worker.run(environ))
    except (ValueError, ReviewAgentError, TemporalUnavailableError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
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
    scripts = migrations.locations(environ.get(migrations.SCRIPTS_SETTING))
    if check:
        not_run = migrations.pending(database_url, scripts)
        for name in not_run:
            print(name)
        return 1 if not_run else 0
    migrations.upgrade(database_url, scripts)
    return 0


def main() -> None:
    sys.exit(run())


def _repository_origins(path: Path | None, environ: Mapping[str, str]) -> int:
    database_url = environ.get("DATABASE_URL")
    if not database_url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 2
    try:
        if path is not None:
            apply_mapping(database_url, path)
        print(json.dumps(inventory(database_url), sort_keys=True))
    except AssociationRecordMissingError:
        print("error: mapping names an absent record", file=sys.stderr)
        return 2
    except AssociationConflictError:
        print("error: record already has another origin", file=sys.stderr)
        return 2
    except (ValueError, OSError):
        # Mapping input may contain a mistyped credential-bearing URL.
        print("error: invalid repository mapping", file=sys.stderr)
        return 2
    return 0
