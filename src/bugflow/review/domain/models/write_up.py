"""A checkout agent's write-up, and the key it is stored under."""

from dataclasses import dataclass

from bugflow.shared.domain.values.correlation import Correlation


@dataclass(frozen=True, kw_only=True)
class WriteUp:
    """The write-up one checkout agent wrote in one evaluation."""

    correlation: Correlation
    agent_id: str
    text: str

    @property
    def write_up_id(self) -> str:
        """The key the write-up is stored under: the workflow run and
        the agent.

        It is not a hash of the text. Two evaluations that produce the
        same text are still two runs, and the key says which run wrote
        it.
        """
        return (
            f"{self.correlation.workflow_id}/"
            f"{self.correlation.run_id}/{self.agent_id}"
        )

    @property
    def is_prose(self) -> bool:
        """Whether there is any text other than white space."""
        return bool(self.text.strip())
