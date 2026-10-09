"""Remove from a worktree the files a runner might read as instructions,
and the symbolic links that lead out of it.

Which names count as instructions is decided by
``bugflow.work.domain.values.sandbox.instructs``. This module does the
deleting and returns what it deleted.

Symbolic links need care, because the repository under review chooses
where they point:

- A link is never followed. If a link named ``.claude`` pointed at a
  directory elsewhere on the machine, following it while deleting would
  delete that directory.
- A link whose name counts as an instruction is removed as a link. What
  it points at is not touched.
- A link that points outside the worktree is removed whatever it is
  called. Otherwise a runner could read through it into the rest of the
  machine.
- A link that points inside the worktree is left. Everything it can
  reach has been through the same filter.
"""

import os
import shutil
from pathlib import Path

from bugflow.work.domain.errors import WorktreeError
from bugflow.work.domain.values.sandbox import instructs


def strip_instruction_sources(root: Path) -> tuple[str, ...]:
    """Remove the instruction files and outward links under ``root``.

    Returns the paths removed, relative to ``root`` and sorted. A
    directory whose name counts as an instruction is removed with
    everything in it, and is listed once.

    Raises ``WorktreeError`` if ``root`` is not a directory or is the
    top of a filesystem.
    """
    root = root.resolve()
    if not root.is_dir():
        raise WorktreeError(f"not a directory: {root}")
    if root == Path(root.anchor):
        raise WorktreeError("refusing to strip a filesystem root")

    removed: list[str] = []
    # The walk goes from the top down and does not follow links. A
    # directory that is removed is taken out of ``directories``, so the
    # walk does not try to enter it.
    for current, directories, files in os.walk(root, followlinks=False):
        here = Path(current)
        for name in sorted(directories + files):
            path = here / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                if not (instructs(relative) or _escapes(path, root)):
                    continue
                path.unlink()
            elif instructs(relative):
                if path.is_dir():
                    # rmtree removes links inside as links. It does not
                    # follow them.
                    shutil.rmtree(path)
                else:
                    path.unlink()
            else:
                continue
            removed.append(relative)
            if name in directories:
                directories.remove(name)
    return tuple(sorted(removed))


def _escapes(link: Path, root: Path) -> bool:
    """Whether a link points outside ``root``. The target need not
    exist.

    A link that cannot be resolved, such as one in a loop of links, is
    counted as pointing outside.
    """
    try:
        target = link.resolve()
    except (OSError, RuntimeError):
        return True
    return target != root and root not in target.parents
