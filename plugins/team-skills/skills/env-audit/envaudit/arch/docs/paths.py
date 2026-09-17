from dataclasses import dataclass
import os
from pathlib import Path
import re

from envaudit.arch.context import ArchContext, path_inside
from envaudit.core.runner import git

from . import Document


CODE_PATH = re.compile(r"[\w./-]+\.(?:py|sh|php|js|ts)\b", re.IGNORECASE)
BACKTICK = re.compile(r"`([^`\r\n]+)`")
TREE_BRANCH = re.compile(r"^([ \t│]*)(?:├──|└──)\s+(.+?)\s*$")
TREE_ROOT = re.compile(
    r"^([ \t]*)([\w./-]+/)\s*(?:#\s*(.*))?$"
)
TREE_COMMENT = re.compile(r"^[ \t]*│[ \t│]*#\s*(.+?)\s*$")
COMMENT_FILE = re.compile(
    r"(?<![\w./-])([\w.-]+\.(?:py|sh|php|js|ts|cs|sql|md|json|toml|yaml|yml|txt))\b",
    re.IGNORECASE,
)
QUALIFIED_PATH = re.compile(
    r"^(.+?\.[A-Za-z0-9]+):{1,2}[A-Za-z_][\w.]*$"
)
REMOVED = re.compile(
    r"удал[её]н|выкинут|больше\s+нет|removed|deprecated|legacy",
    re.IGNORECASE,
)
KNOWN_SUFFIXES = frozenset(
    {
        ".py",
        ".sh",
        ".php",
        ".js",
        ".ts",
        ".cs",
        ".sql",
        ".md",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".txt",
    }
)
HANDOFF_PATH = re.compile(
    r"[^\s`\"'<>]*HANDOFF[^\s`\"'<>]*\.md", re.IGNORECASE
)
COMMAND_DOCUMENTS = frozenset({"handoff.md", "changelog.md", "architecture.md"})


@dataclass(frozen=True)
class Mention:
    doc: str
    line: int
    path: str
    source: str


def _clean(raw: str) -> str:
    value = raw.strip().lstrip("'\"")
    value = re.split(r"\s+(?:#|//|—|–)\s*", value, maxsplit=1)[0]
    value = value.rstrip(",;:.)]»\"'")
    qualified = QUALIFIED_PATH.match(value)
    if qualified and Path(qualified.group(1)).suffix.lower() in KNOWN_SUFFIXES:
        return qualified.group(1)
    return value


def _top_level(actx: ArchContext) -> set[str]:
    return {
        Path(entry.rel).parts[0]
        for entry in actx.files()
        if Path(entry.rel).parts
    }


def _eligible_backtick(value: str, top_level: set[str]) -> bool:
    parts = Path(value.removeprefix("./")).parts
    if not parts:
        return False
    suffix = Path(value.rstrip("/")).suffix.lower()
    return parts[0] in top_level or suffix in KNOWN_SUFFIXES or value == ".env"


def _skipped(value: str) -> bool:
    if not value or value.startswith(("/", "~")) or "://" in value:
        return True
    normalized = value.removeprefix("./")
    if (
        any(character.isspace() for character in value)
        or "..." in value
        or "…" in value
        or normalized.startswith("_")
        or any(marker in value for marker in ("*", "<", ">", "{", "}", "$", "NN", "XXX", "YYYY"))
    ):
        return True
    parts = Path(normalized).parts
    if not parts or any(part == ".." for part in parts):
        return True
    if re.fullmatch(r"[^/]+/[^/]+/?", value) and not Path(value).suffix:
        return True
    first = parts[0]
    if (
        re.fullmatch(r"[A-Za-z0-9-]+\.[A-Za-z]{2,}", first)
        and Path(first).suffix.lower() not in KNOWN_SUFFIXES
    ):
        return True
    return False


def _comment_mentions(
    document: Document, number: int, comment: str, directory: str
) -> list[Mention]:
    result = []
    for match in COMMENT_FILE.finditer(comment):
        name = match.group(1)
        value = f"{directory.rstrip('/')}/{name}" if directory else name
        result.append(
            Mention(document.rel, number, value, "tree_listing")
        )
    return result


def _tree_depth(prefix: str) -> int:
    width = len(prefix.expandtabs(4))
    return (width + 2) // 4 if width else 0


def _origin_repo_name(actx: ArchContext) -> str | None:
    if not actx.vcs:
        return None
    result = git(actx.root, "remote", "get-url", "origin")
    if result.rc != 0:
        return None
    remote = result.stdout.decode("utf-8", "replace").strip().rstrip("/")
    name = re.split(r"[/\\:]", remote)[-1]
    if name.lower().endswith(".git"):
        name = name[:-4]
    return name or None


