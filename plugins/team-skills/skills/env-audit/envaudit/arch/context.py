from dataclasses import dataclass, field
import os
from pathlib import Path
import re

from envaudit.core.context import Context
from envaudit.core.runner import git
from envaudit.core.walk import EXCLUDED_DIRS, FileEntry, iter_files, read_limited


@dataclass
class TreeView:
    tree_id: str
    mode: str
    path: Path
    sha: str | None
    reason: str


@dataclass
class ArchContext:
    ctx: Context
    root: Path
    vcs: bool
    out: dict
    rule_inputs: dict[str, dict]
    trees: dict[str, TreeView] = field(default_factory=dict)
    cache: dict[str, object] = field(default_factory=dict)

    def _nested_worktrees(self, root: Path) -> tuple[Path, ...]:
        key = f"nested_worktrees:{root}"
        cached = self.cache.get(key)
        if isinstance(cached, tuple):
            return cached

        absolute_root = Path(os.path.abspath(root))
        blocked = set()
        tree = self.out.get("tree", {})
        worktrees = tree.get("worktrees", []) if isinstance(tree, dict) else []
        for worktree in worktrees:
            path = worktree.get("path") if isinstance(worktree, dict) else None
            if not isinstance(path, str):
                continue
            candidate = Path(os.path.abspath(path))
            if candidate != absolute_root and path_inside(candidate, absolute_root):
                blocked.add(candidate)

        def onerror(_error: OSError) -> None:
            return

        for current, dirs, files in os.walk(
            absolute_root, followlinks=False, onerror=onerror
        ):
            current_path = Path(current)
            if current_path in blocked:
                dirs[:] = []
                continue
            if current_path != absolute_root and ".git" in files:
                marker = current_path / ".git"
                try:
                    if marker.is_file():
                        with marker.open(
                            "r", encoding="utf-8", errors="replace"
                        ) as stream:
                            is_worktree = stream.read(256).lstrip().startswith(
                                "gitdir:"
                            )
                    else:
                        is_worktree = False
                except OSError:
                    is_worktree = False
                if is_worktree:
                    blocked.add(current_path)
                    dirs[:] = []
                    continue
            dirs[:] = [
                dirname
                for dirname in dirs
                if dirname not in EXCLUDED_DIRS
                and Path(os.path.abspath(current_path / dirname)) not in blocked
            ]

        result = tuple(sorted(blocked, key=str))
        self.cache[key] = result
        return result

    def files(self, tree_id: str = "primary") -> list[FileEntry]:
        key = f"files:{tree_id}"
        cached = self.cache.get(key)
        if isinstance(cached, list):
            return cached
        view = self.trees.get(tree_id)
        if view is None:
            return []
        exclude_paths = (
            self._nested_worktrees(view.path)
            if tree_id in {"primary", "worktree"}
            else ()
        )
        files = list(
            iter_files(
                view.path,
                self.ctx,
                "architecture",
                exclude_paths=exclude_paths,
            )
        )
        files.sort(key=lambda entry: entry.rel)
        self.cache[key] = files
        return files

    def read(
        self, entry: FileEntry, max_bytes: int | None = None
    ) -> bytes | None:
        limit = (
            self.ctx.flags.max_text_mb * 1024 * 1024
            if max_bytes is None
            else max_bytes
        )
        cached = self.cache.setdefault("read_bytes", {})
        key = str(entry.path)
        if isinstance(cached, dict):
            value = cached.get(key)
            if isinstance(value, bytes):
                return value if len(value) <= limit else None
        value = read_limited(entry, limit)
        if value is not None and isinstance(cached, dict):
            cached[key] = value
        return value

    def code_files(
        self, tree_id: str = "primary", *, exts: frozenset[str]
    ) -> list[FileEntry]:
        normalized = frozenset(
            suffix if suffix.startswith(".") else f".{suffix}" for suffix in exts
        )
        return [
            entry
            for entry in self.files(tree_id)
            if Path(entry.rel).suffix.lower() in normalized
        ]

    def is_prod_path(self, rel: str) -> bool:
        path = rel.replace("\\", "/")
        parts = tuple(part.lower() for part in Path(path).parts)
        if any(
            part in {
                "tests",
                "test",
                "migrations",
                ".venv",
                "venv",
                "node_modules",
                "build",
                "dist",
            }
            for part in parts[:-1]
        ):
            return False
        name = parts[-1] if parts else ""
        return not (
            name == "conftest.py"
            or name.startswith("test_")
            or re.search(r"(?:^|[_.-])test(?:[_.-]|$)", name) is not None
        )

    def blind_spot(self, language: str, share_of_code: float, what: str) -> None:
        self.out["blind_spots"].append(
            {
                "language": language,
                "share_of_code": share_of_code,
                "what": what,
            }
        )

    def skip(
        self, check: str, reason: str, details: str | None = None
    ) -> None:
        suffix = f":{details}" if details else ""
        self.ctx.skip(
            "architecture",
            reason,
            details=f"{self.root}:{check}{suffix}",
        )

    def error(self, check: str, kind: str) -> None:
        self.ctx.error("architecture", f"{check}:{kind}")

    def live_units(self) -> list[dict] | None:
        runtime = self.out.get("runtime")
        if not isinstance(runtime, dict):
            return None
        units = runtime.get("live_units")
        return units if isinstance(units, list) else None

    def churn(self) -> dict[str, tuple[float, int]] | None:
        if "churn" in self.cache:
            cached = self.cache["churn"]
            return cached if isinstance(cached, dict) else None
        if not self.vcs:
            self.cache["churn"] = None
            return None

        tree = self.out.get("tree", {})
        ref = tree.get("head") if isinstance(tree, dict) else None
        if not isinstance(ref, str):
            self.cache["churn"] = None
            return None
        result = git(
            self.root,
            "log",
            "--format=%x00%ct%x00",
            "--name-only",
            "-z",
            ref,
            timeout=600,
        )
        if result.rc != 0:
            self.cache["churn"] = None
            return None

        commits: dict[str, tuple[float, int]] = {}
        current: float | None = None
        for chunk in result.stdout.split(b"\x00"):
            chunk = chunk.strip(b"\r\n")
            if not chunk:
                continue
            if chunk.isdigit():
                current = float(chunk)
                continue
            if current is None:
                continue
            try:
                rel = chunk.decode("utf-8", "surrogateescape")
            except UnicodeDecodeError:
                continue
            previous = commits.get(rel)
            if previous is None:
                commits[rel] = (current, 1)
            else:
                commits[rel] = (max(previous[0], current), previous[1] + 1)
        self.cache["churn"] = commits
        return commits


def path_inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False
