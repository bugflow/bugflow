"""A directory laid out as a policy repository, for tests."""

from pathlib import Path

#: The files a server reads, by path.
READ = {
    "pace-layers.toml": '[layer.pull-request]\ncadence = "event"\n',
    "prose/reviewer.md": "agent_id: prose\n---\nReads the description.\n",
    "prose/policies/XX-01-example.md": "policy_id: XX-01\n---\nJudge it.\n",
    "prose/doctrine/01-voice.md": "**EX-1.** Say what changed.\n",
}

#: Files a policy repository may also hold, which are not sent.
NOT_READ = {
    "prose/cases/XX-01/one.json": "{}\n",
    "README.md": "notes\n",
    ".github/workflows/deploy.yml": "pipeline\n",
}


def laid_out(directory: Path) -> Path:
    """Write READ and NOT_READ under the directory and return it."""
    for path, text in (READ | NOT_READ).items():
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_text(text)
    return directory
