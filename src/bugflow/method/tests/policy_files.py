"""File texts for tests of deployments: one valid manifest, policy,
topology and doctrine, with invented names, and a helper that writes
them to a directory laid out as a policy repository is."""

from pathlib import Path

MANIFEST = """\
agent_id: prose
summary: What a change says about itself
runner: judge
governs: yes
policies: P-01
---

Reads the title and the description.
"""

POLICY = """\
policy_id: P-01
subject: pull request
summary: The description says what changed
model_class: small
evidence: description
quotable_name: title or description
graded: yes
quotes_code: no
clause: EX-1 the description says what changed
---
Judge whether the description says what changed.
=== calibration
Not measured.
"""

TOPOLOGY = """\
[process.evaluate-pull-request]
subject = "pull request"
judges = true

[layer.pull-request]
cadence = "event"
processes = ["evaluate-pull-request"]
"""

DOCTRINE = "**EX-1.** A description says what changed.\n"

#: The files a server reads, by path, all valid.
READ = {
    "pace-layers.toml": TOPOLOGY,
    "prose/reviewer.md": MANIFEST,
    "prose/policies/P-01-example.md": POLICY,
    "prose/doctrine/01-voice.md": DOCTRINE,
}

#: Files a policy repository may also hold, which are not sent.
NOT_READ = {
    "prose/cases/P-01/one.json": "{}\n",
    "README.md": "notes\n",
    ".github/workflows/deploy.yml": "pipeline\n",
}


def laid_out(directory: Path) -> Path:
    """Write READ and NOT_READ under the directory and return it."""
    for path, text in (READ | NOT_READ).items():
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_text(text)
    return directory
