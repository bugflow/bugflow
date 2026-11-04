"""Summing the rows a spend record lists, one for each run, layer,
agent and kind of fact, into the figures a page shows. Every figure is
summed from the same rows as the runs listed for it, so the two agree."""

from collections import defaultdict
from collections.abc import Sequence

from bugflow.review.domain.models.spend import RunCost
from bugflow.review.dtos.read_repository_operations import RunRow


def by_run(rows: Sequence[RunCost]) -> tuple[RunRow, ...]:
    """What each run spent over the rows, latest first, and runs whose
    latest facts are as late by workflow and run."""
    grouped: dict[tuple[str, str], list[RunCost]] = defaultdict(list)
    for one in rows:
        grouped[(one.workflow_id, one.run_id)].append(one)
    runs = sorted(
        (
            RunRow(
                workflow_id=workflow_id,
                run_id=run_id,
                forge=held[0].forge,
                repo=held[0].repo,
                first=min(one.first for one in held),
                last=max(one.last for one in held),
                usd=sum(one.usd for one in held),
                facts=sum(one.facts for one in held),
            )
            for (workflow_id, run_id), held in grouped.items()
        ),
        key=lambda row: (row.workflow_id, row.run_id),
    )
    runs.sort(key=lambda row: row.last, reverse=True)
    return tuple(runs)
