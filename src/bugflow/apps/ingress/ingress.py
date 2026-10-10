"""The ingress: the server that receives deliveries.

Each forge has a route of its own, which verifies the delivery's
signature the way that forge signs, normalises the delivery the way that
forge shapes it, passes it to the receive-delivery use case, and answers
202 at once. Evaluations run on the worker.

A managed agent's completion has a route too, verified the platform's
own way rather than a forge's, and handed to the receive-completion use
case, which signals the evaluation waiting for it.

Run by uvicorn with ``--factory``, as ``app_from_environment``.
"""

import asyncio
import json
import logging
import os
import signal
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from standardwebhooks import Webhook, WebhookVerificationError
from temporalio.client import Client

from bugflow.apps.shared.boundaries import settling_for
from bugflow.apps.shared.deploying import checks_from
from bugflow.apps.shared.journals import (
    build_sha,
    delivery_journal,
    stamped_journal,
)
from bugflow.apps.shared.policies import reviewers_in_force
from bugflow.apps.shared.temporal import (
    TemporalEvaluationStarter,
    TemporalSettings,
    WorkerWorkflows,
    connect,
)
from bugflow.apps.worker import evaluate_pull_request, pull_request
from bugflow.forge.domain.errors import EvaluationStartError
from bugflow.forge.domain.models.delivery import Delivery
from bugflow.forge.domain.services.corpus_refresh import CorpusRefreshPort
from bugflow.forge.dtos.receive_delivery import ReceiveDeliveryRequest
from bugflow.forge.infrastructure.forgejo_delivery import delivery_from_forgejo
from bugflow.forge.infrastructure.github_delivery import delivery_from_github
from bugflow.forge.infrastructure.signatures import (
    FORGEJO_SIGNATURE_HEADER,
    GITHUB_SIGNATURE_HEADER,
    forgejo_signature_valid,
    github_signature_valid,
)
from bugflow.forge.usecases.receive_delivery import ReceiveDeliveryUseCase
from bugflow.method.infrastructure.deployment_watch import (
    stop_on_new_deployment,
)
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.system_clock import SystemClock
from bugflow.work.dtos.receive_completion import ReceiveCompletionRequest
from bugflow.work.infrastructure.managed_agent_completion import (
    completion_from_managed_agent,
)
from bugflow.work.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.work.usecases.receive_completion import ReceiveCompletionUseCase

