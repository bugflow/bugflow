"""A repository's host and path, independent of its forge implementation."""

import re
from dataclasses import dataclass
from typing import Self
from urllib.parse import urlsplit

_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
_PART = re.compile(r"[A-Za-z0-9_.-]+")
_SCP = re.compile(r"(?:[A-Za-z0-9_-]+@)?([^/:]+):([^:]+)")


@dataclass(frozen=True)
class RepositoryOrigin:
    """Keep path case and non-default ports; normalize DNS host case.

    Only two-component repository paths are supported. Transport default
    ports (HTTPS 443 and SSH 22) denote the unqualified host. Other ports
    remain part of the identity. HTTP and local paths are not origins.
    """

    value: str

    def __post_init__(self) -> None:
        if self._canonical(self.value) != self.value:
            raise ValueError("repository origin is not canonical")

    @classmethod
    def parse(cls, text: str) -> Self:
        return cls(cls._canonical(text))

    @staticmethod
    def _canonical(text: str) -> str:
        refusal = "expected a repository origin with a host and owner/name"
        if not text or any(c.isspace() for c in text):
            raise ValueError(refusal)
        if any(c in text for c in "\\%?#"):
            raise ValueError(refusal)
        scheme = ""
        if "://" in text:
            parsed = urlsplit(text)
            if parsed.netloc.endswith(":"):
                raise ValueError(refusal)
            scheme = parsed.scheme
            if scheme not in ("https", "ssh"):
                raise ValueError(refusal)
            if parsed.password is not None or (
                scheme == "https" and parsed.username is not None
            ):
                raise ValueError(refusal)
            if parsed.username is not None and not re.fullmatch(
                r"[A-Za-z0-9_-]+", parsed.username
            ):
                raise ValueError(refusal)
            host = parsed.hostname or ""
            port = parsed.port
            path = parsed.path.removeprefix("/")
        else:
            scp = _SCP.fullmatch(text)
            if scp and ("@" in text or not scp[2].split("/", 1)[0].isdigit()):
                host, path = scp.groups()
                port = None
            else:
                parsed = urlsplit("//" + text)
                if parsed.username is not None:
                    raise ValueError(refusal)
                host = parsed.hostname or ""
                port = parsed.port
                path = parsed.path.removeprefix("/")
        host = host.lower()
        if (
            not _HOST.fullmatch(host)
            or any(
                not part or part.startswith("-") or part.endswith("-")
                for part in host.split(".")
            )
            or host.isdigit()
        ):
            raise ValueError(refusal)
        path = path.removesuffix(".git")
        parts = path.split("/")
        if len(parts) != 2 or any(
            not _PART.fullmatch(part) or part in (".", "..") for part in parts
        ):
            raise ValueError(refusal)
        if port == 0:
            raise ValueError(refusal)
        if (scheme, port) in (("https", 443), ("ssh", 22)):
            port = None
        authority = host if port is None else f"{host}:{port}"
        return f"{authority}/{path}"

    def __str__(self) -> str:
        return self.value
