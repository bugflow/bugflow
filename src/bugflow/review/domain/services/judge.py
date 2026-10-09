"""The interfaces to the judge."""

from typing import Protocol

from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.judgement import (
    JudgeExchange,
    JudgeReproduction,
)
from bugflow.review.domain.models.submission import Submission


class JudgeService(Protocol):
    @property
    def model_id(self) -> str:
        """The model the judge asks."""
        ...

    @property
    def policies(self) -> tuple[str, ...]:
        """The ids of the policies the judge can answer. Each is asked
        in a request of its own."""
        ...

    @property
    def fingerprint(self) -> str:
        """A hash of the settings that decide a verdict. It is part of
        the corpus version."""
        ...

    def assess(
        self,
        submission: Submission,
        doctrine: DoctrineText,
        policy_id: str,
    ) -> JudgeAssessment:
        """Ask whether the submission breaks one policy.

        Raises ``JudgeUnavailableError`` if the judge refuses or cannot
        answer.
        """
        ...


class JudgeReproducerService(Protocol):
    def reproduce(self, exchange: JudgeExchange) -> JudgeReproduction:
        """Send a stored request again and compare what the model finds
        with what it found before.

        Raises ``JudgeUnavailableError``.
        """
        ...
