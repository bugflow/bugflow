"""The sign-in script every page this server serves loads.

``GET /sign-in.js`` is the script. A page signs a person in through the
settings page's client and its address, which is the one redirect
address an operator registers, and is sent back to where it started.
It needs no token: it holds no data.
"""

from importlib.resources import files

from fastapi import FastAPI
from fastapi.responses import Response

#: The script, kept beside this module.
SIGN_IN = "sign_in.js"


def sign_in_route(app: FastAPI) -> None:
    """Serve the sign-in script every page loads."""

    @app.get("/sign-in.js")
    def sign_in_script() -> Response:
        return Response(
            files("bugflow.apps.api").joinpath(SIGN_IN).read_text(),
            media_type="text/javascript",
        )
