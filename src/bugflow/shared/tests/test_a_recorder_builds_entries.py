"""Tests of the recorder, and of converting a journal entry to database
columns and back."""

from datetime import UTC, datetime
from uuid import UUID

from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.serde import (
    from_columns,
    from_json,
    to_columns,
    to_json,
)

REF = PullRequestRef(forge="forgejo", owner="someone", repo="one", number=8)
RUN = Correlation(workflow_id="a-workflow", run_id="a-run")
WHEN = datetime(2026, 9, 21, 1, 56, 45, tzinfo=UTC)


def recorder() -> Recorder:
    return Recorder(REF, RUN, "v1", WHEN)


def test_an_entry_carries_the_pull_request_the_run_and_the_time() -> None:
    made = recorder().entry(
        "pr.observed", "a-key", {"count": 2}, commit_sha="a" * 40
    )

    assert made == JournalEntry(
        event_id=event_id(RUN, "pr.observed", "a-key"),
        occurred_at=WHEN,
        event_type="pr.observed",
        forge="forgejo",
        repo="someone/one",
        pr_number=8,
        commit_sha="a" * 40,
        corpus_version="v1",
        workflow_id="a-workflow",
        run_id="a-run",
        payload={"count": 2},
    )


def test_an_entry_may_name_an_agent_and_its_own_corpus_version() -> None:
    made = recorder().entry(
        "finding.raised", "k", {}, agent_id="an-agent", corpus_version="v2"
    )

    assert (made.agent_id, made.corpus_version) == ("an-agent", "v2")


def test_two_keys_give_two_ids_and_one_key_gives_one() -> None:
    one = recorder().entry("pr.observed", "one", {})
    assert one.event_id != recorder().entry("pr.observed", "two", {}).event_id
    assert one.event_id == recorder().entry("pr.observed", "one", {}).event_id


def test_an_entry_converted_to_columns_and_back_is_the_same() -> None:
    made = recorder().entry("pr.observed", "a-key", {"nested": {"n": 1}})

    read_back = from_columns(JournalEntry, to_columns(made))

    assert read_back == made
    # Checked by type as well, because a UUID and its string compare
    # unequal but a careless conversion could leave strings behind.
    assert isinstance(read_back.event_id, UUID)
    assert isinstance(read_back.occurred_at, datetime)
    assert read_back.occurred_at.tzinfo is not None


def test_a_value_converted_to_json_and_back_is_the_same() -> None:
    as_json = to_json(REF)

    assert as_json == {
        "forge": "forgejo",
        "owner": "someone",
        "repo": "one",
        "number": 8,
    }
    assert from_json(PullRequestRef, as_json) == REF
