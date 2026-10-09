"""Files enrolled by a kept ledger, without checking their storage."""

from collections.abc import Mapping
from dataclasses import dataclass, field

#: How a reference to an archived file begins, as a sealed item's links
#: write it and a search hit's ``ref`` does: ``ipfs://{cid}/{path}``.
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
    """Where a reference's file is enrolled: its path in the ledger and
    the bundle that enrolled it, None for a file no bundle holds."""

    file: ArchivedFile
    bundle: ArchivedBundle | None


@dataclass(frozen=True, kw_only=True)
class ArchiveInventory:
    events: int
    bundles: tuple[ArchivedBundle, ...] = ()
    files: tuple[ArchivedFile, ...]
    #: The CID each enrolled path folds to, files and directories both,
    #: the root as ".". Empty for a ledger whose entries record no CID.
    folded: Mapping[str, str] = field(default_factory=dict)

    def enrolled_at(self, reference: str) -> tuple[EnrolledPlace, ...]:
        """The enrolled files ``reference`` names, in order of path:
        those at its path beneath whatever folds to its CID. More than
        one where the same bytes are enrolled under several paths, none
        where the ledger enrols nothing there or the reference is not
        one."""
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
