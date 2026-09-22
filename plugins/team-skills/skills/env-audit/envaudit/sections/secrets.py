import csv
from collections import Counter as ByteCounter
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import tarfile
import time
import zipfile

from envaudit.core import patterns, worktrees
from envaudit.core.context import Context
from envaudit.core.controls import positive_control
from envaudit.core.dockerignore import load_matcher
from envaudit.core.runner import (
    GIT_ENV,
    GIT_SAFE_CONFIG,
    git,
    git_stream,
    is_git_repo,
    run,
)
from envaudit.core.walk import EXCLUDED_DIRS, FileEntry, audit_backup_dirs, iter_files
from envaudit.secrets.external import collect_external_access
from envaudit.secrets.pii import FIO_KEYS, FIO_RE, INN_KEYS, scan_json_bytes, valid_inn12
from envaudit.secrets.scan import Counter, _scan_bytes_many, is_fixture_path, scan_bytes
from envaudit.secrets.sshkeys import key_info


NAME = "secrets"
ORDER = 60
GENERIC_ASSIGNMENT_SCOPE = (
    "context_files",
    "agent_configs",
    "shell_history",
    "config_dir",
)
ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".zip")
HOME_EXCLUDED_DIRS = EXCLUDED_DIRS | frozenset(
    {".cache", ".npm", ".nvm", ".vscode-server", ".cursor-server"}
)
HOME_PRIORITY_DIRS = (
    ".claude",
    ".codex",
    ".secrets",
    ".ssh",
    ".config",
    "Desktop",
    "Downloads",
    "Documents",
    "Tools",
)
AGENT_HISTORY_WINDOW_DAYS = 30
AGENT_HISTORY_MAX_BYTES = 2 * 1024 * 1024 * 1024
AGENT_HISTORY_CHUNK_BYTES = 1024 * 1024
AGENT_HISTORY_OVERLAP_BYTES = 64 * 1024
SECRET_DIR_NAME_RE = re.compile(r"secret|env|cred|key|token", re.IGNORECASE)
COPY_ALL_RE = re.compile(
    rb"(?im)^\s*(?:COPY|ADD)\s+(?:--[^\s]+\s+)*\.\s+\.\s*$"
)
CYRILLIC_INN_MARKERS = tuple(
    value.encode("utf-8")
    for value in ("ИНН", "ИНн", "ИнН", "Инн", "иНН", "иНн", "инН", "инн")
)


def _control_value(user_id: int = 1) -> bytes:
    prefix = b"/" + b"rest" + b"/" + str(user_id).encode("ascii") + b"/"
    return prefix + b"k9m2n5p8q4r7s3t6"


def _mode(path: Path) -> str | None:
    try:
        return f"{stat.S_IMODE(path.stat().st_mode):04o}"
    except OSError:
        return None


