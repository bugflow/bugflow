"""Posts deliveries to the server's own delivery endpoint, as a forge would.

The poller uses this. Each delivery is posted to ``/webhooks/github`` or
``/webhooks/forgejo`` under the server's URL, with a body shaped as that
forge shapes it and signed with the webhook secret, so the receiving side
handles it exactly like a real one.

The body holds only what the receiving side reads. For a pull request
delivery that is the action, the number and the repository. For a comment
it is the issue, marked as a pull request, and the comment.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx2

from bugflow.forge.domain.errors import DeliveryNotAcceptedError
from bugflow.forge.domain.models.delivery import Delivery
from bugflow.forge.infrastructure.signatures import (
    FORGEJO_SIGNATURE_HEADER,
    GITHUB_SIGNATURE_HEADER,
    digest,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


def _ref(delivery: Delivery) -> PullRequestRef:
    if delivery.ref is None:
        raise ValueError("only deliveries about a pull request are posted")
    return delivery.ref


def _repository(ref: PullRequestRef) -> dict[str, Any]:
    return {
        "name": ref.repo,
        "full_name": f"{ref.owner}/{ref.repo}",
        "owner": {"login": ref.owner},
    }


def _comment(delivery: Delivery) -> dict[str, Any]:
    assert delivery.comment is not None
    return {
        "id": delivery.comment.comment_id,
        "user": {"login": delivery.comment.author},
        "body": delivery.comment.body,
    }


def _pull_request(delivery: Delivery) -> dict[str, Any]:
    """The part of the body about the pull request itself. Only the time it
    last changed is included, since that is all the receiving side reads
    from a polled delivery.
    """
    if delivery.updated_at is None:
        return {}
    return {"pull_request": {"updated_at": delivery.updated_at.isoformat()}}


def github_payload(delivery: Delivery) -> dict[str, Any]:
    ref = _ref(delivery)
    if delivery.comment is not None:
        return {
            "action": delivery.action,
            "issue": {"number": ref.number, "pull_request": {}},
            "comment": _comment(delivery),
            "repository": _repository(ref),
        }
    return {
        "action": delivery.action,
        "number": ref.number,
        "repository": _repository(ref),
        **_pull_request(delivery),
    }


def forgejo_payload(delivery: Delivery) -> dict[str, Any]:
    """The body as Forgejo shapes it. A push is "synchronized", and a comment
    on a pull request has a value under its issue's ``pull_request`` key.
    """
    ref = _ref(delivery)
    if delivery.comment is not None:
        return {
            "action": delivery.action,
            "is_pull": True,
            "issue": {"number": ref.number, "pull_request": {"merged": False}},
            "comment": _comment(delivery),
            "repository": _repository(ref),
        }
    action = "synchronized" if delivery.action == "synchronize" else None
    return {
        "action": action or delivery.action,
        "number": ref.number,
        "repository": _repository(ref),
        **_pull_request(delivery),
    }


def github_headers(
    delivery: Delivery, body: bytes, secret: bytes
) -> dict[str, str]:
    return {
        "X-GitHub-Event": delivery.event,
        "X-GitHub-Delivery": delivery.delivery_id,
        GITHUB_SIGNATURE_HEADER: f"sha256={digest(secret, body)}",
        "Content-Type": "application/json",
    }


def forgejo_headers(
    delivery: Delivery, body: bytes, secret: bytes
) -> dict[str, str]:
    return {
        "X-Forgejo-Event": delivery.event,
        "X-Forgejo-Delivery": delivery.delivery_id,
        FORGEJO_SIGNATURE_HEADER: digest(secret, body),
        "Content-Type": "application/json",
    }


Payload = Callable[[Delivery], dict[str, Any]]
Headers = Callable[[Delivery, bytes, bytes], dict[str, str]]
SHAPES: dict[str, tuple[Payload, Headers]] = {
    "github": (github_payload, github_headers),
    "forgejo": (forgejo_payload, forgejo_headers),
}


class SignedWebhookSink:
    """Implements ``DeliverySinkService`` over HTTP."""

    def __init__(
        self,
        url: str,
        secret: str,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        """``url`` is the server's own address with no path, such as
        ``http://server.example:8000``. ``secret`` is the webhook secret.
        ``transport`` replaces the network, for tests.
        """
        if not secret:
            raise ValueError("a webhook secret is required")
        self._url = url.rstrip("/")
        self._secret = secret.encode()
        self._client = httpx2.Client(timeout=30.0, transport=transport)

    def send(self, delivery: Delivery) -> str:
        if delivery.forge not in SHAPES:
            raise DeliveryNotAcceptedError(
                f"the server has no route for the {delivery.forge} forge"
            )
        payload, headers = SHAPES[delivery.forge]
        body = json.dumps(payload(delivery)).encode()
        try:
            response = self._client.post(
                f"{self._url}/webhooks/{delivery.forge}",
                content=body,
                headers=headers(delivery, body, self._secret),
            )
        except httpx2.RequestError as exc:
            raise DeliveryNotAcceptedError(
                f"could not reach the server: {exc}"
            ) from exc
        if response.status_code != 202:
            raise DeliveryNotAcceptedError(
                f"the server answered {response.status_code}: "
                f"{response.text[:200]}"
            )
        return str(response.json().get("outcome", ""))
