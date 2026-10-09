"""Checking that a delivery really came from the forge.

When a webhook is created it is given a secret. The forge uses the
secret to sign each delivery: it computes an HMAC-SHA256 of the request
body and puts it in a header. The server computes the same thing and
compares. Anyone who does not know the secret cannot produce a matching
signature.

GitHub and Forgejo use different headers and write the signature
slightly differently.
"""

import hashlib
import hmac

#: The header GitHub puts its signature in.
GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"

#: The header Forgejo puts its signature in.
FORGEJO_SIGNATURE_HEADER = "X-Forgejo-Signature"


def digest(secret: bytes, body: bytes) -> str:
    """The HMAC-SHA256 of ``body`` under ``secret``, as hexadecimal."""
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def github_signature_valid(
    secret: str, body: bytes, header: str | None
) -> bool:
    """Whether ``header`` is GitHub's signature of ``body``. GitHub writes
    the signature as ``sha256=`` followed by the hexadecimal digest.

    The comparison takes the same time whether or not the signatures
    match, so that timing cannot be used to guess a signature.
    """
    if header is None or not header.startswith("sha256="):
        return False
    return hmac.compare_digest(
        f"sha256={digest(secret.encode(), body)}", header
    )


def forgejo_signature_valid(
    secret: str, body: bytes, header: str | None
) -> bool:
    """Whether ``header`` is Forgejo's signature of ``body``. Forgejo
    writes the hexadecimal digest alone, with no prefix."""
    if not header:
        return False
    return hmac.compare_digest(digest(secret.encode(), body), header)
