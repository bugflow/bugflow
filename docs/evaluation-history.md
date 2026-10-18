# Reading recorded evaluations

For application developers exposing stored review evidence. The readers in
`review/usecases/read_review_record.py` use domain interfaces and do not call
a model or publish to a forge. They are Python use cases; the HTTP API does
not expose them yet.

## History

Construct `ReadReviewHistoryUseCase` with a `HistoryService` and optional
`HistoryLimits`. `SqlAlchemyJournalQueries` reads PostgreSQL;
`InMemoryHistory` accepts stored events for tests. The request contains a
`HistoryScope`: one forge, one `owner/repository`, and explicit positive
pull-request numbers. An optional workflow/run pair narrows the scope.

The response groups observed events by pull request and workflow/run pair.
It preserves event identifiers, event and recording times, build, reviewer,
corpus version and policy-deployment stamps. These stamps identify the
writer's deployment, rather than attributing every event to one policy.

A requested policy adds a policy view without removing other runs or shared
events. Policy summaries distinguish an answered judgement or deterministic
check from no recorded answer. Requested pull requests with no events are
listed separately. Original event rows remain in the response.

Costs sum recorded `llm.called` nanodollars. Run and requested-policy costs
are separate, with source event and call IDs and counts of priced and
unpriced calls. Delegated-session charges are excluded. Some failed attempts
are not journalled, so cost completeness remains unknown.

`finding.resolved` records a judge's silence; `finding.rewritten` records
the disappearance of quoted words. Neither establishes agreement or
correctness. `action.taken` includes actions that were not performed: read
its `performed` and `status` fields. Run completion remains unknown because
the journal has no universal completion event.

## Consistency and bounds

History reads default to 10,000 events and 8 MiB. Applications can supply
different positive limits when assembling the reader. An oversized request
raises `HistoryTooLargeError`; no partial response is returned.

The PostgreSQL adapter checks row count and stored bytes before transferring
payloads. That check and the fetch share a repeatable-read transaction.
Counts derive from those fetched rows. Events are ordered by event time,
recording time and event ID. A transaction that commits after the read's
snapshot cannot alter its result, even with an earlier recording timestamp.
There is no pagination or persistent analysis session.

The stored-byte check includes structural overhead. The use case also checks
serialized response size, since projections can repeat evidence. Event IDs
identify the returned evidence; a later request can see newly committed events.

## Evaluation detail

`ReadReviewRecordUseCase` requires a pull-request reference and workflow/run
pair. Its history dependency implements `HistoryService`; the former
correlation-only journal interface is insufficient. Content references come
only from that scoped evaluation. An absent evaluation raises
`ReviewRecordNotFoundError` before content is read.

The exchange store implements `BoundedJudgeArchiveRepository`. An optional
`BoundedSubmissionSourceRepository` supplies the evaluated submission. The
forge adapter validates the snapshot's pull-request reference and returns
submission fields without commit authorship.

Bounded stores check size before transferring JSON from PostgreSQL. Each
read charges a cumulative content allowance, and the final serialized detail
response must also fit the byte limit. Existing unbounded store methods
remain available to their existing internal callers.

History lists references without opening content. Detail distinguishes
`not_recorded`, `not_checked`, `available` and `missing`. Linked content can
be deleted; its availability is observed when detail is read.

An application must authorise the caller for the repository before invoking
either reader. Repository scoping prevents a run identifier from selecting
another repository's facts; it does not grant permission to read.
