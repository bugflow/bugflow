"""A store of write-ups that keeps them in a dictionary, for tests and
for running an evaluation with no database."""

from bugflow.review.domain.errors import WriteUpNotFoundError
from bugflow.review.domain.models.write_up import WriteUp


class InMemoryWriteUpArchive:
    def __init__(self) -> None:
        self.write_ups: dict[str, WriteUp] = {}

    def put(self, write_up: WriteUp) -> str:
        self.write_ups.setdefault(write_up.write_up_id, write_up)
        return write_up.write_up_id

    def get(self, write_up_id: str) -> WriteUp:
        try:
            return self.write_ups[write_up_id]
        except KeyError as exc:
            raise WriteUpNotFoundError(
                f"no archived write-up {write_up_id}"
            ) from exc
