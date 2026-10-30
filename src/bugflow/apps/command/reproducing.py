"""``bugflow reproduce``: run an archived judgement again.

Calibration asks whether a finding was the policy's or the model's. A
judged finding names the exchange it came from, and this sends that
exchange's request to the model again, through the proxy the worker
judges through, and says whether the model found the same violations.
The new exchange is archived beside the old one.

It reads the archive in the database ``DATABASE_URL`` names, and calls
the model once with ``LITELLM_MASTER_KEY``, ``JUDGE_URL`` and
``JUDGE_MODEL`` as the worker reads them.
"""

import sys
from collections.abc import Mapping
from typing import TextIO

from bugflow.apps.worker.litellm_judge import judge_from_environment
from bugflow.review.domain.errors import (
    ExchangeNotFoundError,
    JudgeUnavailableError,
)
from bugflow.review.domain.models.judgement import (
    JudgeReproduction,
)
from bugflow.review.domain.repositories.judge_archive import (
    JudgeArchiveRepository,
)
from bugflow.review.domain.services.judge import JudgeReproducerService
from bugflow.review.dtos.reproduce_judgement import ReproduceJudgementRequest
from bugflow.review.infrastructure.sqlalchemy_judge_archive import (
    SqlAlchemyJudgeArchive,
)
from bugflow.review.usecases.reproduce_judgement import (
    ReproduceJudgementUseCase,
)


def said_of(reproduction: JudgeReproduction) -> list[str]:
    """The lines that say what the rerun found beside what was archived."""
    outcome = (
        "reproduced: the model reported the same violations"
        if reproduction.matches
        else "not reproduced: the model reported different violations"
    )
    lines = [
        f"exchange {reproduction.exchange_id}",
        f"rerun by {reproduction.model}, archived as "
        f"{reproduction.replay.exchange_id}",
        outcome,
    ]
    lines += [f"  archived  {v}" for v in reproduction.archived] or [
        "  archived  no violations"
    ]
    lines += [f"  replayed  {v}" for v in reproduction.replayed] or [
        "  replayed  no violations"
    ]
    return lines


def run_reproduce(
    exchange_id: str,
    environ: Mapping[str, str],
    out: TextIO | None = None,
    err: TextIO | None = None,
    archive: JudgeArchiveRepository | None = None,
    judge: JudgeReproducerService | None = None,
) -> int:
    """Run the exchange again and print the comparison.

    Returns 0 when the model reports the same violations, 1 when it
    does not, and 2 when a setting is missing, no exchange has the id,
    or the model does not answer.

    ``archive`` and ``judge`` replace the database and the model, for
    tests.
    """
    out, err = out or sys.stdout, err or sys.stderr
    database_url = environ.get("DATABASE_URL")
    if archive is None and not database_url:
        print("error: DATABASE_URL not set", file=err)
        return 2
    if judge is None:
        judge = judge_from_environment(environ, None)
    if judge is None:
        print(
            "error: LITELLM_MASTER_KEY not set; reproducing calls the "
            "judge's model through the proxy",
            file=err,
        )
        return 2
    try:
        response = ReproduceJudgementUseCase(
            SqlAlchemyJudgeArchive(database_url or "")
            if archive is None
            else archive,
            judge,
        ).execute(ReproduceJudgementRequest(exchange_id=exchange_id))
    except ExchangeNotFoundError as exc:
        print(f"error: {exc}", file=err)
        return 2
    except JudgeUnavailableError as exc:
        print(f"error: the judge did not answer: {exc}", file=err)
        return 2
    for line in said_of(response.reproduction):
        print(line, file=out)
    return 0 if response.reproduction.matches else 1
