"""Keeping the archive's search index up to date, as a Temporal workflow.

The work itself is ``IndexArchiveUseCase``, which brings one ledger's
index up to date. This module is the wrapping that lets Temporal run it:

- two activities, which call the use case and list the registered
  ledgers;
- a workflow, which runs the use case for one ledger after another;
- a schedule, which starts the workflow every five minutes for every
  registered ledger.

The archive host also starts the workflow, for one ledger, straight
after it stores a new event.
"""

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict
from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from bugflow.apps.worker.parts import WorkerParts
    from bugflow.archive.domain.errors import ArchiveRefusedError
    from bugflow.archive.domain.repositories.bindings import BindingRepository
    from bugflow.archive.dtos.index_archive import (
        IndexArchiveRequest,
        IndexArchiveResponse,
    )
    from bugflow.archive.infrastructure.pyposlib_keeping import PyposlibKeeping
    from bugflow.archive.infrastructure.pyposlib_searching import (
        PyposlibSearching,
    )
    from bugflow.archive.infrastructure.sqlalchemy_bindings import (
        SqlAlchemyBindings,
    )
    from bugflow.archive.infrastructure.sqlalchemy_kept_events import (
        SqlAlchemyKeptEvents,
    )
    from bugflow.archive.infrastructure.sqlalchemy_search_index import (
        SqlAlchemyIndexedFiles,
        SqlAlchemyIndexPositions,
    )
    from bugflow.archive.infrastructure.temporal_indexing import (
        INDEX_SCHEDULE,
        INDEX_WORKFLOW,
    )
    from bugflow.archive.usecases.index_archive import IndexArchiveUseCase
    from bugflow.shared.infrastructure.s3_object_store import S3ObjectStore

BOUND_LEDGERS_ACTIVITY = "bound_ledgers"
INDEX_ARCHIVE_ACTIVITY = "index_archive"

#: How often the schedule starts the workflow.
EVERY = timedelta(minutes=5)

#: The longest one ledger's catch-up may take. The first catch-up of a
#: ledger fetches every file it has from the object store, which can be
#: slow: one ledger of 1,800 files took twenty minutes just to upload.
CATCH_UP_WITHIN = timedelta(hours=1)


class ArchiveIndexInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: The ledgers to index. Empty means every registered ledger.
    ledgers: tuple[str, ...] = ()


class ArchiveIndexResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: The result for each ledger that was indexed.
    indexed: tuple[IndexArchiveResponse, ...]
    #: The ledgers whose catch-up still failed after its retries.
    failed: tuple[str, ...]


