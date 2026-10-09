"""The inventory of a ledger: the list of files its events refer to, worked
out from the events alone. It does not check that the files' bytes are
actually stored.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

#: The start of a reference to an archived file. A full reference is
#: ``ipfs://{cid}/{path}``.
REFERENCE = "ipfs://"


@dataclass(frozen=True, kw_only=True)
class ArchivedFile:
    path: str
    size: int
    cid: str | None


@dataclass(frozen=True, kw_only=True)
class ArchivedBundle:
    number: int
    item: str
    files: tuple[ArchivedFile, ...]


@dataclass(frozen=True, kw_only=True)
class EnrolledPlace:
    """One place a file appears in a ledger: its path, and the bundle that
    added it. ``bundle`` is None for a file that no bundle added.
    """

    file: ArchivedFile
    bundle: ArchivedBundle | None


@dataclass(frozen=True, kw_only=True)
class ArchiveInventory:
    events: int
    bundles: tuple[ArchivedBundle, ...] = ()
    files: tuple[ArchivedFile, ...]
    #: The CID of every path in the archive, for files and directories
    #: alike. The archive's top level is ".". Empty for an old ledger
    #: whose events do not record CIDs.
    folded: Mapping[str, str] = field(default_factory=dict)

    def enrolled_at(self, reference: str) -> tuple[EnrolledPlace, ...]:
        """Find the files that an ``ipfs://cid/path`` reference points to,
        sorted by path.

        There may be more than one, because the same content can be stored
        under several paths. The result is empty if the ledger has nothing
        there or the text is not a reference.
        """
        if not reference.startswith(REFERENCE):
            return ()
        cid, _, beneath = reference[len(REFERENCE) :].partition("/")
        beneath = beneath.strip("/")
        named = {
            "/".join(part for part in (base, beneath) if part and part != ".")
            for base, folded in self.folded.items()
            if folded == cid
        }
        return tuple(
            EnrolledPlace(
                file=file,
                bundle=next(
                    (
                        bundle
                        for bundle in self.bundles
                        if file in bundle.files
                    ),
                    None,
                ),
            )
            for file in self.files
            if file.path in named
        )
