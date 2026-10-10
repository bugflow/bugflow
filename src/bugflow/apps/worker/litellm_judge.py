"""Judge a pull request by asking a model behind a LiteLLM proxy.

Each judged policy is judged in a request of its own, with its own
instructions, its own evidence and its own report schema. A policy's file
says which evidence the model is shown: the title and description, those
with the commits and file paths, the commits alone, or the patches too.

How much of the diff a policy that reads patches is shown is its snapshot
fidelity: every patch in one request, one request per file, or each patch cut
to its hunk headers. The worker judges whole diffs; a measurement can use
the others.

A request is an OpenAI-compatible chat completion with the report's JSON
schema as its response format; the proxy's configuration maps the model name
to a provider's model and key. The doctrine and the policy's instructions
are the system message, identical for every pull request. The evidence is
the user message, which is contributor-controlled and never read as
instruction.

Every violation quotes the words that break its clause. A violation whose
quote is not in the text the policy judges is dropped, so a finding always
points at text the author wrote. So is one whose quote is only inside code,
and one citing a clause the policy does not judge: the instructions say
both, and a model does not always hold to them.

The policies are given when the judge is built, parsed from the policy
deployment in force. This module names none and reads no file.

It implements the review context's ``JudgeService`` with the method
context's policies and the work context's call-recording client. It knows
three contexts, so it is in an application.
"""

import hashlib
import inspect
import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx2
from pydantic import BaseModel, ValidationError

from bugflow.apps.shared.policies import ReviewersInForce
from bugflow.method.domain.models.corpus import JUDGE_RUNNER
from bugflow.method.domain.models.policy_text import (
    EVIDENCE_KINDS,
    PolicyText,
)
from bugflow.method.infrastructure.policy_files import unwrap
from bugflow.review.domain.errors import (
    JudgeTemporarilyUnavailableError,
    JudgeUnavailableError,
)
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.finding import Finding, Severity
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.judgement import (
    JudgeExchange,
    JudgeReproduction,
)
from bugflow.review.domain.models.submission import (
    Submission,
    SubmissionCommit,
)
from bugflow.review.domain.values import delimiting
from bugflow.review.domain.values.delimiting import closing_escaped
from bugflow.review.domain.values.passage import (
    SUBJECT_QUOTE,
    normalised,
    unmarked,
)
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.services.object_store import ObjectStoreService
from bugflow.shared.infrastructure.null_object_store import NullObjectStore
from bugflow.work.infrastructure.litellm_client import (
    CallResult,
    LiteLLMClient,
)
from bugflow.work.infrastructure.litellm_roles import (
    ServingUnknownError,
    served_by,
)

DEFAULT_URL = "http://localhost:4000"


#: What each class of model asks the proxy for when no setting names a
#: model: the role of the class's own name. A policy names a class, and
#: several policies share one. Which model fills a role is the proxy's
#: configuration, so nothing here names a vendor's model.
MODEL_CLASS_DEFAULTS = {"small": "small", "medium": "medium", "large": "large"}
DEFAULT_MODEL_CLASS = "medium"
DEFAULT_MODEL = MODEL_CLASS_DEFAULTS[DEFAULT_MODEL_CLASS]


# The wait after a rate limit that does not say how long to wait: long enough
# for a per-minute quota to refill.
RATE_LIMIT_WAIT = timedelta(minutes=1)


# A provider's own wait, inside the error the proxy passes on, whose quotes
# may be escaped by the JSON around it.
_RETRY_DELAY = re.compile(r'\\?"retryDelay\\?"\s*:\s*\\?"(\d+(?:\.\d+)?)s')


# The quotas a provider says a request exceeded. A daily one still comes
# with a retry delay of seconds, but does not refill until the next day.
_QUOTA_ID = re.compile(r'\\?"quotaId\\?"\s*:\s*\\?"([\w-]+)')


# How much of each patch a policy that reads patches is shown: every patch in
# one request, one request per file with the others' paths and line counts,
# or each patch's hunk headers alone.
FIDELITIES = ("whole", "per-file", "summarised")


# What a graded policy may answer. "pass" is not among them: a violation
# that is not a violation is reported by not reporting it.
GRADES: tuple[Severity, ...] = ("fail", "warn")


class Violation(BaseModel):
    clause: str
    quote: str
    explanation: str
    # How bad, for a policy that grades. Absent from a policy that does not
    # ask, whose findings are all warnings.
    severity: Severity | None = None


