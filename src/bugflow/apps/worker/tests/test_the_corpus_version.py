"""Tests of the corpus version: it moves when anything that decides a
finding moves, and each installed reviewer has a version of its own.

One version over everything would make editing one reviewer's prompt
move the version recorded on every other reviewer's findings. So a
reviewer's version is over its own prose and the pinned thing that runs
it, and an evaluation records the set.
"""

from dataclasses import replace

from bugflow.apps.worker.corpus import (
    ConfiguredCorpus,
    ConfiguredEvaluationRegime,
    checking_fingerprint,
)
from bugflow.apps.worker.reviewers import corpus_of
from bugflow.apps.worker.tests.policies import a_judge, deployed
from bugflow.method.domain.models.corpus import AgentCorpus, Corpus
from bugflow.method.domain.models.doctrine import Doctrine
from bugflow.method.tests.policy_files import TOPOLOGY
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.submission import Submission

DOCTRINE = Doctrine(text="**EX-4.** A commit does one thing.")
BASE = Corpus(doctrine=DOCTRINE, judge="judge-1")

PROSE = """\
agent_id: prose
summary: What a change says about itself
runner: judge
governs: yes
policies: P-02
---

It reads what a change says about itself.
"""

#: The same reviewer with a second policy, which a check answers.
PROSE_WITH_A_CHECK = PROSE.replace(
    "policies: P-02\n", "policies: P-02, P-09\nchecks: em-dash P-09 EX-21\n"
)

SECURITY = """\
agent_id: security
summary: Whether a change makes the system easier to attack
runner: managed-agent
governs: no
---

You are reviewing one pull request for security.
"""

POLICY = """\
policy_id: P-02
subject: pull request
summary: The pull request does one thing
model_class: medium
evidence: scope
quotable_name: title
graded: yes
quotes_code: no
clause: EX-4 the pull request does one thing
---
Say whether it does one thing.

=== calibration
Measured once: 13 of 13.
"""

FILES = {
    "pace-layers.toml": TOPOLOGY,
    "prose/reviewer.md": PROSE,
    "prose/policies/P-02-scope.md": POLICY,
    "prose/doctrine/01-voice.md": "**EX-1.** Be terse.\n",
    "security/reviewer.md": SECURITY,
}


def agents_of(
    files: dict[str, str], pinned: str | None = "runner-1"
) -> tuple[AgentCorpus, ...]:
    """Each reviewer's corpus, for a deployment holding these files."""
    reviewers = deployed(files)
    return corpus_of(
        reviewers.agents, reviewers.prose, {"managed-agent": pinned}
    )


def corpus(files: dict[str, str], pinned: str | None = "runner-1") -> Corpus:
    return Corpus(
        doctrine=DOCTRINE, judge="judge-1", agents=agents_of(files, pinned)
    )


def test_equal_components_give_an_equal_version() -> None:
    same = Corpus(doctrine=Doctrine(text=DOCTRINE.text), judge="judge-1")
    assert same.version == BASE.version


def test_a_doctrine_edit_changes_the_version() -> None:
    edited = replace(BASE, doctrine=Doctrine(text=DOCTRINE.text + " Always."))
    assert edited.version != BASE.version


def test_a_judge_change_changes_the_version() -> None:
    assert replace(BASE, judge="judge-2").version != BASE.version
    assert replace(BASE, judge=None).version != BASE.version


def test_a_reviewers_version_follows_its_own_prose() -> None:
    base = AgentCorpus(
        agent_id="security", prose="p1", runner="managed-agent", pinned="r1"
    )
    assert replace(base, prose="p2").version != base.version


def test_a_reviewers_version_follows_the_runner_it_is_pinned_to() -> None:
    base = AgentCorpus(
        agent_id="security", prose="p1", runner="managed-agent", pinned="r1"
    )
    assert replace(base, pinned="r2").version != base.version
    assert replace(base, pinned=None).version != base.version


def test_a_reviewers_version_follows_the_code_that_checks_for_it() -> None:
    """A checked policy is answered by a function and not by the judge.
    A function that changes must move the version, or two findings from
    different code carry one version."""
    base = AgentCorpus(
        agent_id="prose", prose="p1", runner="judge", pinned="j1", checks="c1"
    )
    assert replace(base, checks="c2").version != base.version
    assert replace(base, checks=None).version != base.version


def test_the_installed_set_is_every_reviewers_own_version() -> None:
    installed = corpus(FILES).installed
    assert sorted(installed) == ["prose", "security"]
    assert installed["prose"] != installed["security"]


def test_editing_one_reviewers_prose_moves_only_its_own_version() -> None:
    before = corpus(FILES)
    after = corpus(
        FILES
        | {
            "security/reviewer.md": SECURITY
            + "\nRead the diff before the tree.\n"
        }
    )
    assert after.installed["security"] != before.installed["security"]
    assert after.installed["prose"] == before.installed["prose"]
    assert after.version == before.version


