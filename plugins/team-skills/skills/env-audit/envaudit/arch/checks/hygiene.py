from fnmatch import fnmatch
from pathlib import Path
import re

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext
from envaudit.core.runner import git


KEY = "hygiene"
ORDER = 90
LARGE_BYTES = 10 * 1024 * 1024
DUMP_BYTES = 1024 * 1024
CODE_EXTENSIONS = frozenset(
    {".py", ".php", ".js", ".jsx", ".ts", ".tsx", ".cs", ".sh", ".bash", ".zsh"}
)
DATA_EXTENSIONS = frozenset(
    {".json", ".jsonl", ".csv", ".tsv", ".db", ".sqlite", ".sql", ".xml", ".yaml", ".yml"}
)
MANIFEST_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "pipfile",
        "poetry.lock",
        "package.json",
        "composer.json",
        "gemfile",
        "go.mod",
    }
)
_COPY_SUFFIX = re.compile(
    r"(?:\s*-\s*)?\(?(?:copy|копия)\)?(?:\s*\(\d+\))?\.[^.]+$",
    re.IGNORECASE,
)
_NUMBERED_COPY = re.compile(r"\.[^.]+\.1$")
_BROKEN_FRAGMENT = re.compile(r"[\[\]\\\"{}]|chr\(|print\(", re.IGNORECASE)


def _decode_paths(data: bytes) -> list[str]:
    return sorted(
        item.decode("utf-8", "surrogateescape")
        for item in data.split(b"\x00")
        if item
    )


def _tracked(actx: ArchContext) -> set[str] | None:
    view = actx.trees.get("primary")
    if view is None:
        return set()
    if view.mode == "archive":
        return {entry.rel for entry in actx.files()}
    if not actx.vcs:
        return None
    result = git(actx.root, "ls-files", "-z")
    return set(_decode_paths(result.stdout)) if result.rc == 0 else None


def _backup_name(name: str) -> bool:
    lowered = name.lower()
    return (
        fnmatch(lowered, "*.bak*")
        or lowered.endswith((".bck", ".orig", "~"))
        or _NUMBERED_COPY.search(name) is not None
    )


def _broken_name(rel: str) -> bool:
    for part in Path(rel).parts:
        if (
            part.startswith(("'", '"'))
            or _BROKEN_FRAGMENT.search(part) is not None
            or _COPY_SUFFIX.search(part) is not None
            or _NUMBERED_COPY.search(part) is not None
        ):
            return True
    return False


def _manifest(rel: str) -> bool:
    name = Path(rel).name.lower()
    return (
        name in MANIFEST_NAMES
        or name.startswith("requirements") and name.endswith(".txt")
        or name.endswith((".csproj", ".sln"))
    )


