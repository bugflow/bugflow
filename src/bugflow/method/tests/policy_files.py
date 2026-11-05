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

EDITOR = """\
model_class: medium
---
You edit the draft of a review comment. Keep what the author must act
on, in the order it matters, and leave the rest out.
"""

GOOD_EXAMPLE = """\
why: One thing to fix, named first, with what to do about it.
---
The commit changes two things. Split the retry out so each can be
reverted alone.
"""

BAD_EXAMPLE = """\
why: Every finding at the same weight, and the reason hedged.
---
Falls short of One reason in commit. Falls short of Say it once in the
description. This is borderline compliant.
"""

#: The editor's files, by path, all valid.
EDITED = {
    "pr-comment-editor.md": EDITOR,
    "pr-comment-editor/examples/good-01-one-fix.md": GOOD_EXAMPLE,
    "pr-comment-editor/examples/bad-01-every-finding.md": BAD_EXAMPLE,
}

#: The reviewer's directory, which holds its policies and doctrine.
REFERENCES = "prose"

#: Where the reviewer's skill holds its copy of both.
SKILL = "prose/skills/prose-write/references"

#: The files a server reads, by path, all valid.
READ = {
    "pace-layers.toml": TOPOLOGY,
    "prose/reviewer.md": MANIFEST,
    f"{REFERENCES}/policies/P-01-example.md": POLICY,
    f"{REFERENCES}/doctrine/01-voice.md": DOCTRINE,
}

#: Files a policy repository may also hold, which are not sent.
NOT_READ = {
    "prose/cases/P-01/one.json": "{}\n",
    "prose/skills/prose-write/SKILL.md": "A skill.\n",
    f"{SKILL}/policies/P-01-example.md": POLICY,
    f"{SKILL}/doctrine/01-voice.md": DOCTRINE,
    "prose/skills/prose-write/scripts/check-example": "#!/bin/sh\n",
    "README.md": "notes\n",
    ".github/workflows/deploy.yml": "pipeline\n",
}


def laid_out(directory: Path) -> Path:
    """Write READ and NOT_READ under the directory and return it."""
    for path, text in (READ | NOT_READ).items():
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_text(text)
    return directory
