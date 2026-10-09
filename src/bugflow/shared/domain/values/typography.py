"""Find dashes used as punctuation in prose.

Whether a text contains a dash is a fact about its characters. It needs
no judgement, so a function finds it and no model is asked.

Three characters are looked for: the em dash, the en dash and the
horizontal bar. Used to break a sentence they all read the same way. A
hyphen is not looked for, because compound words need it.

Code is left alone. A dash inside a fenced block or between backticks
is part of something quoted, and is not reported.
"""

import re

# The em dash, the en dash and the horizontal bar. They are written as
# escapes so that a tool that looks for these characters does not report
# this file.
EM_DASHES = "\u2014\u2013\u2015"
_DASH = re.compile(f"[{EM_DASHES}]")

# A fenced block, or a span between single backticks.
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)

#: How many characters before a dash and after it are quoted. More are
#: taken after than before, so that two dashes in one sentence give two
#: different quotations. A finding is identified by its quotation, and
#: two findings with the same one could not be told apart.
BEFORE = 12
AFTER = 48


def without_code(text: str) -> str:
    """The text with each piece of code replaced by spaces. The result
    has the same length, so a position in it is the same position in
    the original."""
    return _CODE.sub(lambda m: " " * len(m.group(0)), text)


def em_dashes(text: str) -> tuple[str, ...]:
    """One quotation for each dash outside code, in order.

    A quotation is the dash with the words around it, taken from the
    text as written and with runs of white space made single spaces.
    """
    prose = without_code(text)
    found: list[str] = []
    for match in _DASH.finditer(prose):
        start = max(0, match.start() - BEFORE)
        end = min(len(text), match.end() + AFTER)
        found.append(" ".join(text[start:end].split()))
    return tuple(found)


def has_em_dash(text: str) -> bool:
    """Whether the text has a dash outside code."""
    return bool(em_dashes(text))