def _display_home(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _git_command(repo: Path, *args: str, input_bytes: bytes | None = None):
    return run(
        ["git", *GIT_SAFE_CONFIG, "-C", str(repo), *args],
        timeout=60,
        env_extra=GIT_ENV,
        input_bytes=input_bytes,
    )


def _git_commit(repo: Path, message: str) -> bool:
    result = _git_command(
        repo,
        "-c",
        "user.name=a",
        "-c",
        "user.email=a@a",
        "commit",
        "-q",
        "-m",
        message,
    )
    return result.rc == 0


def _parse_batch(stdout: bytes, count: int) -> list[bytes | None]:
    blobs: list[bytes | None] = []
    offset = 0
    while offset < len(stdout) and len(blobs) < count:
        newline = stdout.find(b"\n", offset)
        if newline < 0:
            break
        header = stdout[offset:newline]
        offset = newline + 1
        fields = header.split()
        if len(fields) < 3 or fields[1] != b"blob":
            blobs.append(None)
            continue
        try:
            size = int(fields[2])
        except ValueError:
            blobs.append(None)
            continue
        blobs.append(stdout[offset : offset + size])
        offset += size
        if offset < len(stdout) and stdout[offset : offset + 1] == b"\n":
            offset += 1
    blobs.extend([None] * (count - len(blobs)))
    return blobs


def _git_head_counter(
    repo: Path,
    max_bytes: int,
    text_bytes: int | None = None,
    ctx: Context | None = None,
) -> Counter:
    counter = Counter()
    listing = git(repo, "ls-tree", "-r", "-z", "HEAD", timeout=60)
    if listing.rc != 0:
        return counter
    objects: list[tuple[bytes, str]] = []
    for record in listing.stdout.split(bytes((0,))):
        if not record or b"\t" not in record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        fields = metadata.split()
        if len(fields) == 3 and fields[1] == b"blob":
            objects.append((fields[2], raw_path.decode("utf-8", "replace")))
    check = _git_command(
        repo,
        "cat-file",
        "--batch-check",
        input_bytes=b"\n".join(oid for oid, _ in objects) + b"\n",
    )
    sizes: list[int | None] = []
    if check.rc == 0:
        for line in check.stdout.splitlines():
            fields = line.split()
            try:
                sizes.append(int(fields[2]) if len(fields) >= 3 and fields[1] == b"blob" else None)
            except ValueError:
                sizes.append(None)
    sizes.extend([None] * (len(objects) - len(sizes)))
    eligible = [item for item, size in zip(objects, sizes) if size is not None and size <= max_bytes]
    for offset in range(0, len(eligible), 500):
        if ctx is not None and ctx.expired():
            ctx.mark_truncated()
            break
        batch = eligible[offset : offset + 500]
        result = _git_command(
            repo,
            "cat-file",
            "--batch",
            input_bytes=b"\n".join(oid for oid, _ in batch) + b"\n",
        )
        if result.rc != 0:
            continue
        for (_, rel), blob in zip(batch, _parse_batch(result.stdout, len(batch))):
            if blob is None or len(blob) > max_bytes:
                continue
            if text_bytes is not None and len(blob) > text_bytes:
                window = 256 * 1024
                middle = max(0, len(blob) // 2 - window // 2)
                blob = blob[:window] + b"\n" + blob[middle : middle + window] + b"\n" + blob[-window:]
            scan_bytes(
                blob,
                counter,
                path_rel=rel,
                is_fixture=is_fixture_path(rel),
                include_generic=False,
            )
    return counter


def _git_history_counter(repo: Path, ctx: Context | None = None) -> Counter:
    counter = Counter()
    commit = "unknown"
    for line in git_stream(
        repo,
        "log",
        "--all",
        "-p",
        "--no-textconv",
        "--no-ext-diff",
        "--format=%x00%H",
        timeout=600,
    ):
        if ctx is not None and ctx.expired():
            ctx.mark_truncated()
            break
        if line.startswith(bytes((0,))):
            commit = line[1:].strip().decode("ascii", "replace")
            continue
        if not line.startswith((b"+", b"-")) or line.startswith((b"+++", b"---")):
            continue
        scan_bytes(
            line[1:],
            counter,
            path_rel=commit,
            is_fixture=False,
            include_generic=False,
        )
    return counter


def _read_for_scan(
    entry: FileEntry,
    ctx: Context,
    counters: dict[str, int],
    *,
    with_digest: bool = False,
) -> tuple[bytes | None, bytes | None]:
    text_limit = ctx.flags.max_text_mb * 1024 * 1024
    hash_limit = ctx.flags.max_hash_mb * 1024 * 1024
    if entry.is_symlink:
        return None, None
    if entry.size <= text_limit:
        try:
            data = entry.path.read_bytes()
        except OSError:
            ctx.skip(NAME, "permission", details=entry.rel)
            return None, None
        digest = hashlib.sha256(data).digest() if with_digest else None
        return data, digest
    if entry.size > hash_limit:
        counters["size_cap_files"] += 1
        return None, None
    window = 256 * 1024
    try:
        if with_digest:
            starts = (
                0,
                max(0, entry.size // 2 - window // 2),
                max(0, entry.size - window),
            )
            chunks: list[list[bytes]] = [[], [], []]
            digest = hashlib.sha256()
            offset = 0
            with entry.path.open("rb") as stream:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                    block_end = offset + len(block)
                    for index, start in enumerate(starts):
                        end = min(entry.size, start + window)
                        left = max(offset, start)
                        right = min(block_end, end)
                        if left < right:
                            chunks[index].append(block[left - offset : right - offset])
                    offset = block_end
            data = b"\n".join(b"".join(parts) for parts in chunks)
            counters["windowed_files"] += 1
            return data, digest.digest()
        with entry.path.open("rb") as stream:
            first = stream.read(window)
            stream.seek(max(0, entry.size // 2 - window // 2))
            middle = stream.read(window)
            stream.seek(max(0, entry.size - window))
            last = stream.read(window)
    except OSError:
        ctx.skip(NAME, "permission", details=entry.rel)
        return None, None
    counters["windowed_files"] += 1
    return first + b"\n" + middle + b"\n" + last, None


def _tracked_files(root: Path) -> set[str]:
    result = git(root, "ls-files", "-z", timeout=60)
    if result.rc != 0:
        return set()
    return {
        item.decode("utf-8", "replace")
        for item in result.stdout.split(bytes((0,)))
        if item
    }


def _untracked_files(root: Path) -> set[str]:
    result = git(root, "ls-files", "-z", "--others", "--exclude-standard", timeout=60)
    if result.rc != 0:
        return set()
    return {
        item.decode("utf-8", "replace")
        for item in result.stdout.split(bytes((0,)))
        if item
    }


def _ignored_files(root: Path, rels: list[str]) -> set[str]:
    if not rels:
        return set()
    payload = bytes((0,)).join(item.encode("utf-8") for item in rels) + bytes((0,))
    result = _git_command(
        root,
        "check-ignore",
        "--stdin",
        "-z",
        "-v",
        "-n",
        input_bytes=payload,
    )
    if result.rc not in (0, 1):
        return set()
    fields = result.stdout.split(bytes((0,)))
    ignored = set()
    for offset in range(0, len(fields) - 3, 4):
        _source, _line, pattern, raw_path = fields[offset : offset + 4]
        if pattern and raw_path:
            ignored.add(raw_path.decode("utf-8", "replace"))
    return ignored


def _is_env_like(rel: str) -> bool:
    name = Path(rel).name
    folded = name.casefold()
    if folded.startswith(".env") or folded.endswith(".env"):
        return True
    if ".env.bak" in folded or folded.startswith("config.env"):
        return True
    if folded == ".servers" or folded.endswith((".pem", ".key")):
        return True
    path = Path(name)
    stem = path.stem.casefold()
    document = path.suffix.casefold() in {".md", ".txt", ".doc", ".docx", ".odt"}
    no_extension = not path.suffix
    return stem.endswith("_key") and (name.startswith(".") or document or no_extension)


def _entropy(value: bytes) -> float:
    if not value:
        return 0.0
    counts = ByteCounter(value)
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def _value_classes(data: bytes) -> list[str]:
    classes = set()
    for match in patterns.find(data, self_check_only=True):
        value = data[match.start : match.end]
        if not patterns.is_fake(value):
            classes.add(match.cls)
    for line in data.splitlines():
        if b"=" not in line and b":" not in line:
            continue
        _key, value = re.split(rb"[=:]", line, maxsplit=1)
        candidate = value.strip().strip(b"\"'")
        if len(candidate) >= 20 and not patterns.is_fake(candidate) and _entropy(candidate) >= 3.5:
            classes.add("long_high_entropy")
    return sorted(classes)


def _scan_csv_bytes(data: bytes) -> tuple[int, int]:
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
    except UnicodeError:
        return 0, 0
    inn_records = 0
    fio_records = 0
    try:
        for row in reader:
            has_inn = any(
                str(key).casefold() in INN_KEYS and valid_inn12(str(value or ""))
                for key, value in row.items()
            )
            has_fio = any(
                str(key).casefold() in FIO_KEYS
                and isinstance(value, str)
                and FIO_RE.fullmatch(value.strip()) is not None
                for key, value in row.items()
            )
            inn_records += int(has_inn)
            fio_records += int(has_fio)
    except csv.Error:
        return 0, 0
    return inn_records, fio_records


def _has_inn_marker(data: bytes) -> bool:
    return b"inn" in data.lower() or any(
        marker in data for marker in CYRILLIC_INN_MARKERS
    )


def _directory_info(path: Path, home: Path | None = None) -> dict | None:
    if not path.is_dir():
        return None
    files = 0
    wider = 0
    if not path.is_symlink():
        for current, _dirs, names in os.walk(path, followlinks=False):
            for name in names:
                item = Path(current) / name
                if item.is_symlink():
                    continue
                files += 1
                try:
                    wider += int(bool(stat.S_IMODE(item.stat().st_mode) & 0o077))
                except OSError:
                    continue
    shown = _display_home(path, home) if home is not None else path.name
    return {"path": shown, "mode": _mode(path), "files": files, "files_wider_than_600": wider}


def _archive_members(path: Path) -> int | None:
    try:
        if path.name.casefold().endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
        else:
            with tarfile.open(path, mode="r:*") as archive:
                names = archive.getnames()
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        return None
    return sum(1 for name in names if _is_env_like(name))


def _empty_source() -> dict[str, dict]:
    return Counter().as_dict()


def _root_patterns(
    head: Counter | None,
    history: Counter | None,
    worktree: Counter,
    outside: Counter,
) -> dict[str, dict]:
    head_view = head.as_dict() if head is not None else _empty_source()
    history_view = history.as_dict() if history is not None else _empty_source()
    work_view = worktree.as_dict()
    outside_view = outside.as_dict()
    result = {}
    for item in patterns.CLASSES:
        cls = item.name
        if cls == "generic_assignment":
            continue
        paths = []
        for source in (head_view, work_view):
            for path in source[cls]["paths_sample"]:
                if path not in paths and len(paths) < 10:
                    paths.append(path)
        result[cls] = {
            "head_files": head_view[cls]["files"] if head is not None else None,
            "head_distinct": head_view[cls]["distinct"] if head is not None else None,
            "history_commits": history_view[cls]["files"] if history is not None else None,
            "history_distinct": history_view[cls]["distinct"] if history is not None else None,
            "worktree_files": work_view[cls]["files"],
            "distinct": len(
                set().union(
                    head._values[cls] if head is not None else set(),
                    history._values[cls] if history is not None else set(),
                    worktree._values[cls],
                )
            ),
            "outside_secrets_dir_files": outside_view[cls]["files"],
            "test_fixture_files": head_view[cls]["test_fixture_files"]
            + work_view[cls]["test_fixture_files"],
            "fake_filtered": head_view[cls]["fake_filtered"]
            + history_view[cls]["fake_filtered"]
            + work_view[cls]["fake_filtered"],
            "user_ids": sorted(
                set(head_view[cls]["user_ids"])
                | set(history_view[cls]["user_ids"])
                | set(work_view[cls]["user_ids"])
            ),
            "paths_sample": paths,
        }
    return result


def _scan_root(root: Path, ctx: Context, vcs: bool) -> dict:
    entries = sorted(iter_files(root, ctx, NAME), key=lambda entry: entry.rel)
    entry_by_rel = {entry.rel: entry for entry in entries}
    tracked = _tracked_files(root) if vcs else set()
    untracked = _untracked_files(root) if vcs else set(entry_by_rel)
    env_rels = sorted(rel for rel in entry_by_rel if _is_env_like(rel))
    ignored = _ignored_files(root, env_rels) if vcs else set()
    worktree = Counter()
    outside = Counter()
    disk = Counter()
    counters = {"windowed_files": 0, "size_cap_files": 0}
    data_by_env: dict[str, bytes] = {}
    digest_by_env: dict[str, bytes] = {}
    docker_data: dict[str, bytes] = {}
    ci_chunks: list[bytes] = []
    matched_disk_paths: set[str] = set()
    pii_files = []

    for entry in entries:
        if ctx.expired():
            ctx.mark_truncated()
            break
        data, digest = _read_for_scan(
            entry,
            ctx,
            counters,
            with_digest=entry.rel in env_rels,
        )
        if data is None:
            continue
        targets = [disk]
        if entry.rel in untracked:
            targets.append(worktree)
        if not vcs and not entry.rel.startswith(".secrets/"):
            targets.append(outside)
        if _scan_bytes_many(
            data,
            tuple(targets),
            path_rel=entry.rel,
            is_fixture=is_fixture_path(entry.rel),
            include_generic=False,
        ):
            matched_disk_paths.add(entry.rel)
        if entry.rel in env_rels:
            data_by_env[entry.rel] = data
            if digest is not None:
                digest_by_env[entry.rel] = digest
        if (
            not entry.is_symlink
            and entry.path.name.startswith("Dockerfile")
            and entry.size <= 2 * 1024 * 1024
        ):
            docker_data[entry.rel] = data
        if (
            not entry.is_symlink
            and entry.rel.startswith(".github/workflows/")
            and entry.size <= 2 * 1024 * 1024
        ):
            ci_chunks.append(data)
        if entry.size <= 2 * 1024 * 1024 and entry.path.suffix.casefold() in {".json", ".csv"}:
            if entry.path.suffix.casefold() == ".json":
                if _has_inn_marker(data):
                    counts = scan_json_bytes(data)
                else:
                    counts = (0, 0)
            else:
                header = data.partition(b"\n")[0]
                counts = _scan_csv_bytes(data) if _has_inn_marker(header) else (0, 0)
            if counts != (0, 0):
                pii_files.append(
                    {
                        "path": entry.rel,
                        "tracked": entry.rel in tracked if vcs else None,
                        "records_with_valid_inn12": counts[0],
                        "records_with_fio": counts[1],
                    }
                )

    ignored_hashes: dict[bytes, set[str]] = {}
    for rel in env_rels:
        if rel not in ignored:
            continue
        digest = digest_by_env.get(rel)
        if digest is not None:
            ignored_hashes.setdefault(digest, set()).add(rel)
    env_like_files = []
    ci_data = b"\n".join(ci_chunks)
    for rel in env_rels:
        entry = entry_by_rel[rel]
        digest = digest_by_env.get(rel)
        same_ignored = bool(
            digest is not None and any(other != rel for other in ignored_hashes.get(digest, set()))
        )
        env_like_files.append(
            {
                "path": rel,
                "tracked": rel in tracked if vcs else None,
                "ignored": rel in ignored if vcs else None,
                "symlink": entry.is_symlink,
                "symlink_target_inside_root": entry.symlink_inside_root,
                "mode": _mode(entry.path),
                "identical_to_ignored_env": same_ignored,
                "value_classes": _value_classes(data_by_env.get(rel, b"")),
                "ci_referenced": rel.encode("utf-8") in ci_data
                or Path(rel).name.encode("utf-8") in ci_data,
            }
        )

    dockerfiles = []
    for entry in entries:
        if entry.is_symlink or not entry.path.name.startswith("Dockerfile") or entry.size > 2 * 1024 * 1024:
            continue
        data = docker_data.get(entry.rel)
        if data is None:
            continue
        if COPY_ALL_RE.search(data):
            dockerfiles.append(entry.rel)
    matcher = load_matcher(root)
    unsupported = (root / ".dockerignore").exists() and matcher is None
    sensitive = set(env_rels) | matched_disk_paths | {item["path"] for item in pii_files}
    if dockerfiles:
        sensitive_in_context = sorted(
            rel for rel in sensitive if matcher is None or not matcher(rel)
        )
    else:
        sensitive_in_context = []

    archives = []
    for entry in entries:
        folded = entry.rel.casefold()
        if entry.is_symlink or not folded.endswith(ARCHIVE_SUFFIXES) or entry.size > 50 * 1024 * 1024:
            continue
        members = _archive_members(entry.path)
        if members is not None:
            archives.append(
                {
                    "path": entry.rel,
                    "tracked": entry.rel in tracked if vcs else None,
                    "secret_members": members,
                }
            )

    head = (
        _git_head_counter(
            root,
            ctx.flags.max_hash_mb * 1024 * 1024,
            text_bytes=ctx.flags.max_text_mb * 1024 * 1024,
            ctx=ctx,
        )
        if vcs
        else None
    )
    history = _git_history_counter(root, ctx=ctx) if vcs else None
    return {
        "vcs": vcs,
        "patterns": _root_patterns(head, history, worktree, outside),
        "env_like_files": env_like_files,
        "secrets_dir": _directory_info(root / ".secrets"),
        "pii_files": sorted(pii_files, key=lambda item: item["path"]),
        "build_context": {
            "dockerfiles": sorted(dockerfiles),
            "sensitive_in_context": sensitive_in_context,
            "dockerignore_unsupported": unsupported,
        },
        "archives": sorted(archives, key=lambda item: item["path"]),
        **counters,
    }


def _classes_view(counter: Counter) -> dict:
    return {
        cls: {
            "matches": values["matches"],
            "distinct": values["distinct"],
            "user_ids": values["user_ids"],
        }
        for cls, values in counter.as_dict().items()
        if cls != "generic_assignment" and values["matches"]
    }


def _add_generic_stats(target: dict[str, int], counter: Counter) -> None:
    generic = counter.as_dict()["generic_assignment"]
    target["files"] += generic["files"]
    target["matches"] += generic["matches"]


def _tracked_context(path: Path, roots: list[Path]) -> bool | None:
    for root in roots:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if not is_git_repo(root):
            return None
        return git(root, "ls-files", "--error-unmatch", "--", rel).rc == 0
    return None


def _context_candidates(ctx: Context, codex_home: Path) -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = [
        (ctx.home / ".claude" / "CLAUDE.md", "claude_md"),
        (codex_home / "AGENTS.md", "agents_md"),
    ]
    memory = ctx.home / ".claude" / "projects"
    candidates.extend((path, "memory") for path in sorted(memory.glob("*/memory/**/*.md")))
    candidates.extend((path, "user_skill") for path in sorted((ctx.home / ".claude" / "skills").glob("**/*")) if path.is_file())
    for root in ctx.roots:
        for entry in iter_files(root, ctx, NAME, max_depth=3):
            if entry.path.name == "CLAUDE.md":
                candidates.append((entry.path, "claude_md"))
            elif entry.path.name == "AGENTS.md":
                candidates.append((entry.path, "agents_md"))
            elif entry.path.name == "README.md":
                candidates.append((entry.path, "readme"))
        for directory, kind in ((root / ".claude" / "skills", "project_skill"), (root / ".claude" / "commands", "project_command")):
            candidates.extend((path, kind) for path in sorted(directory.glob("**/*")) if path.is_file())
    unique = {}
    for path, kind in candidates:
        unique[path] = kind
    return [(path, unique[path]) for path in sorted(unique, key=str)]


def _scan_context_files(
    ctx: Context, codex_home: Path
) -> tuple[list[dict], dict[str, int]]:
    result = []
    generic_stats = {"files": 0, "matches": 0}
    limit = ctx.flags.max_text_mb * 1024 * 1024
    for path, kind in _context_candidates(ctx, codex_home):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        counter = Counter()
        accepted = scan_bytes(
            data,
            counter,
            path_rel=path.name,
            is_fixture=False,
            include_generic=True,
        )
        _add_generic_stats(generic_stats, counter)
        if not accepted:
            continue
        shown = _display_home(path, ctx.home) if path.is_relative_to(ctx.home) else str(path)
        result.append(
            {
                "path": shown,
                "kind": kind,
                "tracked": _tracked_context(path, ctx.roots),
                "classes": _classes_view(counter),
            }
        )
    return result, generic_stats


def _find_nonfake(data: bytes) -> list[tuple[patterns.Match, bytes]]:
    result = []
    for match in patterns.find(data, self_check_only=True):
        value = data[match.start : match.end]
        if not patterns.is_fake(value):
            result.append((match, value))
    return result


def _scan_agent_config(
    path: Path,
    shown: str,
    is_backup: bool,
    generic_stats: dict[str, int] | None = None,
) -> dict | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    env_count = 0
    allow_count = 0
    other_data = data
    pieces: list[bytes] = []
    try:
        document = json.loads(data)
        if isinstance(document, dict):
            env = document.get("env", {})
            if isinstance(env, dict):
                for value in env.values():
                    encoded = str(value).encode("utf-8")
                    pieces.append(encoded)
                    if _find_nonfake(encoded):
                        env_count += 1
            permissions = document.get("permissions", {})
            allow = permissions.get("allow", []) if isinstance(permissions, dict) else []
            if isinstance(allow, list):
                for value in allow:
                    encoded = str(value).encode("utf-8")
                    pieces.append(encoded)
                    if _find_nonfake(encoded):
                        allow_count += 1
            remainder = dict(document)
            remainder.pop("env", None)
            if isinstance(remainder.get("permissions"), dict):
                remainder["permissions"] = dict(remainder["permissions"])
                remainder["permissions"].pop("allow", None)
            other_data = json.dumps(remainder, ensure_ascii=False).encode("utf-8")
    except (UnicodeError, json.JSONDecodeError):
        pass
    other_matches = _find_nonfake(other_data)
    counter = Counter()
    for piece in [*pieces, other_data]:
        scan_bytes(
            piece,
            counter,
            path_rel=shown,
            is_fixture=False,
            include_generic=True,
        )
    if generic_stats is not None:
        _add_generic_stats(generic_stats, counter)
    return {
        "path": shown,
        "is_backup": is_backup,
        "mode": _mode(path),
        "env_keys_with_secret": env_count,
        "allow_rules_with_secret": allow_count,
        "other_matches": len(other_matches),
        "classes": _classes_view(counter),
    }


def _agent_config_candidates(ctx: Context, codex_home: Path) -> list[tuple[Path, bool]]:
    claude = ctx.home / ".claude"
    paths = {
        claude / "settings.json",
        claude / "settings.local.json",
        ctx.home / ".claude.json",
        codex_home / "config.toml",
    }
    paths.update(claude.glob("*.bak*"))
    paths.update(claude.glob("*.json.*"))
    paths.update(codex_home.glob("config.toml.bak*"))
    for root in ctx.roots:
        paths.update((root / ".claude").glob("settings*.json"))
    result = []
    for path in sorted(paths, key=str):
        name = path.name.casefold()
        backup = ".bak" in name or (".json." in name and not name.endswith(".json"))
        result.append((path, backup))
    return result


def _scan_agent_configs(
    ctx: Context, codex_home: Path
) -> tuple[list[dict], dict[str, int]]:
    result = []
    generic_stats = {"files": 0, "matches": 0}
    for path, backup in _agent_config_candidates(ctx, codex_home):
        shown = _display_home(path, ctx.home) if path.is_relative_to(ctx.home) else str(path)
        item = _scan_agent_config(path, shown, backup, generic_stats)
        if item is not None:
            result.append(item)
    return result, generic_stats


def _home_exclusions(home: Path, roots: list[Path], codex_home: Path) -> tuple[Path, ...]:
    root_paths = [path for root in roots for path in (root, Path(os.path.realpath(root)))]
    excluded = [*root_paths, *audit_backup_dirs(home), home / ".local" / "share" / "Trash", codex_home / "sessions"]
    for pattern in ("OneDrive*", "Dropbox*", "Яндекс.Диск*", "Google Drive*"):
        excluded.extend(path for path in home.glob(pattern) if path.is_dir())
    projects = home / ".claude" / "projects"
    excluded.extend(projects.glob("*/*.jsonl"))
    excluded.extend(projects.glob("*/*/subagents"))
    return tuple(dict.fromkeys(excluded))


def _walk_regular_files(roots: list[Path]):
    for root in sorted(roots, key=str):
        if root.is_symlink() or not root.is_dir():
            continue
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirs[:] = [
                name
                for name in sorted(dirs)
                if not (current_path / name).is_symlink()
            ]
            for name in sorted(files):
                path = current_path / name
                if not path.is_symlink():
                    yield path


def _agent_history_sources(home: Path, codex_home: Path):
    projects = home / ".claude" / "projects"
    subagent_dirs = sorted(projects.glob("*/*/subagents"), key=str)
    sessions = codex_home / "sessions"
    return (
        (
            "claude_transcripts",
            projects.is_dir(),
            (path for path in sorted(projects.glob("*/*.jsonl"), key=str)),
        ),
        (
            "claude_subagents",
            bool(subagent_dirs),
            _walk_regular_files(subagent_dirs),
        ),
        (
            "codex_sessions",
            sessions.is_dir(),
            _walk_regular_files([sessions]),
        ),
    )


def _empty_agent_history(present: bool) -> dict:
    return {
        "present": present,
        "files_scanned": 0,
        "files_with_hits": 0,
        "by_class": {},
        "bytes_read": 0,
        "window_days": AGENT_HISTORY_WINDOW_DAYS,
        "truncated": False,
        "lower_bound": True,
        "paths_sample": [],
    }


def _scan_agent_histories(
    ctx: Context,
    codex_home: Path,
    *,
    max_bytes: int = AGENT_HISTORY_MAX_BYTES,
    chunk_bytes: int = AGENT_HISTORY_CHUNK_BYTES,
) -> dict[str, dict]:
    cutoff = time.time() - AGENT_HISTORY_WINDOW_DAYS * 24 * 60 * 60
    total_bytes = 0
    budget_reported = False
    size_cap_reported = False
    result = {}

    def stop_for_budget(item: dict) -> None:
        nonlocal budget_reported
        item["truncated"] = True
        ctx.mark_truncated()
        if not budget_reported:
            ctx.skip(NAME, "budget", "agent_histories")
            budget_reported = True

    def stop_for_size(item: dict) -> None:
        nonlocal size_cap_reported
        item["truncated"] = True
        ctx.mark_truncated()
        if not size_cap_reported:
            ctx.skip(NAME, "size_cap", "agent_histories")
            size_cap_reported = True

    for name, present, paths in _agent_history_sources(ctx.home, codex_home):
        item = _empty_agent_history(present)
        class_files = {secret.name: 0 for secret in patterns.CLASSES}
        if not present:
            result[name] = item
            continue
        for path in paths:
            if ctx.expired():
                stop_for_budget(item)
                break
            try:
                path_stat = path.stat()
            except OSError:
                continue
            if not path.is_file() or path_stat.st_mtime < cutoff:
                continue
            if total_bytes >= max_bytes:
                stop_for_size(item)
                break
            file_classes = set()
            tail = b""
            stopped = False
            try:
                stream = path.open("rb")
            except OSError:
                continue
            item["files_scanned"] += 1
            with stream:
                while True:
                    if ctx.expired():
                        stop_for_budget(item)
                        stopped = True
                        break
                    remaining = max_bytes - total_bytes
                    if remaining <= 0:
                        stop_for_size(item)
                        stopped = True
                        break
                    try:
                        chunk = stream.read(min(chunk_bytes, remaining))
                    except OSError:
                        break
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    item["bytes_read"] += len(chunk)
                    data = tail + chunk
                    for match in patterns.find(data, self_check_only=True):
                        value = data[match.start : match.end]
                        if not patterns.is_fake(value):
                            file_classes.add(match.cls)
                    tail = data[-AGENT_HISTORY_OVERLAP_BYTES:]
                    if total_bytes >= max_bytes and stream.tell() < path_stat.st_size:
                        stop_for_size(item)
                        stopped = True
                        break
            if file_classes:
                item["files_with_hits"] += 1
                for cls in file_classes:
                    class_files[cls] += 1
                if len(item["paths_sample"]) < 10:
                    item["paths_sample"].append(_display_home(path, ctx.home))
            if stopped:
                break
        item["by_class"] = {
            secret.name: class_files[secret.name]
            for secret in patterns.CLASSES
            if class_files[secret.name]
        }
        result[name] = item
    return result


def _inside_path(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(parent))) == str(parent)
    except ValueError:
        return False


def _summary_entries(
    root: Path,
    ctx: Context,
    *,
    exclude_dirs: frozenset[str],
    exclude_paths: tuple[Path, ...],
    excluded_worktrees: list[Path] | None,
    max_depth: int | None,
    prioritize_top_level: bool = False,
):
    root = Path(os.path.abspath(root))
    blocked = {Path(os.path.abspath(path)) for path in exclude_paths}
    if any(_inside_path(root, path) for path in blocked):
        return

    def onerror(error: OSError) -> None:
        failed = Path(error.filename) if error.filename else root
        try:
            details = failed.relative_to(root).as_posix() or "."
        except ValueError:
            details = failed.name or "."
        ctx.skip(NAME, "permission", details=details)

    for current, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        current_path = Path(current)
        try:
            relative_dir = current_path.relative_to(root)
        except ValueError:
            continue
        depth = len(relative_dir.parts)
        kept_dirs = []
        ordered_dirs = sorted(dirs)
        if prioritize_top_level and depth == 0:
            available = set(ordered_dirs)
            ordered_dirs = [
                name for name in HOME_PRIORITY_DIRS if name in available
            ] + [name for name in ordered_dirs if name not in HOME_PRIORITY_DIRS]
        for dirname in ordered_dirs:
            candidate = Path(os.path.abspath(current_path / dirname))
            if dirname in exclude_dirs or candidate in blocked:
                continue
            if (
                excluded_worktrees is not None
                and worktrees.is_linked_worktree(candidate)
            ):
                excluded_worktrees.append(candidate)
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs if max_depth is None or depth < max_depth else []
        shown_dir = relative_dir.as_posix() if relative_dir.parts else "."
        yield None, shown_dir

        for filename in sorted(files):
            path = current_path / filename
            if Path(os.path.abspath(path)) in blocked:
                continue
            try:
                path_stat = path.lstat()
            except OSError:
                onerror(OSError(0, "stat failed", str(path)))
                continue
            is_symlink = path.is_symlink()
            inside: bool | None = None
            if is_symlink:
                try:
                    inside = _inside_path(Path(os.path.realpath(path)), root)
                except OSError:
                    inside = False
            yield FileEntry(
                path=path,
                rel=path.relative_to(root).as_posix(),
                size=path_stat.st_size,
                mtime=path_stat.st_mtime,
                is_symlink=is_symlink,
                symlink_inside_root=inside,
            ), shown_dir


def _scan_tree_summary(
    root: Path,
    ctx: Context,
    *,
    exclude_paths: tuple[Path, ...] = (),
    max_depth: int | None = None,
    home_prefix: bool = False,
    include_generic: bool,
    exclude_worktrees: bool = False,
    budget_deadline: float | None = None,
    budget_details: str | None = None,
) -> dict:
    counter = Counter()
    files_scanned = 0
    matched_files = 0
    truncated = False
    excluded_worktrees: list[Path] | None = [] if exclude_worktrees else None
    is_home_root = Path(os.path.abspath(root)) == Path(os.path.abspath(ctx.home))
    if not root.is_dir():
        result = {
            "files_scanned": 0,
            "files_with_matches": 0,
            "by_class": {},
            "truncated": False,
        }
        if excluded_worktrees is not None:
            result["excluded_worktrees"] = 0
        return result

    def budget_expired() -> bool:
        now = time.time()
        return now >= ctx.deadline or (
            budget_deadline is not None and now >= budget_deadline
        )

    top_level_dirs = []
    reached_top_level = set()
    if is_home_root:
        blocked = {Path(os.path.abspath(path)) for path in exclude_paths}
        try:
            names = [path.name for path in root.iterdir() if path.is_dir()]
        except OSError:
            names = []
        available = {
            name
            for name in names
            if name not in HOME_EXCLUDED_DIRS
            and Path(os.path.abspath(root / name)) not in blocked
        }
        top_level_dirs = [
            name for name in HOME_PRIORITY_DIRS if name in available
        ] + sorted(name for name in available if name not in HOME_PRIORITY_DIRS)

    stopped_at = "."
    for entry, current_dir in _summary_entries(
        root,
        ctx,
        exclude_dirs=HOME_EXCLUDED_DIRS,
        exclude_paths=exclude_paths,
        excluded_worktrees=excluded_worktrees,
        max_depth=max_depth,
        prioritize_top_level=is_home_root,
    ):
        stopped_at = current_dir
        if budget_expired():
            ctx.mark_truncated()
            if budget_details is not None:
                ctx.skip(NAME, "budget", budget_details)
            truncated = True
            break
        if entry is None:
            if current_dir != ".":
                reached_top_level.add(current_dir.split("/", 1)[0])
            continue
        if entry.is_symlink or entry.size > 2 * 1024 * 1024:
            continue
        try:
            data = entry.path.read_bytes()
        except OSError:
            continue
        files_scanned += 1
        shown = "~/" + entry.rel if home_prefix else entry.rel
        if scan_bytes(
            data,
            counter,
            path_rel=shown,
            is_fixture=False,
            include_generic=include_generic,
        ):
            matched_files += 1
        if budget_expired():
            ctx.mark_truncated()
            if budget_details is not None:
                ctx.skip(NAME, "budget", budget_details)
            truncated = True
            break
    by_class = {
        cls: {"files": values["files"], "distinct": values["distinct"]}
        for cls, values in counter.as_dict().items()
        if values["matches"]
    }
    result = {
        "files_scanned": files_scanned,
        "files_with_matches": matched_files,
        "by_class": by_class,
        "truncated": truncated,
    }
    if excluded_worktrees is not None:
        result["excluded_worktrees"] = len(excluded_worktrees)
    if is_home_root:
        result["not_reached"] = (
            [name for name in top_level_dirs if name not in reached_top_level][:30]
            if truncated
            else []
        )
    if truncated:
        result["stopped_at"] = stopped_at
    return result


def _scan_home_blocks(
    ctx: Context,
    codex_home: Path,
    timings: dict[str, float] | None = None,
    home_deadline: float | None = None,
) -> tuple[dict, dict, dict]:
    home_started = time.perf_counter()
    exclusions = _home_exclusions(ctx.home, ctx.roots, codex_home)
    home = _scan_tree_summary(
        ctx.home,
        ctx,
        exclude_paths=exclusions,
        max_depth=6,
        home_prefix=True,
        include_generic=False,
        exclude_worktrees=True,
        budget_deadline=home_deadline,
        budget_details="home" if home_deadline is not None else None,
    )
    excluded_shown = {_display_home(path, ctx.home) for path in exclusions}
    excluded_shown.update(
        _display_home(ctx.home / name, ctx.home)
        for name in sorted(HOME_EXCLUDED_DIRS)
    )
    home["excluded"] = sorted(excluded_shown)
    if timings is not None:
        timings["home"] = round(time.perf_counter() - home_started, 2)

    shell_started = time.perf_counter()
    shell_counter = Counter()
    shell_files = 0
    shell_matches = 0
    for path in (
        ctx.home / ".bash_history",
        ctx.home / ".zsh_history",
        ctx.home / ".local" / "share" / "fish" / "fish_history",
        ctx.home / ".python_history",
    ):
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        shell_files += 1
        shell_matches += int(
            bool(scan_bytes(data, shell_counter, path_rel=_display_home(path, ctx.home), is_fixture=False, include_generic=True))
        )
    shell = {
        "files": shell_files,
        "with_matches": shell_matches,
        "by_class": {
            cls: {"files": values["files"], "distinct": values["distinct"]}
            for cls, values in shell_counter.as_dict().items()
            if values["matches"]
        },
    }
    if timings is not None:
        timings["shell_history"] = round(time.perf_counter() - shell_started, 2)
    config_started = time.perf_counter()
    config = _scan_tree_summary(
        ctx.home / ".config",
        ctx,
        home_prefix=True,
        include_generic=True,
    )
    if timings is not None:
        timings["config_dir"] = round(time.perf_counter() - config_started, 2)
    return home, shell, config


def _storage(ctx: Context) -> dict:
    paths = [ctx.home / ".secrets"]
    config = ctx.home / ".config"
    try:
        paths.extend(
            path
            for path in config.iterdir()
            if path.is_dir() and SECRET_DIR_NAME_RE.search(path.name)
        )
    except OSError:
        pass
    return {
        "secrets_dirs": [
            item
            for item in (_directory_info(path, ctx.home) for path in sorted(set(paths), key=str))
            if item is not None
        ]
    }


def _ssh(ctx: Context) -> tuple[list[dict], int]:
    directory = ctx.home / ".ssh"
    keys = []
    try:
        candidates = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError:
        candidates = []
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        if path.name.endswith(".pub") or path.name.startswith("known_hosts") or path.name in {"config", "authorized_keys"}:
            continue
        try:
            data = path.read_bytes()
            if not data.startswith(b"-----BEGIN"):
                continue
            item = key_info(path, data)
        except OSError:
            continue
        item["file"] = _display_home(path, ctx.home)
        keys.append(item)
    authorized = 0
    try:
        for line in (directory / "authorized_keys").read_bytes().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(b"#") and stripped.startswith((b"ssh-", b"ecdsa-", b"sk-")):
                authorized += 1
    except OSError:
        pass
    return keys, authorized


def _run_controls(ctx: Context) -> dict[str, str]:
    value = _control_value()
    tail = value.rsplit(b"/", 1)[-1]
    tree_values = (
        value,
        b"rest/2/" + tail,
        b"BiTrIx webhook 3/" + tail,
    )

    def build_tree(path: Path) -> None:
        target = path / "sub"
        target.mkdir()
        for index, probe in enumerate(tree_values):
            (target / f"probe-{index}.txt").write_bytes(probe)

    def probe_tree(path: Path) -> int:
        counter = Counter()
        sizing = {"windowed_files": 0, "size_cap_files": 0}
        for entry in iter_files(path, ctx, NAME):
            data, _digest = _read_for_scan(entry, ctx, sizing)
            if data is not None:
                scan_bytes(
                    data,
                    counter,
                    path_rel=entry.rel,
                    is_fixture=False,
                    include_generic=False,
                )
        return counter.as_dict()["bitrix_webhook"]["matches"]

    def init_repo(path: Path) -> None:
        if run(["git", "init", "-q", str(path)]).rc != 0:
            raise RuntimeError("git_init")

    def build_head(path: Path) -> None:
        init_repo(path)
        (path / "probe.txt").write_bytes(value)
        if _git_command(path, "add", "probe.txt").rc != 0 or not _git_commit(path, "add"):
            raise RuntimeError("git_commit")

    def probe_head(path: Path) -> int:
        return _git_head_counter(path, 2 * 1024 * 1024).as_dict()["bitrix_webhook"]["files"]

    def build_history(path: Path) -> None:
        build_head(path)
        (path / "probe.txt").unlink()
        if _git_command(path, "add", "-u").rc != 0 or not _git_commit(path, "remove"):
            raise RuntimeError("git_commit")

    def probe_history(path: Path) -> int:
        return _git_history_counter(path).as_dict()["bitrix_webhook"]["files"]

    def build_configs(path: Path) -> None:
        document = {"permissions": {"allow": [(b"Bash(curl " + value + b")").decode("ascii")]}}
        (path / "settings.json").write_text(json.dumps(document), encoding="utf-8")

    def probe_configs(path: Path) -> int:
        item = _scan_agent_config(path / "settings.json", "settings.json", False)
        return 0 if item is None else item["allow_rules_with_secret"]

    def build_home(path: Path) -> None:
        (path / ".config" / "x").mkdir(parents=True)
        (path / ".bash_history").write_bytes(value)
        (path / ".config" / "x" / "c.ini").write_bytes(value)

    def probe_home(path: Path) -> int:
        started = ctx.started_at
        local = Context(ctx.flags, path, [], started, ctx.deadline)
        home, shell, config = _scan_home_blocks(local, path / ".codex")
        return home["files_with_matches"] + shell["with_matches"] + config["files_with_matches"]

    return {
        "tree": positive_control(
            NAME,
            "tree",
            ctx,
            build_tree,
            probe_tree,
            minimum_hits=len(tree_values),
        ),
        "git_head": positive_control(NAME, "git_head", ctx, build_head, probe_head),
        "git_history": positive_control(NAME, "git_history", ctx, build_history, probe_history),
        "configs": positive_control(NAME, "configs", ctx, build_configs, probe_configs),
        "home": positive_control(NAME, "home", ctx, build_home, probe_home),
    }


def _record_control_failures(ctx: Context, controls: dict[str, str]) -> None:
    for name, status in controls.items():
        if status == "fail":
            ctx.error(NAME, f"positive_control_failed:{name}")


def collect(ctx: Context) -> dict:
    timings: dict[str, float] = {}
    started = time.perf_counter()
    controls = _run_controls(ctx)
    _record_control_failures(ctx, controls)
    timings["positive_controls"] = round(time.perf_counter() - started, 2)
    host = ctx.shared.get("host", {})
    codex_home = Path(str(host.get("codex_home", ctx.home / ".codex"))) if isinstance(host, dict) else ctx.home / ".codex"

    started = time.perf_counter()
    context_files, context_generic = _scan_context_files(ctx, codex_home)
    timings["context_files"] = round(time.perf_counter() - started, 2)

    started = time.perf_counter()
    if controls["configs"] == "pass":
        configs, configs_generic = _scan_agent_configs(ctx, codex_home)
    else:
        configs = None
        configs_generic = {"files": 0, "matches": 0}
    timings["agent_configs"] = round(time.perf_counter() - started, 2)

    started = time.perf_counter()
    roots: dict[str, dict] | None
    if any(controls[name] == "fail" for name in ("tree", "git_head", "git_history")):
        roots = None
    else:
        roots = {}
        for root in ctx.roots:
            vcs = is_git_repo(root)
            if not vcs:
                ctx.skip(NAME, "no_vcs", details=str(root))
            roots[str(root)] = _scan_root(root, ctx, vcs)
    timings["roots"] = round(time.perf_counter() - started, 2)

    if controls["home"] == "pass":
        now = time.time()
        home_deadline = min(now + 120, ctx.deadline - 30)
        home, shell_history, config_dir = _scan_home_blocks(
            ctx,
            codex_home,
            timings,
            home_deadline=home_deadline,
        )
    else:
        home = shell_history = config_dir = None
        timings.update({"home": 0.0, "shell_history": 0.0, "config_dir": 0.0})

    started = time.perf_counter()
    agent_histories = _scan_agent_histories(ctx, codex_home)
    timings["agent_histories"] = round(time.perf_counter() - started, 2)

    started = time.perf_counter()
    storage = _storage(ctx)
    timings["storage"] = round(time.perf_counter() - started, 2)

    started = time.perf_counter()
    ssh_keys, authorized_keys = _ssh(ctx)
    timings["ssh_keys"] = round(time.perf_counter() - started, 2)

    started = time.perf_counter()
    external_access = collect_external_access(ctx.home)
    timings["external"] = round(time.perf_counter() - started, 2)
    return {
        "lower_bound": True,
        "timings_s": timings,
        "positive_controls": controls,
        "generic_assignment_scope": list(GENERIC_ASSIGNMENT_SCOPE),
        "context_files": context_files,
        "context_generic_assignment": context_generic,
        "agent_configs": configs,
        "agent_configs_generic_assignment": configs_generic,
        "roots": roots,
        "home": home,
        "agent_histories": agent_histories,
        "shell_history": shell_history,
        "config_dir": config_dir,
        "storage": storage,
        "ssh_keys": ssh_keys,
        "authorized_keys": authorized_keys,
        "external_access": external_access,
    }