def _root_allowed(rel: str, anchor_entries: set[str]) -> bool:
    path = Path(rel)
    name = path.name
    lowered = name.lower()
    if _manifest(rel):
        return True
    if (
        fnmatch(name, "README*")
        or name in {"CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "LICENSE", "Makefile", "manage.py"}
        or fnmatch(name, "*-HANDOFF.md")
        or fnmatch(name, "*-CHANGELOG.md")
        or fnmatch(name, "*-architecture.md")
        or fnmatch(name, "Dockerfile*")
        or lowered.startswith("docker-compose")
        or name in {"compose.yml", "compose.yaml", ".gitignore", ".dockerignore", "pytest.ini", "setup.cfg", "service.yaml"}
        or fnmatch(name, "*.example")
    ):
        return True
    return path.suffix.lower() == ".py" and rel in anchor_entries


def _anchor_entries(actx: ArchContext) -> set[str]:
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    return {
        str(item["entry"])
        for item in anchors
        if isinstance(item, dict) and isinstance(item.get("entry"), str)
    }


def _tracked_ignored(actx: ArchContext) -> list[str] | None:
    if not actx.vcs:
        actx.skip("H3", "no_vcs")
        return None
    result = git(
        actx.root,
        "ls-files",
        "-ci",
        "--exclude-standard",
        "-z",
    )
    if result.rc != 0:
        actx.error(KEY, "git_tracked_ignored")
        return None
    return _decode_paths(result.stdout)


def _untracked(actx: ArchContext) -> list[str] | None:
    if not actx.vcs:
        return None
    result = git(
        actx.root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    if result.rc != 0:
        actx.error(KEY, "git_untracked")
        return None
    return [
        rel for rel in _decode_paths(result.stdout) if len(Path(rel).parts) == 1
    ]


def _third_party_prod(actx: ArchContext) -> set[str]:
    local = pyast.local_modules(actx)
    anchors = _anchor_entries(actx)
    result = set()
    for entry in actx.code_files(exts=frozenset({".py"})):
        if not actx.is_prod_path(entry.rel):
            continue
        parts = tuple(part.lower() for part in Path(entry.rel).parts)
        if parts and parts[0] in {"tools", "scripts"} and entry.rel not in anchors:
            continue
        data = actx.read(entry)
        if data is None:
            continue
        tree = pyast.parse(data, entry.rel)
        if tree is not None:
            result.update(pyast.third_party_imports(tree, local))
    return result


def run(actx: ArchContext) -> None:
    files = actx.files()
    by_rel = {entry.rel: entry for entry in files}
    tracked = _tracked(actx)
    selected = set(by_rel) if tracked is None else tracked
    root_entries = [entry for entry in files if len(Path(entry.rel).parts) == 1]
    anchors = _anchor_entries(actx)

    if tracked is None:
        backup_patterns = None
        backups = None
        actx.skip("H1", "no_vcs")
    else:
        backup_patterns = sorted(
            entry.rel
            for entry in root_entries
            if entry.rel in tracked and _backup_name(Path(entry.rel).name)
        )
        backups = sorted(
            rel for rel in tracked if _backup_name(Path(rel).name)
        )

    not_allowlisted = sorted(
        entry.rel
        for entry in root_entries
        if not _root_allowed(entry.rel, anchors)
    )
    untracked = _untracked(actx)
    large = sorted(entry.rel for entry in root_entries if entry.size > LARGE_BYTES)
    broken = sorted(entry.rel for entry in files if _broken_name(entry.rel))
    tracked_ignored = _tracked_ignored(actx)

    tracked_data_bytes = 0
    tracked_code_bytes = 0
    dumps = []
    for rel in sorted(selected):
        entry = by_rel.get(rel)
        if entry is None:
            continue
        suffix = Path(rel).suffix.lower()
        if suffix in CODE_EXTENSIONS:
            tracked_code_bytes += entry.size
        if suffix in DATA_EXTENSIONS:
            tracked_data_bytes += entry.size
            parts = tuple(part.lower() for part in Path(rel).parts[:-1])
            if entry.size > DUMP_BYTES and "docs" not in parts:
                dumps.append(rel)

    handoffs = sorted(
        entry.rel
        for entry in files
        if Path(entry.rel).suffix.lower() == ".md"
        and "handoff" in Path(entry.rel).stem.lower()
    )
    changelogs = sorted(
        entry.rel
        for entry in files
        if Path(entry.rel).suffix.lower() == ".md"
        and "changelog" in Path(entry.rel).stem.lower()
    )
    tree = actx.out.get("tree", {})
    dirty = tree.get("dirty", {}) if isinstance(tree, dict) else {}
    if actx.vcs:
        crlf = dirty.get("crlf_only_files") if isinstance(dirty, dict) else None
    else:
        crlf = None
        actx.skip("H6", "no_vcs")

    third_party = _third_party_prod(actx)
    manifest_present = any(_manifest(entry.rel) for entry in files)
    data_vs_code = {
        "tracked_data_bytes": tracked_data_bytes,
        "tracked_code_bytes": tracked_code_bytes,
        "dumps_over_1mb_outside_docs": sorted(dumps),
    }
    doc_duplicates = {"handoff_md": handoffs, "changelog_md": changelogs}
    dependency_manifest = {
        "present": manifest_present,
        "third_party_imports_prod": len(third_party),
    }
    actx.out[KEY] = {
        "root_files": {
            "backup_patterns": backup_patterns,
            "not_allowlisted": not_allowlisted,
            "untracked_not_ignored": untracked,
            "large_over_10mb": large,
        },
        "backups": backups,
        "broken_names": broken,
        "tracked_but_ignored": tracked_ignored,
        "data_vs_code": data_vs_code,
        "doc_duplicates": doc_duplicates,
        "crlf_only_changes": crlf,
        "gitattributes": any(Path(entry.rel).name == ".gitattributes" for entry in root_entries),
        "dependency_manifest": dependency_manifest,
    }

    actx.rule_inputs["H1"] = {
        "backup_patterns": None if backup_patterns is None else len(backup_patterns),
        "untracked_not_ignored": None if untracked is None else len(untracked),
        "large_over_10mb": len(large),
    }
    actx.rule_inputs["H2"] = {"count": len(broken)}
    actx.rule_inputs["H3"] = {
        "count": None if tracked_ignored is None else len(tracked_ignored)
    }
    actx.rule_inputs["H4"] = dict(data_vs_code)
    actx.rule_inputs["H5"] = {
        "metric_only": True,
        "count": len(handoffs) + len(changelogs),
    }
    actx.rule_inputs["H6"] = {
        "crlf_only_changes": crlf,
        "gitattributes": actx.out[KEY]["gitattributes"],
    }
    actx.rule_inputs["H7"] = dict(dependency_manifest)
