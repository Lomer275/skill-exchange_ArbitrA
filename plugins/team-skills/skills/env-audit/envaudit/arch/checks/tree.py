from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import re
import tarfile
import tempfile

from envaudit.arch.context import ArchContext, TreeView
from envaudit.core.runner import git


KEY = "tree"
ORDER = 10
CODE_GLOBS = ("*.py", "*.php", "*.js", "*.ts", "*.cs")


def _decoded(data: bytes) -> str:
    return data.decode("utf-8", "surrogateescape").strip()


def _git_value(actx: ArchContext, *args: str, timeout: float = 30) -> str | None:
    result = git(actx.root, *args, timeout=timeout)
    if result.rc != 0:
        return None
    value = _decoded(result.stdout)
    return value or None


def _timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromtimestamp(int(value), timezone.utc)
    except (ValueError, OverflowError):
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _first_commit_timestamp(actx: ArchContext) -> str | None:
    roots = _git_value(actx, "rev-list", "--max-parents=0", "HEAD")
    if roots is None:
        return None
    first_sha = roots.splitlines()[0] if roots.splitlines() else None
    return _git_value(actx, "show", "-s", "--format=%ct", first_sha) if first_sha else None


def _default_branch(actx: ArchContext, current: str | None) -> str | None:
    symbolic = _git_value(
        actx, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"
    )
    if symbolic and symbolic.startswith("origin/"):
        return symbolic.split("/", 1)[1]
    for candidate in ("main", "master"):
        if _git_value(
            actx,
            "show-ref",
            "--verify",
            "--hash",
            f"refs/remotes/origin/{candidate}",
        ) or _git_value(
            actx, "show-ref", "--verify", "--hash", f"refs/heads/{candidate}"
        ):
            return candidate
    return current


def _remote_heads(
    actx: ArchContext, default: str | None, current: str | None
) -> tuple[bool, dict[str, str | None]]:
    names = []
    for name in (default, current):
        if name and name not in names:
            names.append(name)
    if not names:
        return False, {"default": None, "current": None}
    result = git(actx.root, "ls-remote", "origin", *names, timeout=20)
    if result.rc != 0:
        return False, {"default": None, "current": None}
    by_name = {}
    for line in result.stdout.splitlines():
        fields = line.split(b"\t", 1)
        if len(fields) != 2:
            continue
        ref = fields[1].decode("utf-8", "replace")
        by_name[ref.rsplit("/", 1)[-1]] = fields[0].decode("ascii", "replace")
    return True, {
        "default": by_name.get(default or ""),
        "current": by_name.get(current or ""),
    }


def _ahead_behind(actx: ArchContext) -> tuple[int | None, int | None]:
    value = _git_value(
        actx, "rev-list", "--left-right", "--count", "HEAD...@{u}"
    )
    if value is None:
        return None, None
    fields = value.split()
    try:
        return int(fields[0]), int(fields[1])
    except (IndexError, ValueError):
        return None, None


def _numstat(actx: ArchContext, *, ignore_crlf: bool) -> dict[str, tuple[int, int]]:
    args = ["diff", "--no-textconv", "--no-ext-diff", "--numstat"]
    if ignore_crlf:
        args.append("--ignore-cr-at-eol")
    args.append("HEAD")
    result = git(actx.root, *args, timeout=120)
    if result.rc != 0:
        return {}
    values = {}
    for line in result.stdout.splitlines():
        fields = line.split(b"\t", 2)
        if len(fields) != 3:
            continue
        try:
            added = int(fields[0]) if fields[0] != b"-" else 0
            deleted = int(fields[1]) if fields[1] != b"-" else 0
        except ValueError:
            continue
        values[fields[2].decode("utf-8", "surrogateescape")] = (added, deleted)
    return values


def _line_count(path: Path) -> int:
    try:
        size = path.stat().st_size
        if size > 20 * 1024 * 1024 or path.is_symlink():
            return 0
        count = 0
        last = b""
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                count += chunk.count(b"\n")
                last = chunk[-1:]
        return count + (1 if size and last != b"\n" else 0)
    except OSError:
        return 0


