"""A judge that calls no model and finds nothing, for tests and for
running an evaluation with no model.

An evaluation that uses it goes through the judging step as usual: a
"judge invoked" fact is recorded with an identity, and an exchange is
stored. Nothing leaves the process.
"""

import hashlib
import inspect
import sys

from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.submission import Submission

MODEL = "stub"


class StubJudge:
    @property
    def model_id(self) -> str:
        return MODEL

    @property
    def policies(self) -> tuple[str, ...]:
        """One policy, named "stub"."""
        return (MODEL,)

    @property
    def fingerprint(self) -> str:
        """A hash of this module's source."""
        source = inspect.getsource(sys.modules[__name__])
        return hashlib.sha256(source.encode()).hexdigest()[:12]

    def assess(
        self,
        submission: Submission,
        doctrine: DoctrineText,
        policy_id: str = MODEL,
    ) -> JudgeAssessment:
        request = {
            "model": MODEL,
            "policy": policy_id,
            "doctrine_version": doctrine.version,
            "snapshot": submission.content_id,
        }
        return JudgeAssessment(
            findings=(),
            model=MODEL,
            exchange=JudgeExchange(
                request=request, response={"model": MODEL, "violations": []}
            ),
        )
