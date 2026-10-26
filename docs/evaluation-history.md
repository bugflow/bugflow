# Reading recorded evaluations

For application developers exposing stored review evidence. The readers in
`review/usecases/read_review_record.py` use domain interfaces and do not call
a model or publish to a forge. The HTTP API exposes both readers after checking access to each selected
pull request.

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
the rows and the facts their typed tables hold. That check and the fetch
share a repeatable-read transaction.
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

An application must authorise the caller for every requested pull request
before invoking either reader. Repository scoping prevents a run identifier from selecting
another repository's facts; it does not grant permission to read.

## HTTP API

Send the API's accepted bearer token with each request:

- `GET /api/repositories/{forge}/{owner}/{repo}/evaluations?pr_number=30&pr_number=31&policy_id=ED-02`
- `GET /api/repositories/{forge}/{owner}/{repo}/pull-requests/30/evaluation?workflow_id=review%2F30&run_id=run-id`

Both routes accept an optional `origin` query parameter for canonical
repository selection. [Repository origins](repository-origins.md#canonical-evaluation-reads)
defines its mapping prerequisites, host isolation and unresolved-record
responses. Omitting the parameter preserves hostless selection.

History requires between 1 and 100 explicit positive PR numbers. Repeated
numbers are counted once. The optional policy selects a view while preserving
all observed runs. Detail requires both workflow and run IDs; query parameters
allow workflow IDs containing slashes. Forge is `github` or `forgejo`.
Responses use the Python readers' DTOs without another counting implementation.

A missing or refused token returns 401. Insufficient access returns 403 before
journal or retained review content is read. A batch containing an inaccessible
PR is refused in full. Invalid selectors return 422; an absent authorised
evaluation returns 404; exceeding a reader limit returns 413 without a partial
response. Missing linked content remains a successful detail response with
explicit availability. There is no endpoint for reading an arbitrary exchange
or snapshot ID.

## Who may read

An authenticated contributor may read all evaluation data for a PR when any
retained snapshot of that PR contains a commit with a recognised author or
committer email. This includes evaluations of other commits on the PR and
retained model exchanges. Opening a PR, having a similar login name, or holding
the policy-deployer role does not grant access.

The operator configures identities in Bugflow through `EVALUATION_IDENTITIES`:

```json
[
  {
    "issuer": "https://identity.example",
    "subject": "person-123",
    "emails": ["developer@work.example", "123+developer@users.noreply.github.com"]
  }
]
```

Issuer and subject identify the person independently of login email and client
application. The issuer must be the provider verified by the API. Addresses
match commit metadata exactly, including case. The operator must approve the
aliases; callers cannot register their own through this API. Duplicate
identities, ambiguous shared addresses within an issuer and malformed
configuration stop startup. An omitted list grants no contributor access.

`EVALUATION_ADMIN_ROLE` names the token role that can read all evaluations.
Unset, no role grants administrative read access. Roles come from the configured
`API_ROLES_CLAIM`; every token must still satisfy issuer, audience and allowed
client checks. `API_CLIENTS` must include the applications used by readers.

Alias and administrator-role configuration changes take effect on API restart.
Changing an IDP role affects access when the caller presents a token reflecting
that change; an already issued token can retain its roles until expiry.
The API does not introspect tokens on each request.

Commit email is attribution supplied by the commit, not proof of authorship.
This initial policy accepts operator-approved aliases and unsigned commits.
A recognised contribution in an older retained snapshot still grants access.
If no retained snapshot establishes contribution, access is denied even when
journal evidence survives; an administrator can read that evidence. The check
uses only a boolean contribution result, not the snapshot's content.

The current forge identity is a forge kind, not a server hostname. Deployments
must not combine distinct forge hosts under colliding repository identities.
Product-specific tech leads, mentors and stronger authorship verification are
not implemented.