def _virtual_tree_roots(actx: ArchContext) -> set[str]:
    names = {actx.root.name.casefold()}
    origin = _origin_repo_name(actx)
    if origin:
        names.add(origin.casefold())
    return names


def _virtual_tree_root(
    primary: Path, value: str, names: set[str]
) -> bool:
    normalized = value.removeprefix("./").rstrip("/")
    parts = Path(normalized).parts
    return (
        len(parts) == 1
        and parts[0].casefold() in names
        and not (primary / parts[0]).is_dir()
    )


def _tree_mentions(
    document: Document, primary: Path, virtual_roots: set[str]
) -> list[Mention]:
    result: list[Mention] = []
    parents: dict[int, str] = {}
    explicit_root = False
    depth_offset = 0
    for number, line in enumerate(document.lines, 1):
        if REMOVED.search(line):
            continue
        branch = TREE_BRANCH.match(line)
        if branch:
            prefix, raw = branch.groups()
            item, _, comment = raw.partition("#")
            value = _clean(item).split()[0] if _clean(item) else ""
            raw_depth = _tree_depth(prefix)
            if (
                raw_depth == 0
                and value.endswith("/")
                and _virtual_tree_root(primary, value, virtual_roots)
            ):
                parents = {0: ""}
                explicit_root = False
                depth_offset = 0
                if comment:
                    result.extend(
                        _comment_mentions(document, number, comment, "")
                    )
                continue
            if explicit_root and depth_offset == 0 and raw_depth == 0:
                depth_offset = 1
            depth = raw_depth + depth_offset
            parents = {
                level: path for level, path in parents.items() if level < depth
            }
            parent = parents.get(depth - 1) if depth else ""
            if not value or (depth and parent is None):
                continue
            joined = f"{parent.rstrip('/')}/{value}" if parent else value
            result.append(Mention(document.rel, number, joined, "tree_listing"))
            if value.endswith("/"):
                parents[depth] = joined
                if comment:
                    result.extend(
                        _comment_mentions(document, number, comment, joined)
                    )
            continue

        continuation = TREE_COMMENT.match(line)
        if continuation and parents:
            directory = parents[max(parents)]
            result.extend(
                _comment_mentions(
                    document, number, continuation.group(1), directory
                )
            )
            continue

        root = TREE_ROOT.match(line)
        if root:
            _, value, comment = root.groups()
            directory = (
                ""
                if _virtual_tree_root(primary, value, virtual_roots)
                else value
            )
            parents = {0: directory}
            explicit_root = True
            depth_offset = 0
            if comment:
                result.extend(
                    _comment_mentions(document, number, comment, directory)
                )
            continue

        if line.strip():
            parents = {}
            explicit_root = False
            depth_offset = 0
    return result


def _tree_syntax(line: str) -> bool:
    return bool(
        TREE_BRANCH.match(line)
        or TREE_COMMENT.match(line)
        or TREE_ROOT.match(line)
    )


def extract_mentions(actx: ArchContext, documents: list[Document]) -> list[Mention]:
    result = []
    top_level = _top_level(actx)
    primary = actx.trees["primary"].path
    virtual_roots = _virtual_tree_roots(actx)
    for document in documents:
        result.extend(_tree_mentions(document, primary, virtual_roots))
        fence_language: str | None = None
        in_fence = False
        for number, line in enumerate(document.lines, 1):
            fence = re.match(r"^\s*```\s*([^\s`]*)", line)
            if fence:
                if in_fence:
                    in_fence = False
                    fence_language = None
                else:
                    in_fence = True
                    fence_language = fence.group(1).lower()
                continue
            if REMOVED.search(line):
                continue
            for match in BACKTICK.finditer(line):
                value = _clean(match.group(1))
                if _eligible_backtick(value, top_level):
                    result.append(
                        Mention(document.rel, number, value, "backtick")
                    )
            if in_fence and fence_language in {"", "sh", "bash"}:
                if _tree_syntax(line):
                    continue
                for match in CODE_PATH.finditer(line):
                    result.append(
                        Mention(document.rel, number, match.group(0), "fenced")
                    )
    unique = {}
    for item in result:
        unique[(item.doc, item.line, item.path, item.source)] = item
    return sorted(
        unique.values(), key=lambda item: (item.doc, item.line, item.path, item.source)
    )


def _candidate_rels(document: Document, value: str) -> list[str]:
    normalized = Path(value.removeprefix("./")).as_posix()
    candidates = [normalized]
    parent = Path(document.rel).parent
    if parent != Path("."):
        candidates.append((parent / normalized).as_posix())
    candidates.append((Path("docs") / normalized).as_posix())
    return list(dict.fromkeys(candidates))