def _dirty(actx: ArchContext) -> dict:
    status = git(
        actx.root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        timeout=120,
    )
    modified = []
    untracked = []
    if status.rc == 0:
        records = status.stdout.split(b"\x00")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if len(record) < 4:
                continue
            code = record[:2]
            rel = record[3:].decode("utf-8", "surrogateescape")
            if code == b"??":
                untracked.append(rel)
            else:
                modified.append(rel)
            if b"R" in code or b"C" in code:
                index += 1

    regular = _numstat(actx, ignore_crlf=False)
    normalized = _numstat(actx, ignore_crlf=True)
    crlf_only = sum(
        1
        for path, counts in regular.items()
        if sum(counts) > 0 and sum(normalized.get(path, (0, 0))) == 0
    )
    return {
        "modified_files": len(modified),
        "lines_add": sum(value[0] for value in normalized.values()),
        "lines_del": sum(value[1] for value in normalized.values()),
        "crlf_only_files": crlf_only,
        "untracked_files": len(untracked),
        "untracked_lines": sum(_line_count(actx.root / rel) for rel in untracked),
    }


def _code_lines(actx: ArchContext, sha: str | None) -> int | None:
    if sha is None:
        return None
    result = git(
        actx.root,
        "grep",
        "-c",
        "-I",
        "",
        sha,
        "--",
        *CODE_GLOBS,
        timeout=120,
    )
    if result.rc not in (0, 1):
        return None
    total = 0
    for line in result.stdout.splitlines():
        try:
            total += int(line.rsplit(b":", 1)[1])
        except (IndexError, ValueError):
            continue
    return total


def _branch_facts(
    actx: ArchContext,
    name: str | None,
    sha: str | None,
    last_commit: str | None,
    default_ref: str | None,
    default_lines: int | None,
) -> dict:
    remote_contains = (
        git(actx.root, "branch", "-r", "--contains", sha).stdout.strip()
        if sha
        else b""
    )
    merged = None
    if sha and default_ref:
        merged = (
            git(actx.root, "merge-base", "--is-ancestor", sha, default_ref).rc
            == 0
        )
    code_lines = _code_lines(actx, sha)
    delta = None
    if code_lines is not None and default_lines not in (None, 0):
        delta = round((code_lines - default_lines) * 100.0 / default_lines, 3)
    return {
        "name": name,
        "head": sha,
        "local_only": not bool(remote_contains),
        "merged": merged,
        "code_lines": code_lines,
        "delta_pct_vs_default": delta,
        "last_commit_at": _timestamp(last_commit),
    }


def _local_branches(
    actx: ArchContext, default_ref: str | None, default_lines: int | None
) -> list[dict]:
    result = git(
        actx.root,
        "for-each-ref",
        "refs/heads",
        "--format=%(refname:short)%00%(objectname)%00%(committerdate:unix)",
    )
    if result.rc != 0:
        return []
    branches = []
    for line in result.stdout.splitlines():
        fields = line.split(b"\x00")
        if len(fields) != 3:
            continue
        branches.append(
            _branch_facts(
                actx,
                fields[0].decode("utf-8", "surrogateescape"),
                fields[1].decode("ascii", "replace"),
                fields[2].decode("ascii", "replace"),
                default_ref,
                default_lines,
            )
        )
    return sorted(branches, key=lambda item: item["name"] or "")


def _worktrees(
    actx: ArchContext, default_ref: str | None, default_lines: int | None
) -> list[dict]:
    result = git(actx.root, "worktree", "list", "--porcelain")
    if result.rc != 0:
        return []
    output = []
    for block in result.stdout.split(b"\n\n"):
        values = {}
        for line in block.splitlines():
            key, _, value = line.partition(b" ")
            values[key.decode("ascii", "replace")] = value.decode(
                "utf-8", "surrogateescape"
            )
        path = values.get("worktree")
        sha = values.get("HEAD")
        if not path or not sha:
            continue
        branch = values.get("branch", "").removeprefix("refs/heads/") or None
        facts = _branch_facts(
            actx,
            branch,
            sha,
            _git_value(actx, "show", "-s", "--format=%ct", sha),
            default_ref,
            default_lines,
        )
        facts["path"] = path
        facts.pop("name", None)
        output.append(facts)
    return sorted(output, key=lambda item: item["path"])


