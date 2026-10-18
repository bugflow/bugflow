"""Evaluation access from configured identities and recorded contributions."""

import json
from collections.abc import Mapping

from bugflow.forge.domain.repositories.snapshots import ContributionReader
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ContributionEvaluationAccess:
    def __init__(
        self,
        issuer: str,
        admin_role: str | None,
        aliases: Mapping[tuple[str, str], frozenset[str]],
        contributions: ContributionReader,
    ) -> None:
        self._issuer = issuer
        self._admin_role = admin_role or None
        self._aliases = dict(aliases)
        self._contributions = contributions

    def may_read(
        self, caller: Caller, ref: PullRequestRef, *, origin: str | None = None
    ) -> bool:
        if self._admin_role and self._admin_role in caller.roles:
            return True
        emails = self._aliases.get((self._issuer, caller.subject), frozenset())
        return bool(emails) and self._contributions.has_contribution(
            ref, emails, origin=origin
        )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"{field} must be nonblank text without surrounding whitespace"
        )
    if "*" in value or "?" in value:
        raise ValueError(f"{field} must not contain a wildcard")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(
                "evaluation identities contain a duplicate JSON key"
            )
        result[key] = value
    return result


def access_from_configuration(
    issuer: str,
    admin_role: str | None,
    aliases_json: str,
    contributions: ContributionReader,
) -> ContributionEvaluationAccess:
    """Reject ambiguous identities before constructing the access policy."""
    try:
        configured = json.loads(aliases_json, object_pairs_hook=_unique_object)
    except (ValueError, TypeError) as exc:
        raise ValueError("evaluation identities must be a JSON list") from exc
    if not isinstance(configured, list):
        raise ValueError("evaluation identities must be a JSON list")
    aliases: dict[tuple[str, str], frozenset[str]] = {}
    owners: dict[tuple[str, str], str] = {}
    for identity in configured:
        if not isinstance(identity, dict) or set(identity) != {
            "issuer",
            "subject",
            "emails",
        }:
            raise ValueError(
                "each identity requires only issuer, subject and emails"
            )
        identity_issuer = _text(identity["issuer"], "identity issuer")
        subject = _text(identity["subject"], "identity subject")
        key = (identity_issuer, subject)
        if key in aliases:
            raise ValueError(
                "an evaluation identity is configured more than once"
            )
        emails = identity["emails"]
        if not isinstance(emails, list) or not emails:
            raise ValueError("identity emails must be a nonempty list")
        checked = tuple(_text(email, "identity email") for email in emails)
        if len(set(checked)) != len(checked):
            raise ValueError("an identity email is configured more than once")
        for email in checked:
            owner_key = (identity_issuer, email)
            if owner_key in owners and owners[owner_key] != subject:
                raise ValueError(
                    "an email belongs to multiple subjects at one issuer"
                )
            owners[owner_key] = subject
        aliases[key] = frozenset(checked)
    return ContributionEvaluationAccess(
        _text(issuer, "token issuer"),
        _text(admin_role, "evaluation admin role") if admin_role else None,
        aliases,
        contributions,
    )
