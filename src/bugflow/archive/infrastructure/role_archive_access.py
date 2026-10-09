"""Access to archives decided by two roles.

A caller with the reader role may read every ledger stored here. A caller
with the writer role may append to every ledger, and read it too, since a
client has to ask what is stored before it sends.

The roles come from the identity provider, in the caller's token. Taking a
role away there ends the person's access.

This does not give access ledger by ledger: a role covers all of them.

The names of the two roles are passed in. They belong to whoever runs the
server, because each identity provider names its own roles.
"""

from dataclasses import dataclass

from bugflow.shared.domain.values.caller import Caller


@dataclass(frozen=True)
class RoleArchiveAccess:
    #: The name of the role that may read every ledger, and the name of the
    #: role that may also append, as they appear in a token.
    reader: str
    writer: str

    def may_read(self, caller: Caller, ledger_id: str) -> bool:
        return bool({self.reader, self.writer} & caller.roles)

    def may_append(self, caller: Caller, ledger_id: str) -> bool:
        return self.writer in caller.roles
