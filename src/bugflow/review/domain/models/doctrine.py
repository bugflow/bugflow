"""The text of a doctrine, and how one clause is found in it.

This context only quotes a doctrine: whole, to a judge, and one clause
at a time, in a comment.

A clause is written as a paragraph that starts with its id in bold and a
full stop, for example::

    **RULE-3.** A commit message says why the change was made.
"""

import hashlib
import re
from dataclasses import dataclass

# A clause's paragraph: from its bold id to the next blank line or the
# end of the text. The bold may close after the full stop or not at all.
_CLAUSE = r"^\*\*{clause}\.(?:\*\*)? .*?(?=\n\n|\n?\Z)"


@dataclass(frozen=True, kw_only=True)
class DoctrineText:
    text: str

    @property
    def version(self) -> str:
        """The first 12 hexadecimal characters of a hash of the text."""
        return hashlib.sha256(self.text.encode()).hexdigest()[:12]

    def clause(self, clause_id: str) -> str | None:
        """The clause's paragraph as it is written, or None if the text
        has no clause of that id."""
        found = re.search(
            _CLAUSE.format(clause=re.escape(clause_id)),
            self.text,
            re.MULTILINE | re.DOTALL,
        )
        return found.group(0) if found else None
