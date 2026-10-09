"""The checks this context offers to anything that lists a server's
checks.

A check here is a use case that reads records and returns rows of
things that need attention. Each is declared with its id and title, the
types of its request and response, and which fields of the response
hold the rows.

The em dash check on a pull request is not one of these. It answers a
policy during an evaluation and returns findings.
"""

from dataclasses import dataclass

from pydantic import BaseModel

from bugflow.review.dtos.check_open_stocktake_findings import (
    CheckOpenStocktakeFindingsRequest,
    CheckOpenStocktakeFindingsResponse,
)


@dataclass(frozen=True)
class DeclaredCheck:
    """One check.

    ``id`` has the form ``<namespace>.<condition>``. ``rows`` names the
    fields of the response that hold what the check found. Any other
    field of the response is a figure.
    """

    id: str
    title: str
    request_model: type[BaseModel]
    response_model: type[BaseModel]
    rows: tuple[str, ...]


DECLARED_CHECKS: tuple[DeclaredCheck, ...] = (
    DeclaredCheck(
        id="stocktake.open-findings",
        title="Findings stocktakes raised that nothing has closed",
        request_model=CheckOpenStocktakeFindingsRequest,
        response_model=CheckOpenStocktakeFindingsResponse,
        rows=("open_findings",),
    ),
)