def _empty_tree(reason: str) -> dict:
    return {
        "vcs": {"present": False, "reason": reason},
        "head": None,
        "branch": None,
        "default_branch": None,
        "origin_default_sha": None,
        "ls_remote_ok": None,
        "ls_remote": None,
        "origin_ref_stale": None,
        "ahead": None,
        "behind": None,
        "ahead_verified": None,
        "dirty": {
            "modified_files": None,
            "lines_add": None,
            "lines_del": None,
            "crlf_only_files": None,
            "untracked_files": None,
            "untracked_lines": None,
        },
        "worktrees": [],
        "local_branches": [],
        "repo_first_commit_at": None,
        "repo_last_commit_at": None,
        "analysed": [],
        "source_roots": [],
    }


def run(actx: ArchContext) -> None:
    actx.trees["worktree"] = TreeView(
        "worktree", "worktree" if actx.vcs else "filesystem", actx.root, None, ""
    )
    if not actx.vcs:
        reason = "stub_git_dir" if (actx.root / ".git").is_dir() else "absent"
        actx.out[KEY] = _empty_tree(reason)
        actx.skip(KEY, "no_vcs")
        return

    head = _git_value(actx, "rev-parse", "HEAD")
    branch = _git_value(actx, "symbolic-ref", "--quiet", "--short", "HEAD")
    default = _default_branch(actx, branch)
    default_ref = f"refs/remotes/origin/{default}" if default else None
    tracking_sha = (
        _git_value(actx, "rev-parse", default_ref) if default_ref else None
    )
    ls_remote_ok, remote = _remote_heads(actx, default, branch)
    ahead, behind = _ahead_behind(actx)
    dirty = _dirty(actx)
    default_lines = _code_lines(actx, tracking_sha or head)
    actx.out[KEY] = {
        "vcs": {"present": True, "reason": None},
        "head": head,
        "branch": branch,
        "default_branch": default,
        "origin_default_sha": tracking_sha,
        "ls_remote_ok": ls_remote_ok,
        "ls_remote": remote,
        "origin_ref_stale": bool(
            ls_remote_ok
            and remote.get("default")
            and tracking_sha
            and remote["default"] != tracking_sha
        ),
        "ahead": ahead,
        "behind": behind,
        "ahead_verified": bool(
            ls_remote_ok
            and tracking_sha
            and remote.get("default") == tracking_sha
        ),
        "dirty": dirty,
        "worktrees": _worktrees(actx, default_ref, default_lines),
        "local_branches": _local_branches(actx, default_ref, default_lines),
        "repo_first_commit_at": _timestamp(
            _first_commit_timestamp(actx)
        ),
        "repo_last_commit_at": _timestamp(
            _git_value(actx, "log", "-1", "--format=%ct", "HEAD")
        ),
        "analysed": [],
        "source_roots": [],
    }
    actx.trees["worktree"].sha = head


