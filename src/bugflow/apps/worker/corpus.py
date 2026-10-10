"""The corpus as a running worker assembles it, and the forge context's
view of it."""

import hashlib
import inspect
from dataclasses import replace

from bugflow.forge.domain.values.evaluation_regime import EvaluationRegime
from bugflow.method.domain.models.corpus import (
    JUDGE_RUNNER,
    AgentCorpus,
    Corpus,
)
from bugflow.method.domain.repositories.corpus import CorpusRepository
from bugflow.method.domain.repositories.doctrine import DoctrineRepository
from bugflow.review.domain.services.judge import JudgeService
from bugflow.review.usecases import check_pull_request
from bugflow.shared.domain.values import typography


def checking_fingerprint() -> str:
    """Hash the code that answers a checked policy.

    A checked policy is answered by a function and not by a model, so
    nothing a runner is pinned to covers it: the rule that finds dashes
    and the use case that applies it are the whole of what decides one.
    Hashing their source puts them in the version the findings carry,
    so a rewritten check changes the version like any other change of
    the rules.
    """
    sources = "".join(
        inspect.getsource(module)
        for module in (check_pull_request, typography)
    )
    return hashlib.sha256(sources.encode()).hexdigest()[:12]


class ConfiguredCorpus:
    """Implements ``CorpusRepository`` from the doctrine, the judge and
    the installed reviewers a worker was started with."""

    def __init__(
        self,
        doctrine: DoctrineRepository,
        judge: JudgeService | None,
        agents: tuple[AgentCorpus, ...] = (),
    ) -> None:
        self._doctrine = doctrine
        self._judge = judge
        self._agents = agents

    def load(self) -> Corpus:
        """Return the corpus in force, with the judge's fingerprint
        filled in.

        A reviewer the judge runs is pinned by the judge. The judge is
        asked for its fingerprint here and not when the worker starts,
        because answering can reach the proxy, and a worker that could
        not start without the proxy would be stopped by an outage.
        """
        fingerprint = self._judge.fingerprint if self._judge else None
        return Corpus(
            doctrine=self._doctrine.load(),
            judge=fingerprint,
            agents=tuple(
                replace(agent, pinned=fingerprint)
                if agent.runner == JUDGE_RUNNER
                else agent
                for agent in self._agents
            ),
        )


class ConfiguredEvaluationRegime:
    """Implements the forge context's ``EvaluationRegimeRepository`` from
    the corpus.

    The forge context records a version, the components that made it
    and every installed reviewer's own version, and decides whether a
    commit has already been judged under the first of those.
    """

    def __init__(self, corpus: CorpusRepository) -> None:
        self._corpus = corpus

    def current(self) -> EvaluationRegime:
        corpus = self._corpus.load()
        return EvaluationRegime(
            doctrine_text=corpus.doctrine.text,
            judge_fingerprint=corpus.judge,
            version=corpus.version,
            components=corpus.components(),
            installed=corpus.installed,
            reporting_agent=corpus.reporting_agent,
        )
