from pathlib import Path


MARKER_LIMIT = 4 * 1024
WORKTREE_SEGMENT = b"/.git/worktrees/"


def is_linked_worktree(path: Path) -> bool:
    marker = path / ".git"
    try:
        if not marker.is_file():
            return False
        with marker.open("rb") as stream:
            data = stream.read(MARKER_LIMIT)
    except OSError:
        return False
    return data.lstrip().startswith(b"gitdir:") and WORKTREE_SEGMENT in data


def linked_worktree_children(path: Path) -> int:
    try:
        children = path.iterdir()
        return sum(
            1
            for child in children
            if child.is_dir() and is_linked_worktree(child)
        )
    except OSError:
        return 0
