"""Archive access by two roles at the identity provider.

The first answer to the archive access port: a caller holding the
reading role may read every ledger kept here, and one holding the
writing role may append to every one, and read it, since a client that
seals has to ask what is kept before it sends. The identity provider
carries roles and knows nothing about content, so revoking a role there
ends a person's access whatever a repository says. It does not say
which ledgers a person may reach: a holder reaches every one.

Which two roles is a deployment's answer: the provider it signs people
in at names its roles, so this is given them and holds no name itself.
"""

from dataclasses import dataclass

from bugflow.shared.domain.values.caller import Caller


@dataclass(frozen=True)
class RoleArchiveAccess:
    #: The role that reads every ledger kept, and the role that appends
    #: to every one, as the provider's tokens carry them.
    reader: str
    writer: str

    def may_read(self, caller: Caller, ledger_id: str) -> bool:
        return bool({self.reader, self.writer} & caller.roles)

    def may_append(self, caller: Caller, ledger_id: str) -> bool:
        return self.writer in caller.roles
