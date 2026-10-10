"""The text of a doctrine, as a judge reads it and a finding quotes it.

A clause is a paragraph that opens with its id in bold, and its name
when it has one, as ``**RULE-3. Narrating yourself.** Pull request
descriptions ...`` or ``**RULE-2.** State the thing.``, and runs to the
next blank line. A clause of several paragraphs states itself in the
first; the rest are its examples, which a reader of a finding does not
need.
"""

import hashlib
import re
from dataclasses import dataclass

_CLAUSE = r"^\*\*{clause}\.(?:\*\*)? .*?(?=\n\n|\n?\Z)"


@dataclass(frozen=True, kw_only=True)
class Doctrine:
    text: str

    @property
    def version(self) -> str:
        """The first 12 hexadecimal characters of a hash of the text."""
        return hashlib.sha256(self.text.encode()).hexdigest()[:12]

    def clause(self, clause_id: str) -> str | None:
        """The clause's paragraph as it is written, or None if the text
        has no clause of that id.

        A finding cites a clause id, which means nothing to the person
        reading it. The words are the point: they say what the rule is
        and they are the doctrine's, not a judge's paraphrase of them.
        """
        found = re.search(
            _CLAUSE.format(clause=re.escape(clause_id)),
            self.text,
            re.MULTILINE | re.DOTALL,
        )
        return found.group(0) if found else None
