"""Reads a GitHub webhook delivery into a ``Delivery``."""

from collections.abc import Mapping
from typing import Any

from bugflow.forge.domain.models.delivery import (
    Delivery,
    DeliveryComment,
    forge_time,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


def delivery_from_github(
    headers: Mapping[str, str], body: dict[str, Any]
) -> Delivery:
    """Build a ``Delivery`` from the headers and JSON body of a request GitHub
    sent. Raises ``ValueError`` if the headers that identify a GitHub
    delivery are missing.
    """
    lowered = {name.lower(): value for name, value in headers.items()}
    try:
        event = lowered["x-github-event"]
        delivery_id = lowered["x-github-delivery"]
    except KeyError as exc:
        raise ValueError(
            f"not a GitHub delivery: missing the {exc.args[0]} header"
        ) from exc

    repository = body.get("repository") or {}
    owner = (repository.get("owner") or {}).get("login")
    name = repository.get("name")
    full_name = f"{owner}/{name}" if owner and name else None

    ref = None
    if event == "pull_request" and owner and name and "number" in body:
        ref = PullRequestRef(owner=owner, repo=name, number=body["number"])

    comment = None
    if event == "issue_comment":
        issue = body.get("issue") or {}
        # GitHub reports a comment on a pull request as a comment on an issue,
        # and marks the issue with a ``pull_request`` key.
        if owner and name and "number" in issue and "pull_request" in issue:
            ref = PullRequestRef(
                owner=owner, repo=name, number=issue["number"]
            )
        raw = body.get("comment") or {}
        if "id" in raw:
            comment = DeliveryComment(
                comment_id=raw["id"],
                author=(raw.get("user") or {}).get("login") or "",
                body=raw.get("body") or "",
            )

    pull = body.get("pull_request") or {}
    return Delivery(
        forge="github",
        delivery_id=delivery_id,
        event=event,
        action=body.get("action"),
        repository=full_name,
        ref=ref,
        comment=comment,
        merged=bool(pull.get("merged")),
        merge_commit_sha=pull.get("merge_commit_sha") or None,
        updated_at=forge_time(pull.get("updated_at")),
    )