class JudgeReport(BaseModel):
    violations: list[Violation]


def report_schema(
    clauses: Mapping[str, str], graded: bool = False
) -> dict[str, Any]:
    """Build a policy's report schema, written out without references:
    providers differ in which JSON Schema features structured output
    accepts.

    A graded policy reports a severity with each violation, because how bad
    it is is part of what it was asked. The rest report none, and their
    findings are warnings.
    """
    properties: dict[str, Any] = {
        "clause": {"type": "string", "enum": list(clauses)},
        "quote": {"type": "string"},
        "explanation": {"type": "string"},
    }
    required = ["clause", "quote", "explanation"]
    if graded:
        properties["severity"] = {
            "type": "string",
            "enum": list(GRADES),
        }
        required.append("severity")
    return {
        "type": "object",
        "properties": {
            "violations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        },
        "required": ["violations"],
        "additionalProperties": False,
    }


# The tags evidence is built from. Whatever a contributor wrote is escaped
# against all of them, so it cannot end the block it sits in or any block
# around it, and nothing it says reaches where instructions go.
EVIDENCE_TAGS = (
    "pull_request",
    "title",
    "description",
    "commits",
    "commit",
    "files",
    "file",
)


def _text(value: str) -> str:
    return closing_escaped(value, *EVIDENCE_TAGS)


def _attribute(value: str) -> str:
    """Escape a value so that it stays inside the double-quoted attribute
    it is put in."""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_evidence(snapshot: Submission) -> str:
    return (
        "<pull_request>\n"
        f"<title>{_text(snapshot.title)}</title>\n"
        f"<description>\n{_text(snapshot.body)}\n</description>\n"
        "</pull_request>"
    )


def _title_and_description(snapshot: Submission) -> str:
    return f"{snapshot.title}\n{snapshot.body}"


@dataclass(frozen=True)
class JudgedPolicy:
    """One judged policy: what the model is told, shown and may quote."""

    policy_id: str
    clauses: Mapping[str, str]
    instructions: str
    # The evidence the model sees: the policy's snapshot fidelity.
    evidence: Callable[[Submission], str]
    # The text a violation's quote must come from, and its name.
    quotable: Callable[[Submission], str]
    quotable_name: str
    # What a finding is about, ahead of its clause.
    subject: str
    # One line: what this policy judges.
    summary: str = ""
    # What measuring the policy has shown.
    calibration: str = "not calibrated"
    # The judging profile this policy is qualified against.
    model_class: str = DEFAULT_MODEL_CLASS
    # Whether a quote may come from inside code. Voice is judged on prose;
    # a claim about the diff may well name code.
    quotes_code: bool = False
    # Whether the model grades each violation. A policy that grades asks how
    # bad, and its scenarios say which grade each stands for; the rest are
    # warnings, which is what a finding was before any policy graded.
    graded: bool = False
    # For a policy that reads patches, its evidence at a snapshot fidelity,
    # showing only one file's patch when a path is given.
    evidence_at: Callable[[Submission, str, str | None], str] | None = None
    # The worst grade a finding may carry: a policy not yet trusted to fail
    # is capped at warn, and its model's own grade stays in the exchange.
    ceiling: str = "fail"


def _touched(commit: SubmissionCommit) -> str:
    """The paths one commit touched, escaped as every other path is.

    Said rather than left out where the forge answered none, because
    a judge shown nothing cannot tell a commit that touched nothing
    from a forge that said nothing.
    """
    if not commit.files:
        return (
            "<files>this forge did not say which paths this commit "
            "touched</files>"
        )
    paths = "\n".join(
        f'<file path="{_attribute(path)}"/>' for path in commit.files
    )
    return f"<files>\n{paths}\n</files>"


def render_scope_evidence(snapshot: Submission) -> str:
    commits = "\n".join(
        f'<commit sha="{c.sha[:7]}">\n{_text(c.message.rstrip())}\n'
        f"{_touched(c)}\n</commit>"
        for c in snapshot.commits
    )
    files = "\n".join(
        f'<file path="{_attribute(f.path)}" additions="{f.additions}" '
        f'deletions="{f.deletions}"/>'
        for f in snapshot.files
    )
    return (
        "<pull_request>\n"
        f"<title>{_text(snapshot.title)}</title>\n"
        f"<description>\n{_text(snapshot.body)}\n</description>\n"
        f"<commits>\n{commits}\n</commits>\n"
        f"<files>\n{files}\n</files>\n"
        "</pull_request>"
    )


def _scope_text(snapshot: Submission) -> str:
    return "\n".join(
        [
            snapshot.title,
            snapshot.body,
            *(c.message for c in snapshot.commits),
            *(f.path for f in snapshot.files),
        ]
    )


def render_commit_evidence(snapshot: Submission) -> str:
    commits = "\n".join(
        f'<commit sha="{c.sha[:7]}">\n{_text(c.message.rstrip())}\n</commit>'
        for c in snapshot.commits
    )
    return f"<pull_request>\n<commits>\n{commits}\n</commits>\n</pull_request>"


def _commit_summaries(snapshot: Submission) -> str:
    return "\n".join(
        (c.message.splitlines() or [""])[0] for c in snapshot.commits
    )


# The patch text a request may carry, in all. Past it a file's patch is
# omitted, and its path and line counts stay.
PATCH_BUDGET = 60_000


def _patch_evidence(
    snapshot: Submission,
    fidelity: str = "whole",
    only: str | None = None,
) -> str:
    rendered: list[str] = []
    budget = PATCH_BUDGET
    for f in snapshot.files:
        opening = (
            f'<file path="{_attribute(f.path)}" additions="{f.additions}" '
            f'deletions="{f.deletions}"'
        )
        if f.patch is None:
            rendered.append(f'{opening} patch="omitted by the forge"/>')
        elif fidelity == "summarised":
            headers = "\n".join(
                line for line in f.patch.splitlines() if line.startswith("@@")
            )
            rendered.append(
                f'{opening} patch="hunk headers only">\n'
                f"{_text(headers)}\n</file>"
            )
        elif only is not None and f.path != only:
            rendered.append(f'{opening} patch="shown in another request"/>')
        elif len(f.patch) > budget:
            rendered.append(f'{opening} patch="omitted for size"/>')
        else:
            budget -= len(f.patch)
            rendered.append(f"{opening}>\n{_text(f.patch)}\n</file>")
    return "\n".join(rendered)


def render_honesty_evidence(
    snapshot: Submission,
    fidelity: str = "whole",
    only: str | None = None,
) -> str:
    commits = "\n".join(
        f'<commit sha="{c.sha[:7]}">\n{_text(c.message.rstrip())}\n</commit>'
        for c in snapshot.commits
    )
    return (
        "<pull_request>\n"
        f"<title>{_text(snapshot.title)}</title>\n"
        f"<description>\n{_text(snapshot.body)}\n</description>\n"
        f"<commits>\n{commits}\n</commits>\n"
        f"<files>\n{_patch_evidence(snapshot, fidelity, only)}\n</files>\n"
        "</pull_request>"
    )


def _honesty_text(snapshot: Submission) -> str:
    return "\n".join(
        [
            _scope_text(snapshot),
            *(f.patch for f in snapshot.files if f.patch is not None),
        ]
    )


# Which renderer shows the model its evidence, and which text a quote must
# come from, by the name a policy file's evidence line gives, one of
# EVIDENCE_KINDS. This is the part of a policy that cannot be written in
# its file, because it is code.
EVIDENCE: dict[
    str,
    tuple[
        Callable[[Submission], str],
        Callable[[Submission], str],
        Callable[[Submission, str, str | None], str] | None,
    ],
] = {
    "description": (render_evidence, _title_and_description, None),
    "scope": (render_scope_evidence, _scope_text, None),
    "commits": (render_commit_evidence, _commit_summaries, None),
    "patches": (
        render_honesty_evidence,
        _honesty_text,
        render_honesty_evidence,
    ),
}


def _wired(text: PolicyText) -> JudgedPolicy:
    """Join one policy's prose to the code its evidence line names."""
    try:
        evidence, quotable, evidence_at = EVIDENCE[text.evidence]
    except KeyError:
        raise ValueError(
            f"{text.policy_id}: evidence {text.evidence!r} is not one of "
            f"{', '.join(EVIDENCE_KINDS)}"
        ) from None
    return JudgedPolicy(
        policy_id=text.policy_id,
        clauses=text.clauses,
        instructions=text.instructions,
        evidence=evidence,
        quotable=quotable,
        quotable_name=text.quotable_name,
        subject=text.subject,
        summary=text.summary,
        calibration=text.calibration,
        model_class=text.model_class,
        quotes_code=text.quotes_code,
        graded=text.graded,
        evidence_at=evidence_at,
        ceiling=text.ceiling,
    )


def wire(texts: Mapping[str, PolicyText]) -> dict[str, JudgedPolicy]:
    """Join parsed policies, by id, each to its evidence renderer.

    Raises ``ValueError`` if a policy names evidence this judge cannot
    render.
    """
    return {
        policy_id: _wired(text) for policy_id, text in sorted(texts.items())
    }


# Fenced code blocks and inline code spans.
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)