def test_editing_the_judged_reviewers_doctrine_moves_only_its_version() -> (
    None
):
    before = corpus(FILES)
    after = corpus(
        FILES | {"prose/doctrine/01-voice.md": "**EX-1.** Be terse. Always.\n"}
    )
    assert after.installed["prose"] != before.installed["prose"]
    assert after.installed["security"] == before.installed["security"]


def test_repinning_one_runner_moves_only_the_reviewers_it_runs() -> None:
    before = corpus(FILES, pinned="runner-1")
    after = corpus(FILES, pinned="runner-2")
    assert after.installed["security"] != before.installed["security"]
    assert after.installed["prose"] == before.installed["prose"]


def test_a_calibration_note_moves_no_version() -> None:
    """What is below a policy's calibration line is dropped, as the
    judge's fingerprint drops it: writing a measurement down must not
    move the version it was taken under."""
    noted = FILES | {
        "prose/policies/P-02-scope.md": POLICY + "Measured again: 13 of 13.\n"
    }
    assert corpus(noted).installed == corpus(FILES).installed


def test_the_corpus_names_the_reviewer_the_judge_answers_for() -> None:
    assert corpus(FILES).reporting_agent == "prose"


def test_a_reviewer_that_is_not_installed_gets_the_deployments_version() -> (
    None
):
    loaded = corpus(FILES)
    assert loaded.version_for("nobody") == loaded.version
    assert BASE.installed == {}
    assert BASE.reporting_agent == ""
    assert BASE.version_for("prose") == BASE.version


def test_the_checking_code_pins_the_reviewer_whose_manifest_has_a_check() -> (
    None
):
    """Which policy a check answers is the manifest's to say. A reviewer
    whose manifest has a checks line carries the fingerprint of the
    checking code, and one whose manifest has none does not."""
    with_a_check = {
        agent.agent_id: agent.checks
        for agent in agents_of(
            FILES | {"prose/reviewer.md": PROSE_WITH_A_CHECK}
        )
    }
    assert with_a_check == {
        "prose": checking_fingerprint(),
        "security": None,
    }
    without = {agent.agent_id: agent.checks for agent in agents_of(FILES)}
    assert without == {"prose": None, "security": None}


class FakeDoctrine:
    def load(self) -> Doctrine:
        return DOCTRINE


class FakeJudge:
    """A judge that counts being asked for its fingerprint, which a real
    one may have to reach its proxy to answer."""

    def __init__(self) -> None:
        self.asked = 0

    @property
    def model_id(self) -> str:
        return "a-model"

    @property
    def policies(self) -> tuple[str, ...]:
        return ("P-02",)

    @property
    def fingerprint(self) -> str:
        self.asked += 1
        return "judge-fp"

    def assess(
        self,
        submission: Submission,
        doctrine: DoctrineText,
        policy_id: str,
    ) -> JudgeAssessment:
        raise NotImplementedError("nothing here judges anything")


def test_the_judge_pins_the_reviewer_it_runs() -> None:
    loaded = ConfiguredCorpus(
        FakeDoctrine(), FakeJudge(), agents_of(FILES, pinned=None)
    ).load()
    pinned = {agent.agent_id: agent.pinned for agent in loaded.agents}
    assert pinned == {"prose": "judge-fp", "security": None}


def test_loading_keeps_what_the_manifest_said_about_checks() -> None:
    agents = agents_of(FILES | {"prose/reviewer.md": PROSE_WITH_A_CHECK})
    loaded = ConfiguredCorpus(FakeDoctrine(), FakeJudge(), agents).load()
    checks = {agent.agent_id: agent.checks for agent in loaded.agents}
    assert checks == {"prose": checking_fingerprint(), "security": None}


def test_the_judge_is_asked_for_its_fingerprint_only_when_loading() -> None:
    """Asking can reach the proxy, so a worker that could not start
    without an answer would be stopped by an outage."""
    judge = FakeJudge()
    held = ConfiguredCorpus(FakeDoctrine(), judge, agents_of(FILES))
    assert judge.asked == 0
    held.load()
    assert judge.asked == 1


def test_the_configured_corpus_holds_the_doctrine_and_the_judge() -> None:
    judge = a_judge(model="a-model")
    loaded = ConfiguredCorpus(FakeDoctrine(), judge).load()
    assert loaded.doctrine == DOCTRINE
    assert loaded.judge == judge.fingerprint
    assert ConfiguredCorpus(FakeDoctrine(), None).load().judge is None


def test_the_forge_is_given_the_same_version_and_the_installed_set() -> None:
    """The forge context records what the rules in force were, and reads
    none of them."""
    held = ConfiguredCorpus(FakeDoctrine(), FakeJudge(), agents_of(FILES))
    regime = ConfiguredEvaluationRegime(held).current()
    loaded = held.load()
    assert regime.version == loaded.version
    assert regime.doctrine_text == loaded.doctrine.text
    assert regime.judge_fingerprint == loaded.judge
    assert regime.components == loaded.components()
    assert regime.installed == loaded.installed
    assert regime.reporting_agent == "prose"