@workflow.defn(name=INDEX_WORKFLOW)
class ArchiveIndexWorkflow:
    """Indexes the given ledgers one after another, or every registered
    ledger if none is given.

    A ledger whose catch-up fails does not stop the others. It is listed
    in the result, and the next run tries it again.
    """

    @workflow.run
    async def run(self, input: ArchiveIndexInput) -> ArchiveIndexResult:
        ledgers = list(input.ledgers)
        if not ledgers:
            ledgers = await workflow.execute_activity(
                BOUND_LEDGERS_ACTIVITY,
                result_type=list[str],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        indexed: list[IndexArchiveResponse] = []
        failed: list[str] = []
        for ledger_id in ledgers:
            try:
                indexed.append(
                    await workflow.execute_activity(
                        INDEX_ARCHIVE_ACTIVITY,
                        IndexArchiveRequest(ledger_id=ledger_id),
                        result_type=IndexArchiveResponse,
                        start_to_close_timeout=CATCH_UP_WITHIN,
                        retry_policy=RetryPolicy(
                            maximum_attempts=3,
                            initial_interval=timedelta(seconds=30),
                        ),
                    )
                )
            except ActivityError:
                failed.append(ledger_id)
        return ArchiveIndexResult(indexed=tuple(indexed), failed=tuple(failed))


class ArchiveIndexActivities:
    """The two activities the workflow calls."""

    def __init__(
        self, bindings: BindingRepository, index: IndexArchiveUseCase
    ) -> None:
        self._bindings = bindings
        self._index = index

    @activity.defn(name=BOUND_LEDGERS_ACTIVITY)
    def bound_ledgers(self) -> list[str]:
        """The ids of every registered ledger, sorted."""
        return sorted(
            binding.ledger_id for binding in self._bindings.bindings()
        )

    @activity.defn(name=INDEX_ARCHIVE_ACTIVITY)
    def index_archive(
        self, request: IndexArchiveRequest
    ) -> IndexArchiveResponse:
        """Bring one ledger's index up to date."""
        try:
            return self._index.execute(request)
        except ArchiveRefusedError as exc:
            # The ledger is no longer registered, or its stored events
            # do not form a valid chain. Trying again would give the
            # same answer, so Temporal is told not to retry.
            raise ApplicationError(str(exc), non_retryable=True) from exc

    def all(self) -> list[Callable[..., Any]]:
        return [self.bound_ledgers, self.index_archive]


def activities_from_environment(
    environ: Mapping[str, str],
) -> ArchiveIndexActivities | None:
    """Build the activities from environment variables.

    Uses ``DATABASE_URL``, ``ARCHIVE_S3_ENDPOINT``, ``ARCHIVE_S3_BUCKET``
    and ``ARCHIVE_S3_REGION``, as the archive host does, and its own key
    for the bucket: ``WORKER_ARCHIVE_S3_ACCESS_KEY`` and
    ``WORKER_ARCHIVE_S3_SECRET_KEY``. The worker only reads the bucket,
    so its key should be a read-only one.

    Returns None if the database, the bucket or the key is not set. The
    worker then runs without indexing.
    """
    database_url = environ.get("DATABASE_URL", "")
    endpoint = environ.get("ARCHIVE_S3_ENDPOINT", "")
    bucket = environ.get("ARCHIVE_S3_BUCKET", "")
    access_key = environ.get("WORKER_ARCHIVE_S3_ACCESS_KEY", "")
    secret_key = environ.get("WORKER_ARCHIVE_S3_SECRET_KEY", "")
    if not (
        database_url and endpoint and bucket and access_key and secret_key
    ):
        return None
    keeping = PyposlibKeeping(
        SqlAlchemyKeptEvents(database_url),
        S3ObjectStore(
            endpoint=endpoint,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            region=environ.get("ARCHIVE_S3_REGION") or "us-east-1",
        ),
    )
    bindings = SqlAlchemyBindings(database_url)
    return ArchiveIndexActivities(
        bindings,
        IndexArchiveUseCase(
            bindings,
            PyposlibSearching(
                keeping,
                SqlAlchemyIndexedFiles(database_url),
                SqlAlchemyIndexPositions(database_url),
            ),
        ),
    )


def parts(environ: Mapping[str, str]) -> WorkerParts:
    """Build the part of a worker that keeps the index up to date: the
    workflow, its two activities and its schedule.

    The part is empty, but for a line saying so, if the settings
    ``activities_from_environment`` reads are not all given.
    """
    indexing = activities_from_environment(environ)
    if indexing is None:
        return WorkerParts(
            lines=(
                "indexes no archive: DATABASE_URL, ARCHIVE_S3_ENDPOINT, "
                "ARCHIVE_S3_BUCKET, WORKER_ARCHIVE_S3_ACCESS_KEY and "
                "WORKER_ARCHIVE_S3_SECRET_KEY are not all set",
            )
        )
    return WorkerParts(
        workflows=(ArchiveIndexWorkflow,),
        activities=tuple(indexing.all()),
        schedules=(ensure_schedule,),
        lines=("indexes the archives it is bound to",),
    )


async def ensure_schedule(client: Client, task_queue: str) -> None:
    """Create the schedule that indexes every registered ledger, unless
    it already exists. If one run is still going when the next is due,
    the next is skipped."""
    try:
        await client.create_schedule(
            INDEX_SCHEDULE,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    ArchiveIndexWorkflow.run,
                    ArchiveIndexInput(),
                    id=f"{INDEX_SCHEDULE}/run",
                    task_queue=task_queue,
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=EVERY)]
                ),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
        )
    except ScheduleAlreadyRunningError:
        return