def render_request(
    snapshot: Submission,
    doctrine: DoctrineText,
    model: str,
    policy_id: str,
    policies: Mapping[str, JudgedPolicy],
    fidelity: str = "whole",
    only: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Build the chat completion the judge sends: the prompt the model
    sees."""
    policy = policies[policy_id]
    evidence = (
        policy.evidence(snapshot)
        if policy.evidence_at is None
        else policy.evidence_at(snapshot, fidelity, only)
    )
    return {
        "model": model,
        # Zero for every judgement. A measurement that samples the judge
        # asks warmer, to read how sure it is of each case.
        "temperature": temperature or 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"<doctrine>\n{doctrine.text}\n</doctrine>\n\n"
                    f"{policy.instructions}"
                ),
            },
            {"role": "user", "content": evidence},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "judge_report",
                "schema": report_schema(policy.clauses, policy.graded),
                "strict": True,
            },
        },
    }


# How a quote is normalised before it is matched or written into a
# finding's message: the review context's, because whether a passage still
# stands is read back from that message by the same rule.
_normalised = normalised
_unmarked = unmarked


def _subject(policy: JudgedPolicy, violation: Violation) -> str:
    """Name what one finding is about: the policy's subject and the words
    it quotes.

    The words are part of it because a finding is resolved by its subject,
    and one passage being rewritten does not rewrite the others. A long
    quote is cut to ``SUBJECT_QUOTE`` characters: long enough to tell two
    passages apart, short enough to read in a table.
    """
    quote = _normalised(violation.quote)
    if len(quote) > SUBJECT_QUOTE:
        quote = quote[:SUBJECT_QUOTE].rstrip() + "..."
    return f'{policy.subject} "{quote}"'


def _severity(violation: Violation, ceiling: str = "fail") -> Severity:
    """Return the grade one violation carries, no worse than the policy's
    ceiling.

    A policy that does not grade reports none, and its findings are
    warnings.
    """
    grade = violation.severity or "warn"
    return "warn" if grade == "fail" and ceiling == "warn" else grade


def findings_from(
    report: JudgeReport,
    snapshot: Submission,
    model: str,
    policy_id: str,
    policies: Mapping[str, JudgedPolicy],
) -> tuple[list[Finding], list[str]]:
    """Make one finding per violation, and list the violations dropped.

    Per violation rather than per clause: each carries its own grade, and
    two passages under one clause can differ in badness. Folding them into
    one finding would report the milder under the worse one's grade, and
    would leave the author one comment to fix two things.
    """
    policy = policies[policy_id]
    text = policy.quotable(snapshot)
    evidence = _unmarked(text)
    prose = _unmarked(_CODE.sub(" ", text))
    code = [_unmarked(span.group(0)) for span in _CODE.finditer(text)]
    by_clause: dict[str, list[Violation]] = {}
    unsupported: list[str] = []
    for violation in report.violations:
        if violation.clause not in policy.clauses:
            unsupported.append(
                f"{violation.clause}: not a clause {policy.policy_id} judges"
            )
            continue
        quote = _unmarked(violation.quote)
        inside_code = not policy.quotes_code and any(
            quote in span for span in code
        )
        if quote and (
            quote in prose or (quote in evidence and not inside_code)
        ):
            by_clause.setdefault(violation.clause, []).append(violation)
        elif quote and quote in evidence:
            unsupported.append(
                f"{violation.clause}: {violation.quote!r} is inside code, "
                "which is not judged"
            )
        else:
            unsupported.append(
                f"{violation.clause}: {violation.quote!r} is not in the "
                f"{policy.quotable_name}"
            )
    order = list(policy.clauses)
    findings = [
        Finding(
            policy_id=policy.policy_id,
            severity=_severity(violation, policy.ceiling),
            clause=clause,
            subject=_subject(policy, violation),
            message=(
                f'"{_normalised(violation.quote)}": {violation.explanation}'
            ),
            judged_by=model,
        )
        for clause, violations in sorted(
            by_clause.items(), key=lambda item: order.index(item[0])
        )
        for violation in violations
    ]
    return findings, unsupported


def _retry_after(result: CallResult) -> timedelta:
    """Return how long a rate-limited request should wait before it is
    sent again.

    The proxy sends Retry-After only for its own cooldowns. A provider's
    wait, when it gives one, is the retryDelay in the error text the proxy
    passes on.
    """
    header = result.headers.get("retry-after")
    if header is not None:
        try:
            return timedelta(seconds=float(header))
        except ValueError:
            pass
    match = _RETRY_DELAY.search(result.text or "")
    if match:
        return timedelta(seconds=float(match.group(1)))
    return RATE_LIMIT_WAIT


def _daily_quota(result: CallResult) -> str | None:
    """Return the daily quota a rate-limited request exceeded, if it names
    one."""
    for match in _QUOTA_ID.finditer(result.text or ""):
        if "PerDay" in match.group(1):
            return match.group(1)
    return None


def _error_message(result: CallResult) -> str:
    payload = result.payload
    if payload is None:
        return (result.text or "")[:200]
    error = payload.get("error")
    message = error.get("message") if isinstance(error, dict) else error
    return str(message)[:200]


def _report(payload: dict[str, Any]) -> JudgeReport:
    """Read the report in a chat completion.

    Raises ``JudgeUnavailableError`` if it holds none that can be read.
    """
    try:
        choice = payload["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise JudgeUnavailableError(
            "the judge's response has no message"
        ) from exc
    finish_reason = choice.get("finish_reason")
    if finish_reason == "content_filter":
        raise JudgeUnavailableError("the model declined to judge this change")
    if not content:
        raise JudgeUnavailableError(
            f"no verdicts returned (finish reason {finish_reason})"
        )
    try:
        return JudgeReport.model_validate_json(content)
    except ValidationError as exc:
        raise JudgeUnavailableError(
            "the judge's report does not match its schema "
            f"(finish reason {finish_reason})"
        ) from exc


def _verdicts(payload: dict[str, Any]) -> tuple[str, ...]:
    """List a response's violations, as sorted "clause: quote" lines."""
    return tuple(
        sorted(
            f"{v.clause}: {_unmarked(v.quote)}"
            for v in _report(payload).violations
        )
    )


class LiteLLMJudge:
    def __init__(
        self,
        url: str,
        key: str,
        model: str | None = None,
        policies: tuple[str, ...] = (),
        transport: httpx2.BaseTransport | None = None,
        fidelity: str = "whole",
        model_classes: Mapping[str, str] | None = None,
        objects: ObjectStoreService | None = None,
        served: Mapping[str, str] | None = None,
        temperature: float = 0.0,
        texts: Mapping[str, PolicyText] | None = None,
        source: str = "",
    ) -> None:
        """Build a judge of the policies named, out of the texts given.

        ``texts`` is the parsed policies by id, as a policy deployment
        holds them, and ``source`` is what the fingerprint hashes for
        them, as ``source_of`` computes it. The prompts are built from
        the one and the fingerprint from the other, so a fingerprint
        names the prose that was asked. A judge given no texts judges
        nothing, which is enough to send an archived request again.

        ``model`` overrides every class, which is what a measurement
        does: one model answers for every policy.

        ``served`` is which model serves each name, when the caller
        already knows, as a test does; otherwise the proxy is asked,
        once.

        Raises ``ValueError`` without a key, for a policy with no text,
        for a fidelity that does not exist or does not apply, and for a
        policy naming a class of model nothing defines.
        """
        if not key:
            raise ValueError("a LiteLLM key is required")
        self._wired = wire(texts or {})
        self._source = source
        unknown = sorted(set(policies) - set(self._wired))
        if unknown:
            raise ValueError(f"no judged policy named {', '.join(unknown)}")
        if fidelity not in FIDELITIES:
            raise ValueError(
                f"no snapshot fidelity named {fidelity}; "
                f"expected one of {', '.join(FIDELITIES)}"
            )
        fixed = sorted(
            p for p in policies if self._wired[p].evidence_at is None
        )
        if fidelity != "whole" and fixed:
            raise ValueError(
                f"{', '.join(fixed)} reads no patches, so its snapshot "
                "fidelity cannot vary"
            )
        self._fidelity = fidelity
        self._temperature = temperature
        self._url = url
        self._override = model
        self._models = dict(model_classes or MODEL_CLASS_DEFAULTS)
        unknown_profiles = sorted(
            {self._wired[p].model_class for p in policies} - set(self._models)
        )
        if unknown_profiles:
            raise ValueError(
                f"no class of model named {', '.join(unknown_profiles)}"
            )
        self._policies = policies
        self._client = httpx2.Client(
            base_url=url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=120.0,
            transport=transport,
        )
        # Every call to a model goes through this, and is kept by it.
        self._calls = LiteLLMClient(self._client, objects or NullObjectStore())
        # Which model serves each name, asked once: the proxy's config only
        # changes when it is deployed, and a deploy starts this worker again.
        self._served: dict[str, str] | None = (
            dict(served) if served is not None else None
        )

    def answering(self, name: str) -> str:
        """Return the model the proxy serves a name with: a role's model,
        or the name itself when it names a model.

        What decides a judgement is the model, so this, not the role, is
        what the fingerprint hashes and what a finding says judged it.
        """
        if self._served is None:
            try:
                self._served = served_by(self._client)
            except ServingUnknownError as exc:
                raise JudgeTemporarilyUnavailableError(
                    f"could not ask the judge at {self._url} which model "
                    f"serves each role: {exc}"
                ) from exc
        return self._served.get(name, name)

    def published_models(self) -> list[str]:
        """List what the proxy publishes, so a class cannot name a model
        that is not there."""
        response = self._request_models()
        return sorted(str(m.get("id")) for m in response.get("data", []))

    def supplied_classes(self) -> set[str]:
        """Return the classes a model is actually supplied for.

        A class with no model named is not supplied, and neither is one
        naming a model the proxy does not publish. Which model fills a
        class is the proxy's business; whether one does at all is what
        decides whether a policy can run.
        """
        published = set(self.published_models())
        return {
            name
            for name, model in self._models.items()
            if model and model in published
        }

    def unsupplied_policies(self) -> tuple[str, ...]:
        """Return the policies whose class no model fills, so they cannot
        run.

        This is not a judge that could not answer. A policy with no model
        of its class was never asked, and a pull request is not left
        unknown on its account; a policy that was asked and refused is
        unknown, because it might have found something.
        """
        supplied = self.supplied_classes()
        return tuple(
            policy_id
            for policy_id in self._policies
            if self._wired[policy_id].model_class not in supplied
        )

    def drop_unsupplied_policies(self) -> tuple[str, ...]:
        """Stop judging the policies whose class no model fills, and say
        which.

        Warning about them is not enough. A policy left in the set is asked,
        fails for want of a model, and leaves the pull request unknown,
        which says the judge could not answer when the truth is that nobody
        asked it. This mutates, once, at startup and before any judging,
        because the alternative is asking the proxy what it publishes from
        inside a constructor.
        """
        dropped = self.unsupplied_policies()
        self._policies = tuple(
            p for p in self._policies if p not in set(dropped)
        )
        return dropped

    def check_model_classes(self) -> None:
        """Refuse a class naming a model the proxy does not publish.

        The class map and the proxy's model list are written from the same
        settings, which is a claim, not a guarantee. This is where the
        claim is checked, once, before any judging. A class left empty is
        not a claim at all: it is a class this server supplies nothing
        for, and the policies needing it do not run.
        """
        published = set(self.published_models())
        wrong = sorted(
            f"{name} names {model}"
            for name, model in self._models.items()
            if model and model not in published
        )
        if self._override and self._override not in published:
            wrong.append(f"JUDGE_MODEL names {self._override}")
        if wrong:
            raise JudgeUnavailableError(
                f"the judge at {self._url} publishes "
                f"{', '.join(sorted(published)) or 'no models'}, but "
                + "; ".join(wrong)
            )

    def _request_models(self) -> dict[str, Any]:
        try:
            answer = self._client.get("/v1/models")
            answer.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise JudgeUnavailableError(
                f"the judge's proxy answered {exc.response.status_code} "
                "when asked what it publishes"
            ) from exc
        except httpx2.RequestError as exc:
            raise JudgeTemporarilyUnavailableError(
                f"could not reach the judge at {self._url}: {exc}"
            ) from exc
        published: dict[str, Any] = answer.json()
        return published

    def model_for(self, policy_id: str) -> str:
        """Return the model judging this policy: the override, or its
        class's."""
        if self._override is not None:
            return self._override
        return self._models[self._wired[policy_id].model_class]

    @property
    def model_id(self) -> str:
        """Name one model when one answers for every policy, else each
        class with its model."""
        models = sorted(
            {self.answering(self.model_for(p)) for p in self._policies}
        )
        if len(models) == 1:
            return models[0]
        # A class once, however many policies it judges, in the order the
        # classes are declared.
        used = {
            self._wired[p].model_class: self.answering(self.model_for(p))
            for p in self._policies
        }
        return ", ".join(
            f"{name}={model}"
            for name, model in used.items()
            if name in self._models and model
        )

    @property
    def policies(self) -> tuple[str, ...]:
        return self._policies

    def policy(self, policy_id: str) -> JudgedPolicy:
        """Return one policy as this judge reads it."""
        return self._wired[policy_id]

    @property
    def fingerprint(self) -> str:
        """Hash the model, the policies' text and the code that builds the
        prompt from them.

        This module holds the output schema, the evidence renderers and
        the rules that drop a violation; ``unwrap`` rejoins each policy's
        prose before it is sent, and ``delimiting`` escapes what a
        contributor wrote. A change to any of them, or to the snapshot
        fidelity, changes the fingerprint and so the corpus version,
        because a prompt the fingerprint stopped following would be a
        judgement nobody could reproduce.
        """
        identity = {
            "fidelity": self._fidelity,
            "temperature": self._temperature,
            "model": self.answering(self._override)
            if self._override
            else None,
            "classes": {
                p: self.answering(self.model_for(p))
                for p in sorted(self._policies)
            },
            "policies": self._source,
            "unwrap": inspect.getsource(unwrap),
            "delimiting": inspect.getsource(delimiting),
            "source": inspect.getsource(sys.modules[__name__]),
        }
        canonical = json.dumps(identity, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]

    def assess(
        self,
        snapshot: Submission,
        doctrine: DoctrineText,
        policy_id: str,
    ) -> JudgeAssessment:
        if policy_id not in self._policies:
            raise ValueError(f"this judge does not judge {policy_id}")
        asked = self.model_for(policy_id)
        requests = [
            render_request(
                snapshot,
                doctrine,
                asked,
                policy_id,
                self._wired,
                self._fidelity,
                only,
                self._temperature,
            )
            for only in self._requested_files(snapshot)
        ]
        completions = [
            self._complete(request, policy_id) for request in requests
        ]
        payloads = [payload for payload, _ in completions]
        # A passage one file's request reports, another's may report again.
        violations = {
            (v.clause, _unmarked(v.quote)): v
            for payload in payloads
            for v in _report(payload).violations
        }
        report = JudgeReport(violations=list(violations.values()))
        # The proxy answers with the name it was asked, which is a role.
        model = self.answering(str(payloads[0].get("model") or asked))
        findings, unsupported = findings_from(
            report, snapshot, model, policy_id, self._wired
        )
        usages = [payload.get("usage") or {} for payload in payloads]
        return JudgeAssessment(
            findings=tuple(findings),
            model=model,
            unsupported=tuple(unsupported),
            # An exchange is one request, so several have none to archive.
            exchange=JudgeExchange(request=requests[0], response=payloads[0])
            if len(requests) == 1
            else None,
            calls=tuple(record for _, record in completions),
            input_tokens=sum(int(u.get("prompt_tokens") or 0) for u in usages),
            output_tokens=sum(
                int(u.get("completion_tokens") or 0) for u in usages
            ),
        )

    def _requested_files(self, snapshot: Submission) -> list[str | None]:
        """List the file each request shows the patch of. None shows them
        all."""
        patched = [f.path for f in snapshot.files if f.patch is not None]
        if self._fidelity == "per-file" and patched:
            return list(patched)
        return [None]

    def reproduce(self, exchange: JudgeExchange) -> JudgeReproduction:
        """Send an archived request again, and compare the violations."""
        payload, _ = self._complete(exchange.request)
        model = payload.get("model") or exchange.request.get("model") or ""
        return JudgeReproduction(
            exchange_id=exchange.exchange_id,
            model=self.answering(str(model)) if model else "",
            archived=_verdicts(exchange.response),
            replayed=_verdicts(payload),
            replay=JudgeExchange(request=exchange.request, response=payload),
        )

    def _complete(
        self, request: dict[str, Any], policy_id: str | None = None
    ) -> tuple[dict[str, Any], CallRecord]:
        """Send a chat completion, and return the response and the record
        of the call.

        What a status code means is this judge's business: a 429 naming a
        daily quota is a day gone, and one naming a rate limit is a
        minute. The client that recorded the call has no opinion about
        it. Each raise carries the call, so a refused judgement is still
        counted.
        """
        result = self._calls.complete(
            request, purpose="judge", policy_id=policy_id
        )
        record = result.record

        if result.error is not None:  # includes timeouts
            raise JudgeTemporarilyUnavailableError(
                f"could not reach the judge at {self._url}: {result.error}",
                calls=(record,),
            )

        status = result.status_code or 0
        if status == 429 and (quota := _daily_quota(result)):
            raise JudgeUnavailableError(
                f"the judge's daily quota {quota} is used up", calls=(record,)
            )
        if status == 429:
            raise JudgeTemporarilyUnavailableError(
                f"the judge answered 429: {_error_message(result)}",
                retry_after=_retry_after(result),
                calls=(record,),
            )
        if status == 408 or status >= 500:
            raise JudgeTemporarilyUnavailableError(
                f"the judge answered {status}: {_error_message(result)}",
                calls=(record,),
            )
        if status >= 400:
            raise JudgeUnavailableError(
                f"the judge answered {status}: {_error_message(result)}",
                calls=(record,),
            )
        if result.payload is None:
            raise JudgeUnavailableError(
                f"the judge answered {status} with no JSON body",
                calls=(record,),
            )
        return result.payload, record


#: The setting that names each class's model. The proxy's model list is
#: written against the same settings, and ``check_model_classes`` refuses
#: a class naming a model the proxy does not publish.
MODEL_CLASS_VARIABLES = {
    "small": "LLM_MODEL_SMALL",
    "medium": "LLM_MODEL_MEDIUM",
    "large": "LLM_MODEL_LARGE",
}


def model_classes_from_environment(
    environ: Mapping[str, str],
) -> dict[str, str]:
    """Read each class's model from its setting: ``LLM_MODEL_SMALL``,
    ``LLM_MODEL_MEDIUM`` and ``LLM_MODEL_LARGE``.

    A class whose setting is not given asks the proxy for the role of
    the class's own name.
    """
    return {
        name: environ.get(variable) or MODEL_CLASS_DEFAULTS[name]
        for name, variable in MODEL_CLASS_VARIABLES.items()
    }


def judging_agent(reviewers: ReviewersInForce) -> str | None:
    """Return the id of the reviewer the judge answers for: the first, in
    id order, whose manifest names the judge as its runner. None if the
    deployment holds no such reviewer."""
    return next(
        (
            agent_id
            for agent_id, agent in sorted(reviewers.agents.items())
            if agent.runner == JUDGE_RUNNER
        ),
        None,
    )


def judge_from_environment(
    environ: Mapping[str, str],
    reviewers: ReviewersInForce | None,
    objects: ObjectStoreService | None = None,
    fidelity: str = "whole",
    temperature: float = 0.0,
) -> LiteLLMJudge | None:
    """Build the judge of the deployment in force, or None without a key
    to call the proxy with.

    Settings: ``LITELLM_MASTER_KEY`` is the key. ``JUDGE_URL`` is the
    proxy's address, by default the local one. ``JUDGE_MODEL``, if
    given, answers for every policy. The classes' models are read by
    ``model_classes_from_environment``.

    The policies judged are the ones the judging reviewer's manifest
    names that the deployment holds a text for. A policy a check
    answers has no text and is not judged. A server that was never sent
    a deployment, or whose deployment has no reviewer the judge answers
    for, gets a judge of no policy.

    ``objects`` is where each call's content is kept, if anywhere.
    """
    key = environ.get("LITELLM_MASTER_KEY")
    if not key:
        return None
    agent_id = judging_agent(reviewers) if reviewers is not None else None
    texts: Mapping[str, PolicyText] = {}
    source = ""
    policies: tuple[str, ...] = ()
    if reviewers is not None and agent_id is not None:
        texts = reviewers.policies[agent_id]
        source = reviewers.policy_sources[agent_id]
        policies = tuple(
            policy_id
            for policy_id in reviewers.agents[agent_id].policies
            if policy_id in texts
        )
    return LiteLLMJudge(
        url=environ.get("JUDGE_URL") or DEFAULT_URL,
        key=key,
        model=environ.get("JUDGE_MODEL") or None,
        policies=policies,
        model_classes=model_classes_from_environment(environ),
        fidelity=fidelity,
        objects=objects,
        temperature=temperature,
        texts=texts,
        source=source,
    )
