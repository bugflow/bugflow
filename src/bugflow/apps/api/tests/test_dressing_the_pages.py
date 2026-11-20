"""Tests of how an operator dresses the pages: a theme loaded after the
pages' own stylesheet, and a brand their navigation begins with.

Every page loads the same two stylesheets and starts with the same
navigation, so the settings page and the operations pages look alike
however they are dressed.
"""

from pathlib import Path

import pytest

from bugflow.apps.api.pages import PageLook, look_from
from bugflow.apps.api.tests.doubles import Server

#: Each page, and where it is beside the server's root.
PAGES = {
    "/settings": "",
    "/operations/": "../",
    "/operations/layers": "../",
    "/operations/agent": "../",
    "/operations/allowances": "../",
    "/operations/run": "../",
    "/operations/repository": "../",
}


def test_every_page_loads_the_stylesheet_and_then_the_theme() -> None:
    server = Server()
    for path, root in PAGES.items():
        text = server.client.get(path).text
        style = f'<link rel="stylesheet" href="{root}pages.css">'
        theme = f'<link rel="stylesheet" href="{root}theme.css">'
        assert style in text and theme in text, path
        assert text.index(style) < text.index(theme), path
        assert "<style>" not in text, path


def test_without_a_theme_the_theme_is_empty() -> None:
    server = Server()
    theme = server.client.get("/theme.css")
    assert theme.status_code == 200
    assert theme.headers["content-type"].startswith("text/css")
    assert theme.text == ""
    assert "--accent" in server.client.get("/pages.css").text


def test_the_theme_is_served_as_the_operator_wrote_it() -> None:
    server = Server(PageLook(theme=":root { --accent: #123456; }"))
    assert server.client.get("/theme.css").text == (
        ":root { --accent: #123456; }"
    )


def test_every_page_navigates_to_every_other() -> None:
    server = Server()
    for path in PAGES:
        text = server.client.get(path).text
        for name in ("Settings", "Overview", "Layers", "Agents", "Allowances"):
            assert f">{name}</a>" in text, (path, name)


def test_the_navigation_marks_the_page_it_is_on() -> None:
    server = Server()
    for path, current in (
        ("/settings", 'href="settings" aria-current="page"'),
        ("/operations/", 'href="./" aria-current="page"'),
        ("/operations/layers", 'href="layers" aria-current="page"'),
        ("/operations/agent", 'href="agents" aria-current="page"'),
    ):
        text = server.client.get(path).text
        assert current in text, path
        assert text.count('aria-current="page"') == 1, path


def test_without_a_brand_the_navigation_begins_with_none() -> None:
    server = Server()
    for path in PAGES:
        text = server.client.get(path).text
        assert 'class="brand"' not in text, path
        assert "<!-- brand -->" not in text, path


def test_the_brand_begins_every_page_s_navigation() -> None:
    server = Server(PageLook(brand="Acme <bugflow>"))
    for path in PAGES:
        text = server.client.get(path).text
        assert (
            '<nav><span class="brand">Acme &lt;bugflow&gt;</span>' in text
        ), path


def test_the_look_is_read_from_the_settings(tmp_path: Path) -> None:
    theme = tmp_path / "theme.css"
    theme.write_text("body { color: red; }", encoding="utf-8")
    look = look_from(
        {"PAGES_THEME": str(theme), "PAGES_BRAND": " Acme bugflow "}
    )
    assert look == PageLook(theme="body { color: red; }", brand="Acme bugflow")
    assert look_from({}) == PageLook()


def test_a_theme_that_cannot_be_read_stops_the_api(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        look_from({"PAGES_THEME": str(tmp_path / "missing.css")})
