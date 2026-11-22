"""The sign-in script every page this server serves loads, and what its
account panel reads.

``GET /sign-in.js`` is the script. A page signs a person in through the
settings page's client and its address, which is the one redirect
address an operator registers, and is sent back to where it started.
It needs no token: it holds no data.

``GET /api/me`` is who the token names, as this server reads it, which
the script's account panel shows. Any accepted token may read its own.
"""

from collections.abc import Callable
from importlib.resources import files
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import Response

from bugflow.shared.domain.values.caller import Caller

#: The script, kept beside this module.
SIGN_IN = "sign_in.js"


def sign_in_routes(app: FastAPI, caller: Callable[..., Caller]) -> None:
    """Serve the sign-in script every page loads, and who a token names."""

    @app.get("/sign-in.js")
    def sign_in_script() -> Response:
        return Response(
            files("bugflow.apps.api").joinpath(SIGN_IN).read_text(),
            media_type="text/javascript",
        )

    @app.get("/api/me")
    def read_me(
        who: Annotated[Caller, Depends(caller)],
    ) -> dict[str, str | list[str]]:
        """Who the token names, as this server reads it: the person's
        id at the provider, the client it was issued to, and the roles
        this server finds in it."""
        return {
            "subject": who.subject,
            "client": who.client,
            "roles": sorted(who.roles),
        }
