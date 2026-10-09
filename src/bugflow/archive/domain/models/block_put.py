"""A block put to a kept ledger before an event enrols it.

Under version 2 of the remote archive protocol a client puts the blocks
of an item's files first and appends the event alone. A block
put is held whether or not an event ever claims it, so each put is
recorded: which ledger it was put to, by whom, how large, and whether
the store lacked it, so that a block put and never claimed can be found
and, after the protocol's seven days, forgotten.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class BlockPut:
    ledger_id: str
    cid: str
    size: int
    caller: str
    #: Whether the store held no such block before this put. A block
    #: that was held already is some ledger's, and is never forgotten
    #: for want of an event claiming this put.
    new: bool
