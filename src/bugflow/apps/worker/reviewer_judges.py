"""One judge for each reviewer a judge answers for, behind one port.

Each gnome a deployment holds has its own doctrine and its own policies.
A reviewer whose runner is the judge gets a judge of its own policies,
and each of that judge's requests carries that reviewer's doctrine and
no other.

An evaluation carries one doctrine text, which is what a finding's
clause is quoted from and what the corpus version hashes. Here it is
every judged reviewer's doctrine, joined in reviewer id order.
"""

import hashlib
import json
from collections.abc import Mapping

from bugflow.apps.shared.policies import ReviewersInForce
from bugflow.apps.worker.litellm_judge import (
    LiteLLMJudge,
    judge_from_environment,
    judging_agents,
)
from bugflow.method.domain.models.doctrine import Doctrine
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.submission import Submission
from bugflow.shared.domain.services.object_store import ObjectStoreService


class ReviewerJudges:
    """Implements ``JudgeService`` with one ``LiteLLMJudge`` for each
    reviewer, by reviewer id, each with that reviewer's doctrine."""

    def __init__(
        self, judges: Mapping[str, tuple[LiteLLMJudge, DoctrineText]]
    ) -> None:
        """Raises ``ValueError`` if two reviewers name the same policy:
        the worker answers, summarises and publishes each policy by its
        id."""
        self._judges = dict(sorted(judges.items()))
        seen: dict[str, str] = {}
        for agent_id, (judge, _) in self._judges.items():
            for policy_id in judge.policies:
                if policy_id in seen:
                    raise ValueError(
                        f"{policy_id} is a policy of both {seen[policy_id]} "
                        f"and {agent_id}"
                    )
                seen[policy_id] = agent_id

    @property
    def judges(self) -> dict[str, LiteLLMJudge]:
        """Each reviewer's judge, by reviewer id."""
        return {
            agent_id: judge for agent_id, (judge, _) in self._judges.items()
        }

    @property
    def model_id(self) -> str:
        """Each judge's models, once each, in reviewer id order."""
        named = dict.fromkeys(
            judge.model_id for judge in self.judges.values() if judge.policies
        )
        return "; ".join(named)

    @property
    def policies(self) -> tuple[str, ...]:
        """Every judge's policies, in reviewer id order. Read from the
        judges, since startup narrows each one."""
        return tuple(
            policy_id
            for judge in self.judges.values()
            for policy_id in judge.policies
        )

    @property
    def fingerprint(self) -> str:
        """The one judge's fingerprint, or a hash of each reviewer's.

        A deployment with one judged reviewer keeps the fingerprint it
        had when the worker had one judge, so its pull requests are not
        judged again for this change alone.
        """
        prints = {
            agent_id: judge.fingerprint
            for agent_id, judge in self.judges.items()
        }
        if len(prints) == 1:
            return next(iter(prints.values()))
        canonical = json.dumps(prints, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]

    def assess(
        self,
        submission: Submission,
        doctrine: DoctrineText,
        policy_id: str,
    ) -> JudgeAssessment:
        """Ask the judge of the reviewer that holds the policy, with that
        reviewer's doctrine.

        ``doctrine`` is the evaluation's, every judged reviewer's
        joined. A request carries its own reviewer's alone.
        """
        for judge, own in self._judges.values():
            if policy_id in judge.policies:
                return judge.assess(submission, own, policy_id)
        raise ValueError(f"no judge here judges {policy_id}")

    def check_model_classes(self) -> None:
        """Refuse a class naming a model the proxy does not publish."""
        for judge in self.judges.values():
            judge.check_model_classes()

    def drop_unsupplied_policies(self) -> tuple[str, ...]:
        """Stop judging the policies whose class no model fills, in
        every judge, and say which."""
        return tuple(
            policy_id
            for judge in self.judges.values()
            for policy_id in judge.drop_unsupplied_policies()
        )


def _doctrine_text(reviewers: ReviewersInForce, agent_id: str) -> str:
    held = reviewers.doctrine.get(agent_id)
    return held.text if held is not None else ""


def judged_doctrine(reviewers: ReviewersInForce) -> Doctrine:
    """Return the doctrine an evaluation carries: the doctrine of each
    reviewer a judge answers for, joined in reviewer id order. Empty if
    there is no such reviewer."""
    return Doctrine(
        text="\n\n".join(
            text
            for agent_id in judging_agents(reviewers)
            if (text := _doctrine_text(reviewers, agent_id))
        )
    )


def judges_from_environment(
    environ: Mapping[str, str],
    reviewers: ReviewersInForce,
    objects: ObjectStoreService | None = None,
) -> ReviewerJudges | LiteLLMJudge | None:
    """Build a judge for each reviewer a judge answers for, as
    ``judge_from_environment`` builds one, or None without a key to call
    the proxy with.

    A deployment with no such reviewer gets the judge of no policy that
    ``judge_from_environment`` builds for it, whose fingerprint is the
    one it had before reviewers had judges of their own.

    Raises ``ValueError`` if two of the reviewers name the same policy.
    """
    agents = judging_agents(reviewers)
    if not agents:
        return judge_from_environment(environ, reviewers, objects)
    judges: dict[str, tuple[LiteLLMJudge, DoctrineText]] = {}
    for agent_id in agents:
        judge = judge_from_environment(
            environ, reviewers, objects, agent_id=agent_id
        )
        if judge is None:
            return None
        own = DoctrineText(text=_doctrine_text(reviewers, agent_id))
        judges[agent_id] = (judge, own)
    return ReviewerJudges(judges)
