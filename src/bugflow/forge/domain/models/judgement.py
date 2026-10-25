"""A judgement as the forge reads it, to tell whether content has been
reviewed before (ADR 007)."""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class RecordedJudgement:
    """One ``judge.invoked`` fact on a pull request, read from its table:
    the policy asked about, the content the judge read, how it went and
    the corpus version the judgement ran under."""

    policy_id: str | None
    input_hash: str | None
    status: str
    corpus_version: str | None
