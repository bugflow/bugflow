import pytest

from bugflow.shared.domain.values.repository_origin import RepositoryOrigin


@pytest.mark.parametrize(
    "text",
    [
        "github.com/Example/repo",
        "https://GitHub.COM/Example/repo.git",
        "git@github.com:Example/repo.git",
        "ssh://git@github.com/Example/repo",
        "ssh://git@github.com:22/Example/repo.git",
        "https://github.com:443/Example/repo",
    ],
)
def test_transport_spellings_share_an_origin(text: str) -> None:
    assert str(RepositoryOrigin.parse(text)) == "github.com/Example/repo"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "owner/repo",
        "/owner/repo",
        "../owner/repo",
        "https://host/repo",
        "https://host/a/b/c",
        "http://host/a/b",
        "file:///a/b",
        "https://user:secret@host/a/b",
        "https://user@host/a/b",
        "https://host/a/b?key=secret",
        "https://host/a/b#fragment",
        "https://host/a/%62",
        "https://host/a/..",
        "https://host/./b",
        "https://host/a/b/",
        "https://host/a\\b",
        " host/a/b",
        "https://host:0/a/b",
        "https://host:99999/a/b",
        "host../a/b",
        "ssh://[::1]/a/b",
        "host/a/b\n",
        "https://host:/a/b",
    ],
)
def test_ambiguous_or_malformed_origins_are_refused(text: str) -> None:
    with pytest.raises(ValueError):
        RepositoryOrigin.parse(text)


def test_hosts_ports_and_path_case_are_identity() -> None:
    values = [
        RepositoryOrigin.parse(value)
        for value in (
            "one.example/a/b",
            "two.example/a/b",
            "one.example/A/b",
            "one.example:8443/a/b",
            "one.example/a/B",
        )
    ]
    assert len(set(values)) == len(values)
    assert RepositoryOrigin.parse("https://one.example:8443/a/b") == values[3]


def test_direct_construction_requires_canonical_spelling() -> None:
    with pytest.raises(ValueError):
        RepositoryOrigin("https://host/a/b")


def test_numeric_owner_in_an_explicit_ssh_remote() -> None:
    assert (
        str(RepositoryOrigin.parse("git@host:123/repo.git")) == "host/123/repo"
    )


def test_an_empty_ssh_user_is_refused() -> None:
    with pytest.raises(ValueError):
        RepositoryOrigin.parse("ssh://@host/a/b")
