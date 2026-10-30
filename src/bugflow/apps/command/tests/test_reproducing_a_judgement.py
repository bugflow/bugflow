"""Tests of ``bugflow reproduce``: an archived judgement, run again for
calibration, with what each run found printed side by side.

The archive is kept in memory and the model is a stand-in, so these pin
what the command prints, its exit status, and that the rerun is
archived.
"""

import io

from bugflow.apps.command.command import run
from bugflow.apps.command.reproducing import run_reproduce
from bugflow.review.domain.errors import JudgeUnavailableError
from bugflow.review.domain.models.judgement import (
    JudgeExchange,
    JudgeReproduction,
)
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)

ARCHIVED = JudgeExchange(
    request={"model": "a-model", "messages": []},
    response={"violations": ["VOICE-6: seamless"]},
)
REPLAY = JudgeExchange(
    request=ARCHIVED.request, response={"violations": [], "rerun": True}
)


class Judge:
    """A model that finds ``replayed`` when asked again."""

    def __init__(self, *replayed: str) -> None:
        self.replayed = replayed

    def reproduce(self, exchange: JudgeExchange) -> JudgeReproduction:
        return JudgeReproduction(
            exchange_id=exchange.exchange_id,
            model="a-model",
            archived=("VOICE-6: seamless",),
            replayed=self.replayed,
            replay=REPLAY,
        )


class Silent:
    def reproduce(self, exchange: JudgeExchange) -> JudgeReproduction:
        raise JudgeUnavailableError("the proxy is down")


def archived() -> InMemoryJudgeArchive:
    held = InMemoryJudgeArchive()
    held.put(ARCHIVED)
    return held


def reproduce(
    judge: Judge | Silent, archive: InMemoryJudgeArchive | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    status = run_reproduce(
        ARCHIVED.exchange_id,
        {},
        out=out,
        err=err,
        archive=archive or archived(),
        judge=judge,
    )
    return status, out.getvalue(), err.getvalue()


def test_the_same_violations_found_again_reproduce() -> None:
    status, printed, _ = reproduce(Judge("VOICE-6: seamless"))
    assert status == 0
    assert "reproduced: the model reported the same violations" in printed
    assert "  replayed  VOICE-6: seamless" in printed


def test_different_violations_do_not_reproduce() -> None:
    status, printed, _ = reproduce(Judge())
    assert status == 1
    assert "not reproduced" in printed
    assert "  archived  VOICE-6: seamless" in printed
    assert "  replayed  no violations" in printed


def test_the_rerun_is_archived_beside_the_exchange() -> None:
    held = archived()
    _, printed, _ = reproduce(Judge(), held)
    assert held.get(REPLAY.exchange_id) == REPLAY
    assert f"archived as {REPLAY.exchange_id}" in printed


def test_an_exchange_never_archived_is_refused() -> None:
    status, _, refused = reproduce(Judge(), InMemoryJudgeArchive())
    assert status == 2
    assert refused.startswith("error:")


def test_a_model_that_does_not_answer_is_refused() -> None:
    status, _, refused = reproduce(Silent())
    assert status == 2
    assert "the judge did not answer" in refused


def test_the_command_needs_the_database_and_the_key() -> None:
    assert run(["reproduce", "0" * 64], environ={}) == 2
    assert (
        run(
            ["reproduce", "0" * 64], environ={"DATABASE_URL": "postgresql://x"}
        )
        == 2
    )
