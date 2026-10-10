"""An example policy deployment for tests of the worker, with invented
names, and a helper that puts one in force in a database.

It holds two reviewers. ``prose`` is answered by the judge: it has one
policy with a text, and one a check answers. ``security`` is run by the
managed agent, once a week.
"""

from collections.abc import Mapping

from bugflow.apps.shared.deploying import deploying_over
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.tests.policy_files import DOCTRINE, POLICY
from bugflow.review.domain.values.checked_policy import CHECKS

REPOSITORY = "example-org/pull-request-policies"

#: The repository the deployment declares it reviews, as the journal
#: names it and as a setting names it.
WIDGETS = ("github", "example-org/widgets")

PROSE = """\
agent_id: prose
summary: What a change says about itself
runner: judge
governs: yes
policies: P-01, P-09
checks: em-dash P-09 EX-21
---

Reads the title and the description.
"""

SECURITY = """\
agent_id: security
summary: Whether a change makes the system easier to attack
runner: managed-agent
governs: no
---

Reads the changes of a week for security.
"""

TOPOLOGY = """\
[process.evaluate-pull-request]
subject = "pull request"
judges = true

[process.security-stocktake]
subject = "range"
reviewer = "security"

[layer.pull-request]
cadence = "event"
processes = ["evaluate-pull-request"]

[layer.weekly]
cadence = "weekly"
processes = ["security-stocktake"]
"""

DECLARATIONS = """\
[repository."example-org/widgets"]
policies = ["P-01", "P-09"]
processes = ["evaluate-pull-request", "security-stocktake"]
"""

#: The deployment's files, by path.
FILES = {
    "pace-layers.toml": TOPOLOGY,
    "declarations.toml": DECLARATIONS,
    "prose/reviewer.md": PROSE,
    "prose/policies/P-01-example.md": POLICY,
    "prose/doctrine/01-voice.md": DOCTRINE,
    "security/reviewer.md": SECURITY,
}


def put_in_force(
    database_url: str,
    files: Mapping[str, str] = FILES,
    commit: str = "c" * 40,
) -> None:
    """Store the files as a deployment in the database, put it in
    force, and write the declarations it carries."""
    deploying_over(database_url, None, CHECKS).deploy.execute(
        DeployPoliciesRequest(
            repository=REPOSITORY,
            commit=commit,
            files=tuple(
                PolicyFile(path=path, text=text)
                for path, text in sorted(files.items())
            ),
            sent_by="a test",
        )
    )
