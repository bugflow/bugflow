"""What one judgement found, and what it cost."""

from dataclasses import dataclass, field

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.shared.domain.models.call_record import CallRecord


@dataclass(frozen=True, kw_only=True)
class JudgeAssessment:
    findings: tuple[Finding, ...]
    #: The model that answered. If the provider fell back to another
    #: model, this is that one, not the one asked for.
    model: str
    #: Verdicts that were dropped because the words they quote are not
    #: in the submission.
    unsupported: tuple[str, ...] = ()
    #: Input tokens, whether or not they were read from a cache.
    input_tokens: int = 0
    output_tokens: int = 0
    #: The request and the response, to be stored. None from a judge
    #: that has none.
    exchange: JudgeExchange | None = None
    #: One record for each call to the model. A judgement may make
    #: several calls, for example one for each file.
    calls: tuple[CallRecord, ...] = field(default_factory=tuple)
