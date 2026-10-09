"""Wrap text that somebody else wrote in a tag that the text cannot
close.

Text from a pull request is given to a model inside a tag, such as
``<description>``. The tag is what separates the instructions from the
text under review. If the text contained ``</description>``, the block
would end early, and whatever came after would sit where instructions
go.

So every closing tag inside the text is broken by putting a backslash
after its ``<``. No real closing tag has one, and the block ends only
where this module ends it. The text is not read or judged to do this.
"""

import re


def closing_escaped(text: str, *tags: str) -> str:
    """The text with every closing form of these tags broken.

    A closing tag is matched in any letter case and with spaces inside
    it, such as ``</ Review >``, because a model may read that as an
    ending too. Text that will sit inside several tags is given all of
    them.
    """
    for tag in tags:
        closing = re.compile(rf"</\s*{re.escape(tag)}\s*>", re.IGNORECASE)
        text = closing.sub(lambda match: "<\\" + match.group(0)[1:], text)
    return text


def delimit(tag: str, text: str, attributes: str = "") -> str:
    """The text inside the tag, with the tag's closing form broken
    wherever the text contains it.

    ``attributes`` are put in the opening tag as given. They come from
    the caller, never from the text under review.
    """
    safe = closing_escaped(text, tag)
    opening = f"<{tag} {attributes}>" if attributes else f"<{tag}>"
    return f"{opening}\n{safe}\n</{tag}>"