def _exists(root: Path, rel: str, directory: bool) -> bool:
    candidate = Path(os.path.abspath(root / rel.rstrip("/")))
    if not path_inside(candidate, Path(os.path.abspath(root))):
        return False
    return candidate.is_dir() if directory else candidate.exists()


def _basename_in_docs(root: Path, value: str) -> bool:
    docs = root / "docs"
    if not docs.is_dir():
        return False
    basename = Path(value.rstrip("/")).name
    try:
        return any(path.is_dir() and path.name == basename for path in docs.rglob("*"))
    except OSError:
        return False


def _file_basename_exists(actx: ArchContext, value: str) -> bool:
    if "/" in value or value.endswith("/"):
        return False
    basename = Path(value).name
    return any(Path(entry.rel).name == basename for entry in actx.files())


def _file_suffix_exists(actx: ArchContext, value: str) -> bool:
    normalized = Path(value.removeprefix("./")).as_posix()
    if "/" not in normalized or value.endswith("/"):
        return False
    suffix = "/" + normalized
    return any(entry.rel.endswith(suffix) for entry in actx.files())


def _prefixed_command_document_exists(
    actx: ArchContext, value: str
) -> bool:
    if "/" in value or value.endswith("/"):
        return False
    basename = Path(value).name.casefold()
    if basename not in COMMAND_DOCUMENTS:
        return False
    for entry in actx.files():
        parts = Path(entry.rel).parts
        if not parts or (len(parts) > 1 and parts[0].casefold() != "docs"):
            continue
        if Path(entry.rel).name.casefold().endswith("-" + basename):
            return True
    return False


def _ignored(actx: ArchContext, rels: list[str]) -> bool:
    if not actx.vcs:
        return False
    primary = actx.trees["primary"].path
    for rel in rels:
        result = git(
            actx.root,
            f"--work-tree={primary}",
            "check-ignore",
            "--no-index",
            "--quiet",
            "--",
            rel.rstrip("/"),
        )
        if result.rc == 0:
            return True
    return False


def _other_branch(actx: ArchContext, rels: list[str]) -> str | None:
    if not actx.vcs:
        return None
    for rel in rels:
        result = git(
            actx.root,
            "cat-file",
            "-e",
            f"origin/dev:{rel.rstrip('/')}",
        )
        if result.rc == 0:
            return "origin/dev"
    return None


def missing_paths(actx: ArchContext, documents: list[Document]) -> list[dict]:
    primary = actx.trees["primary"].path
    by_rel = {document.rel: document for document in documents}
    result = []
    for mention in extract_mentions(actx, documents):
        value = mention.path
        if _skipped(value):
            continue
        document = by_rel[mention.doc]
        rels = _candidate_rels(document, value)
        directory = value.endswith("/")
        if any(_exists(primary, rel, directory) for rel in rels):
            continue
        if not directory and _file_suffix_exists(actx, value):
            continue
        if not directory and _file_basename_exists(actx, value):
            continue
        if not directory and _prefixed_command_document_exists(actx, value):
            continue
        if directory and _basename_in_docs(primary, value):
            continue
        if _ignored(actx, rels):
            continue
        branch = _other_branch(actx, rels)
        result.append(
            {
                "doc": mention.doc,
                "line": mention.line,
                "path": value,
                "source": mention.source,
                "resolved_on_other_branch": branch,
            }
        )
    return result


def document_locations(actx: ArchContext, documents: list[Document]) -> dict:
    files = actx.files()
    handoffs = sorted(
        entry.rel
        for entry in files
        if Path(entry.rel).suffix.lower() == ".md"
        and "handoff" in Path(entry.rel).name.lower()
    )
    changelogs = sorted(
        entry.rel
        for entry in files
        if Path(entry.rel).suffix.lower() == ".md"
        and "changelog" in Path(entry.rel).name.lower()
    )
    sources = list(documents)
    known = {document.rel for document in sources}
    for entry in files:
        if not entry.rel.startswith(".claude/skills/") or entry.rel in known:
            continue
        data = actx.read(entry)
        if data is not None:
            sources.append(
                Document(entry, entry.rel, data.decode("utf-8", "replace"))
            )
    named = set()
    for document in sources:
        for match in HANDOFF_PATH.finditer(document.text):
            named.add(match.group(0).strip(".,;:()[]"))
    return {
        "handoff_files": handoffs,
        "changelog_files": changelogs,
        "paths_named_in_agent_files": sorted(named),
    }