def _archive(actx: ArchContext, sha: str, tree_id: str, reason: str) -> TreeView | None:
    result = git(actx.root, "archive", "--format=tar", sha, timeout=180)
    if result.rc != 0:
        actx.error(KEY, "archive_failed")
        return None
    temp_path = Path(tempfile.mkdtemp(prefix="env-audit-"))
    paths = actx.cache.setdefault("temporary_paths", [])
    if isinstance(paths, list):
        paths.append(temp_path)
    try:
        with tarfile.open(fileobj=BytesIO(result.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                target = Path(os.path.abspath(temp_path / member.name))
                if os.path.commonpath((str(target), str(temp_path))) != str(temp_path):
                    raise ValueError("unsafe_archive_path")
            archive.extractall(temp_path)
    except (tarfile.TarError, OSError, ValueError):
        actx.error(KEY, "archive_extract_failed")
        return None
    return TreeView(tree_id, "archive", temp_path, sha, reason)


def _source_roots(actx: ArchContext) -> list[dict]:
    manifest_languages = {
        "pyproject.toml": "python",
        "setup.py": "python",
        "manage.py": "python",
        "composer.json": "php",
        "package.json": "js_ts",
    }
    roots: dict[tuple[str, str], dict] = {}
    for entry in actx.files():
        name = Path(entry.rel).name
        language = manifest_languages.get(name)
        if language is None and name.startswith("requirements") and name.endswith(".txt"):
            language = "python"
        if language is None and name.endswith(".csproj"):
            language = "csharp"
        if language:
            parent = Path(entry.rel).parent.as_posix()
            parent = "." if parent == "." else parent
            roots[(parent, language)] = {
                "path": parent,
                "language": language,
                "found_by": name,
            }

    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    anchored_languages = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        entry = anchor.get("entry")
        if not isinstance(entry, str):
            continue
        suffix = Path(entry).suffix.lower()
        language = {
            ".py": "python",
            ".php": "php",
            ".js": "js_ts",
            ".ts": "js_ts",
            ".cs": "csharp",
            ".sh": "shell",
        }.get(suffix)
        if language:
            anchored_languages.add(language)
            parent = Path(entry).parent.as_posix()
            parent = "." if parent == "." else parent
            roots[(parent, language)] = {
                "path": parent,
                "language": language,
                "found_by": "runtime_anchor",
            }

    suffixes = {
        "python": frozenset({".py"}),
        "php": frozenset({".php"}),
        "js_ts": frozenset({".js", ".ts", ".jsx", ".tsx"}),
        "csharp": frozenset({".cs"}),
        "shell": frozenset({".sh"}),
    }
    for language in anchored_languages:
        if not actx.code_files(exts=suffixes[language]):
            actx.error(KEY, f"no_files_for_anchored_language:{language}")
    return sorted(roots.values(), key=lambda item: (item["path"], item["language"]))


def refresh_source_roots(actx: ArchContext) -> None:
    tree = actx.out.get(KEY)
    if isinstance(tree, dict) and "primary" in actx.trees:
        tree["source_roots"] = _source_roots(actx)


def finalize_tree(actx: ArchContext) -> None:
    tree = actx.out.get(KEY)
    if not isinstance(tree, dict):
        return
    live = any(
        unit.get("intersects_root") is True
        for unit in (actx.live_units() or [])
        if isinstance(unit, dict)
    )
    if not actx.vcs:
        primary = TreeView(
            "primary", "filesystem", actx.root, None, "1.2:no_vcs"
        )
    elif live:
        primary = TreeView(
            "primary", "worktree", actx.root, tree.get("head"), "1.2:live_unit"
        )
    else:
        dirty = tree.get("dirty", {})
        is_dirty = isinstance(dirty, dict) and (
            (dirty.get("modified_files") or 0)
            - (dirty.get("crlf_only_files") or 0)
            > 0
            or (dirty.get("untracked_files") or 0) > 0
        )
        if (tree.get("behind") or 0) > 0 or is_dirty:
            sha = tree.get("origin_default_sha")
            archived = (
                _archive(actx, sha, "primary", "1.2:behind_or_dirty")
                if isinstance(sha, str)
                else None
            )
            primary = archived or TreeView(
                "primary",
                "worktree",
                actx.root,
                tree.get("head"),
                "1.2:behind_or_dirty",
            )
        else:
            primary = TreeView(
                "primary", "worktree", actx.root, tree.get("head"), "1.2:clean"
            )
    actx.trees["primary"] = primary

    analysed = [
        {
            "tree_id": primary.tree_id,
            "mode": primary.mode,
            "sha": primary.sha,
            "reason": primary.reason,
        }
    ]
    if actx.vcs:
        head_lines = _code_lines(actx, tree.get("head")) or 0
        candidates = []
        for branch in tree.get("local_branches", []):
            if (
                branch.get("local_only") is True
                and (branch.get("code_lines") or 0) > head_lines * 1.2
            ):
                candidates.append(branch)
        for worktree in tree.get("worktrees", []):
            if (
                worktree.get("local_only") is True
                and (worktree.get("code_lines") or 0) > head_lines * 1.2
            ):
                candidates.append(worktree)
        if candidates:
            candidate = max(candidates, key=lambda item: item.get("code_lines") or 0)
            sha = candidate.get("head")
            if isinstance(sha, str):
                alt = _archive(actx, sha, "alt", "1.2:local_branch_plus20")
                if alt is not None:
                    actx.trees["alt"] = alt
                    analysed.append(
                        {
                            "tree_id": alt.tree_id,
                            "mode": alt.mode,
                            "sha": alt.sha,
                            "reason": alt.reason,
                        }
                    )
    tree["analysed"] = analysed
    refresh_source_roots(actx)
