"""What every page this server serves shares: its stylesheet, the
operator's theme over it, and the name the pages are headed with.

``GET /pages.css`` is the stylesheet every page loads, and
``GET /theme.css`` the one each loads after it. The theme is the file
``PAGES_THEME`` names, read when the API starts, and is empty where
none is named, so the pages look as the stylesheet makes them. A rule
in the theme overrides the stylesheet's, so an operator restyles the
pages without changing them.

``PAGES_BRAND`` is the name each page's navigation begins with, or none
where it is not set. Neither needs a token: neither holds data.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response

#: The stylesheet every page loads, kept beside this module.
STYLE = "pages.css"
#: Where a page's navigation puts the brand.
BRAND_MARK = "<!-- brand -->"


@dataclass(frozen=True)
class PageLook:
    """How an operator dresses the pages: a stylesheet loaded after the
    pages' own, and the name their navigation begins with."""

    theme: str = ""
    brand: str = ""


#: The pages as the package makes them: no theme and no brand.
PLAIN = PageLook()


def look_from(environ: Mapping[str, str]) -> PageLook:
    """The look ``PAGES_THEME`` and ``PAGES_BRAND`` name. A theme that
    cannot be read stops the API, rather than serve the pages unstyled
    by it."""
    path = environ.get("PAGES_THEME", "")
    return PageLook(
        theme=Path(path).read_text(encoding="utf-8") if path else "",
        brand=environ.get("PAGES_BRAND", "").strip(),
    )


def page(name: str, look: PageLook) -> str:
    """One of the pages, kept beside this module, with the brand put
    where its navigation marks."""
    brand = ""
    if look.brand:
        brand = f'<span class="brand">{escape(look.brand)}</span>'
    text = files("bugflow.apps.api").joinpath(name).read_text()
    return text.replace(BRAND_MARK, brand)


def page_routes(app: FastAPI, look: PageLook) -> None:
    """Serve the stylesheet and the theme every page loads."""

    @app.get("/pages.css")
    def pages_style() -> Response:
        return Response(
            files("bugflow.apps.api").joinpath(STYLE).read_text(),
            media_type="text/css",
        )

    @app.get("/theme.css")
    def theme_style() -> Response:
        return Response(look.theme, media_type="text/css")
