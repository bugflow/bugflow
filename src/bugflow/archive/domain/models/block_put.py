"""A record that a block was uploaded.

In version 2 of the protocol a client uploads a file's blocks first and
sends the event that refers to them afterwards. If the client stops in
between, the blocks stay stored with no event referring to them.

So every upload is recorded: which ledger, which block, who sent it, how
big it was, and whether the store already had it. The record lets such
leftover blocks be found later and deleted. The protocol allows deleting
them after seven days.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class BlockPut:
    ledger_id: str
    cid: str
    size: int
    caller: str
    #: True if the store did not have this block before this upload.
    #: A block the store already had may belong to another ledger, so
    #: it must not be deleted as a leftover of this upload.
    new: bool
