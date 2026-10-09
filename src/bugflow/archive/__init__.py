"""The archive context: storing and serving sealed archives.

Words used throughout:

- Scope: a directory of a repository that has an archive of its own.
- Archive: files that a scope has sealed, meaning stored for good and
  never changed.
- Ledger: the scope's numbered list of events. It is the record of
  everything the scope has sealed. A ledger has an id, a UUID.
- Event: one entry in a ledger. It is a small JSON file that says which
  files were added, and it names the event before it, so the events
  form a chain.
- CID: a content identifier, a name for some bytes made from a hash of
  them. The same bytes always have the same CID.
- Block: a piece of a file, at most 1 MiB, stored under its CID. A
  large file is stored as several blocks.
- Root: the CID of the whole archive, worked out from all of a ledger's
  events.
- Keeper: a server that stores a ledger's events and the files they
  refer to. This context is a keeper.
- Binding: the record that an operator has registered a ledger with
  this server.

The rules for what a client and a keeper say to each other are the
remote archive protocol, defined in poslib's
``doc/remote-archive-protocol.txt``.
"""