GITHUB_DELIVERY_HEADER = "X-GitHub-Delivery"
FORGEJO_DELIVERY_HEADER = "X-Forgejo-Delivery"
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]
#: Builds the corpus refresh service over the Temporal client the
#: ingress connected, its settings and the loop that owns the client.
CorpusRefresh = Callable[
    [Client, TemporalSettings, asyncio.AbstractEventLoop], CorpusRefreshPort
]
#: Connects to Temporal; replaced in a test.
Connect = Callable[[TemporalSettings], Awaitable[Client]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookForge:
    """How one forge signs and shapes its deliveries."""

    signature_header: str
    delivery_header: str
    verify: Callable[[str, bytes, str | None], bool]
    normalise: Callable[[Mapping[str, str], dict[str, Any]], Delivery]


GITHUB = WebhookForge(
    GITHUB_SIGNATURE_HEADER,
    GITHUB_DELIVERY_HEADER,
    github_signature_valid,
    delivery_from_github,
)
FORGEJO = WebhookForge(
    FORGEJO_SIGNATURE_HEADER,
    FORGEJO_DELIVERY_HEADER,
    forgejo_signature_valid,
    delivery_from_forgejo,
)


@dataclass(frozen=True, kw_only=True)
class IngressParts:
    """What another server built on this package adds to the ingress.

    ``corpora`` builds the service that loads a repository's corpus
    again after a merge; this package has none, and a merge then refreshes
    nothing. ``instrument`` is called with the app once it is built, for
    tracing its requests.
    """

    corpora: CorpusRefresh | None = None
    instrument: Callable[[FastAPI], None] | None = None


def create_app(
    secret: str,
    receive: ReceiveDeliveryUseCase | None = None,
    lifespan: Lifespan | None = None,
    previous_secret: str | None = None,
    receive_completion: ReceiveCompletionUseCase | None = None,
    review_webhook_secret: str = "",
    instrument: Callable[[FastAPI], None] | None = None,
) -> FastAPI:
    """The ingress, verifying each delivery against the webhook secret.

    While the secret is rotated, a delivery signed with the previous
    secret is accepted too, and logged, so the forge's webhook
    configuration can catch up without deliveries being rejected. An
    empty previous secret is no secret, and accepts nothing.

    ``review_webhook_secret`` is a secret of its own, for the route a
    managed agent's completion arrives on: unset, that route starts all
    the same and accepts nothing, the way an empty ``previous_secret``
    does, so that one credential leaking opens one route.

    ``receive`` and ``receive_completion`` may be set later, by
    ``lifespan``, as ``app.state.receive`` and
    ``app.state.receive_completion``.
    """
    if not secret:
        raise ValueError("a webhook secret is required")
    previous = previous_secret or None
    app = FastAPI(title="bugflow ingress", lifespan=lifespan)
    app.state.receive = receive
    app.state.receive_completion = receive_completion

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def root() -> dict[str, str]:
        """The same answer as /healthz, at the address a proxy asks for.

        A reverse proxy in front of this asks the root for proof that
        something is behind the route, and a 404 is not proof. Nothing
        here identifies a caller, so there is nothing to say beyond what
        this is and that it is up.
        """
        return {"service": "bugflow ingress", "status": "ok"}

    async def accept(request: Request, forge: WebhookForge) -> JSONResponse:
        body = await request.body()
        header = request.headers.get(forge.signature_header)
        if not forge.verify(secret, body, header):
            if previous is None or not forge.verify(previous, body, header):
                return JSONResponse(
                    {"error": "signature does not match"}, status_code=401
                )
            logger.warning(
                "delivery %s verified with WEBHOOK_SECRET_PREVIOUS; "
                "the forge still signs with the previous secret",
                request.headers.get(forge.delivery_header),
            )
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("delivery body is not a JSON object")
            delivery = forge.normalise(request.headers, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        use_case: ReceiveDeliveryUseCase = request.app.state.receive
        try:
            received = await run_in_threadpool(
                use_case.execute, ReceiveDeliveryRequest(delivery=delivery)
            )
        except EvaluationStartError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)

        content: dict[str, str | None] = {
            "delivery_id": delivery.delivery_id,
            "outcome": received.outcome,
            "reason": received.reason,
        }
        if received.evaluation is not None:
            content["workflow_id"] = received.evaluation.workflow_id
            content["run_id"] = received.evaluation.run_id
        return JSONResponse(content, status_code=202)

    @app.post("/webhooks/github")
    async def github_webhook(request: Request) -> JSONResponse:
        return await accept(request, GITHUB)

    @app.post("/webhooks/forgejo")
    async def forgejo_webhook(request: Request) -> JSONResponse:
        return await accept(request, FORGEJO)

    @app.post("/webhooks/managed-agent")
    async def managed_agent_webhook(request: Request) -> JSONResponse:
        """A managed agent's completion: verified, then signalled.

        Signed the way the platform's webhooks are signed (the Standard
        Webhooks scheme, not a forge's), and verified the same way this
        ingress verifies everything else it acts on before it acts. What
        the event says is a session, read back from the platform by the
        review's own adapter once the workflow wakes; this route trusts
        it for nothing more than which run to signal.
        """
        if not review_webhook_secret:
            return JSONResponse(
                {"error": "no review webhook secret is configured"},
                status_code=401,
            )
        body = await request.body()
        try:
            payload = Webhook(review_webhook_secret).verify(
                body, dict(request.headers)
            )
        except WebhookVerificationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        completion = completion_from_managed_agent(
            managed_agent_event(payload)
        )
        if completion is None:
            return JSONResponse(
                {"outcome": "ignored", "reason": "not a completion"},
                status_code=202,
            )
        use_case: ReceiveCompletionUseCase = (
            request.app.state.receive_completion
        )
        received = await run_in_threadpool(
            use_case.execute,
            ReceiveCompletionRequest(completion=completion),
        )
        return JSONResponse(
            {"outcome": received.outcome, "reason": received.reason},
            status_code=202,
        )

    if instrument is not None:
        instrument(app)
    return app


def managed_agent_event(payload: Any) -> Any:
    """The verified payload as the completion reader takes it: an object
    whose ``data`` has a ``type`` and an ``id``, the shape the platform's
    SDK gives an event. A payload of another shape is an event of no
    type, which is not a completion."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = {}
    return SimpleNamespace(
        data=SimpleNamespace(type=data.get("type", ""), id=data.get("id", ""))
    )


def worker_workflows() -> WorkerWorkflows:
    """The worker's workflows, as the starter signals them."""

    def input_for(
        ref: PullRequestRef, settling: float | None
    ) -> pull_request.PullRequestWorkflowInput:
        if settling is None:
            return pull_request.PullRequestWorkflowInput(ref=ref)
        return pull_request.PullRequestWorkflowInput(
            ref=ref, debounce_seconds=settling
        )

    return WorkerWorkflows(
        pull_request=pull_request.PullRequestWorkflow.run,
        input_for=input_for,
        workflow_id_for=evaluate_pull_request.workflow_id_for,
        delivery_signal=pull_request.DELIVERY_SIGNAL,
        close_signal=pull_request.CLOSE_SIGNAL,
        review_complete_signal=evaluate_pull_request.REVIEW_COMPLETE_SIGNAL,
        waits_of=evaluate_pull_request.waits_of,
    )


#: The settings the ingress does not start without.
REQUIRED = ("WEBHOOK_SECRET", "DATABASE_URL")


def app_from_environment(
    environ: Mapping[str, str] | None = None,
    parts: IngressParts | None = None,
    connect: Connect = connect,
) -> FastAPI:
    """The ingress as uvicorn runs it, with ``--factory``.

    Required, and the ingress refuses to start without them:

    - ``WEBHOOK_SECRET``: what the forge signs deliveries with. Without
      it no signature could be checked.
    - ``DATABASE_URL``: the Postgres database the journal, the
      deployment in force and the boundaries are kept in.

    Optional:

    - ``WEBHOOK_SECRET_PREVIOUS``: set only while the secret is rotated.
    - ``REVIEW_WEBHOOK_SECRET``: the managed agent's, registered in the
      platform's console; unset, the ingress still starts and that route
      accepts nothing.
    - ``TEMPORAL_ADDRESS``, ``TEMPORAL_NAMESPACE``, ``TEMPORAL_TASK_QUEUE``
      and ``TEMPORAL_UI_URL``, as ``TemporalSettings`` reads them.
    - ``BUILD_SHA``: the full git sha of the build, recorded with every
      journal entry.
    - ``POLICY_CHECKS``: the checks this server performs, as the API
      reads them.

    A server that was never sent a deployment starts all the same: it
    receives deliveries, hands them to the worker, and stops to read the
    first deployment put in force.

    ``parts`` is what another server built on this package adds.
    ``connect`` replaces the connection to Temporal, for tests.
    """
    environ = os.environ if environ is None else environ
    missing = [name for name in REQUIRED if not environ.get(name)]
    if missing:
        raise ValueError(
            f"{', '.join(missing)} not set; the ingress does not start "
            "without them"
        )
    settings = TemporalSettings.from_environment(environ)
    database_url = environ["DATABASE_URL"]
    build = build_sha(environ)
    checks = checks_from(environ)
    added = parts or IngressParts()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = await connect(settings)
        loop = asyncio.get_running_loop()
        deployments = SqlAlchemyPolicyDeployments(database_url)
        # The pace layers of the deployment in force, read once: a
        # server never sent one has no layers and no settling windows.
        reviewers = reviewers_in_force(deployments, checks)
        starter = TemporalEvaluationStarter(
            client,
            settings,
            loop,
            worker_workflows(),
            settling_for(
                reviewers.layers if reviewers else {},
                SqlAlchemyLayerBoundaries(database_url),
            ),
        )
        app.state.receive = ReceiveDeliveryUseCase(
            delivery_journal(database_url, build),
            SystemClock(),
            starter,
            added.corpora(client, settings, loop) if added.corpora else None,
        )
        app.state.receive_completion = ReceiveCompletionUseCase(
            SqlAlchemyJournalQueries(database_url),
            starter,
            stamped_journal(database_url, build),
            SystemClock(),
        )
        # When a different deployment is put in force, ask this process
        # to shut down as SIGTERM does; the container's restart policy
        # starts it again, and the new start reads the new deployment.
        watching = asyncio.create_task(
            stop_on_new_deployment(
                lambda: os.kill(os.getpid(), signal.SIGTERM),
                reviewers.deployed_from if reviewers else None,
                deployments,
                say=lambda line: print(line, flush=True),
            )
        )
        try:
            yield
        finally:
            watching.cancel()

    return create_app(
        environ["WEBHOOK_SECRET"],
        lifespan=lifespan,
        previous_secret=environ.get("WEBHOOK_SECRET_PREVIOUS"),
        review_webhook_secret=environ.get("REVIEW_WEBHOOK_SECRET", ""),
        instrument=added.instrument,
    )
