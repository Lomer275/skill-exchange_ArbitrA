import re
from pathlib import Path


ROOT_FILE_KINDS = ("README.md", "architecture", "CHANGELOG", "HANDOFF")


def _files(directory: Path) -> list[Path]:
    try:
        return sorted(
            (path for path in directory.iterdir() if path.is_file()),
            key=lambda path: path.name,
        )
    except OSError:
        return []


def detect_prefix(root: Path) -> str | None:
    suffixes = ("HANDOFF", "CHANGELOG", "architecture")
    for directory in (root, root / "docs"):
        for path in _files(directory):
            for suffix in suffixes:
                match = re.fullmatch(rf"(.+)-{suffix}\.md", path.name)
                if match:
                    return match.group(1)

    docs = root / "docs"
    try:
        candidates = sorted(
            (path for path in docs.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
    except OSError:
        return None
    for path in candidates:
        match = re.fullmatch(r"2\.\s+(.+)-specifications", path.name)
        if match:
            return match.group(1)
    return None


def locate_root_file(
    root: Path, prefix: str | None, kind: str
) -> tuple[str | None, Path | None]:
    if kind not in ROOT_FILE_KINDS:
        raise ValueError(f"unknown root file kind: {kind}")

    for location, directory in (("root", root), ("docs", root / "docs")):
        if kind == "README.md":
            candidate = directory / kind
            if candidate.is_file():
                return location, candidate
            continue

        if prefix is not None:
            candidate = directory / f"{prefix}-{kind}.md"
            if candidate.is_file():
                return location, candidate
            continue

        suffix = f"-{kind}.md"
        for candidate in _files(directory):
            if candidate.name.endswith(suffix):
                return location, candidate
    return None, None
