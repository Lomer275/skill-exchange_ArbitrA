import os
from pathlib import Path

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext
from envaudit.core.runner import git
from envaudit.core.walk import EXCLUDED_DIRS


KEY = "size"
ORDER = 40
TEXT_LIMIT = 2 * 1024 * 1024
SIZE_CAP = 20 * 1024 * 1024
LANGUAGES = {
    "python": frozenset({".py"}),
    "php": frozenset({".php"}),
    "js_ts": frozenset({".js", ".jsx", ".ts", ".tsx"}),
    "csharp": frozenset({".cs"}),
    "sql": frozenset({".sql"}),
    "shell": frozenset({".sh", ".bash", ".zsh"}),
}
CODE_EXTENSIONS = frozenset().union(*LANGUAGES.values())
DATA_EXTENSIONS = frozenset(
    {".json", ".jsonl", ".csv", ".tsv", ".db", ".sqlite", ".sql", ".xml", ".yaml", ".yml"}
)
DOCUMENT_EXTENSIONS = frozenset(
    {".md", ".rst", ".txt", ".doc", ".docx", ".pdf"}
)


def _language(rel: str) -> str | None:
    suffix = Path(rel).suffix.lower()
    return next(
        (name for name, suffixes in LANGUAGES.items() if suffix in suffixes),
        None,
    )


def _kind(rel: str) -> str:
    suffix = Path(rel).suffix.lower()
    if suffix in CODE_EXTENSIONS:
        return "code"
    if suffix in DATA_EXTENSIONS:
        return "data"
    if suffix in DOCUMENT_EXTENSIONS:
        return "documents"
    return "other"


def _non_python_sloc(data: bytes, language: str) -> int:
    prefixes = {
        "php": (b"//", b"#", b"/*", b"*", b"*/"),
        "js_ts": (b"//", b"/*", b"*", b"*/"),
        "csharp": (b"//", b"/*", b"*", b"*/"),
        "sql": (b"--", b"/*", b"*", b"*/"),
        "shell": (b"#",),
    }[language]
    return sum(
        1
        for line in data.splitlines()
        if line.strip() and not line.lstrip().startswith(prefixes)
    )


def _stream_lines(path: Path) -> int | None:
    try:
        size = path.stat().st_size
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
        return None


def _sample_data_shaped(path: Path, size: int) -> bool:
    window = 256 * 1024
    try:
        with path.open("rb") as stream:
            samples = []
            for offset in (0, max(0, size // 2 - window // 2), max(0, size - window)):
                stream.seek(offset)
                samples.append(stream.read(window))
    except OSError:
        return False
    lines = [line.strip() for sample in samples for line in sample.splitlines() if line.strip()]
    if not lines:
        return False
    literal = sum(
        1
        for line in lines
        if line[:1] in {b"'", b'"', b"[", b"{", b"("}
        or line[:1].isdigit()
    )
    return literal / len(lines) >= 0.8


def _tracked(actx: ArchContext) -> set[str] | None:
    view = actx.trees.get("primary")
    if view is None:
        return set()
    if view.mode == "archive":
        return {entry.rel for entry in actx.files()}
    if not actx.vcs:
        return None
    result = git(actx.root, "ls-files", "-z")
    if result.rc != 0:
        return None
    return {
        item.decode("utf-8", "surrogateescape")
        for item in result.stdout.split(b"\x00")
        if item
    }


def _ignored_dirs(actx: ArchContext) -> list[str]:
    view = actx.trees.get("primary")
    if view is None:
        return []
    output = []
    for current, dirs, _ in os.walk(view.path, followlinks=False):
        current_path = Path(current)
        kept = []
        for name in sorted(dirs):
            rel = (current_path / name).relative_to(view.path).as_posix()
            if name in EXCLUDED_DIRS:
                output.append(rel)
            else:
                kept.append(name)
        dirs[:] = kept
    return output


def _empty_metric() -> dict:
    return {
        "files": 0,
        "lines": 0,
        "sloc": 0,
        "prod_sloc": 0,
        "test_files": 0,
        "test_lines": 0,
    }


def run(actx: ArchContext) -> None:
    metrics = {language: _empty_metric() for language in LANGUAGES}
    large_files = []
    on_disk = {name: 0 for name in ("code", "data", "documents", "other")}
    tracked_bytes = {name: 0 for name in on_disk}
    tracked = _tracked(actx)

    for entry in actx.files():
        kind = _kind(entry.rel)
        on_disk[kind] += entry.size
        if tracked is not None and entry.rel in tracked:
            tracked_bytes[kind] += entry.size
        language = _language(entry.rel)
        if language is None:
            continue
        metric = metrics[language]
        metric["files"] += 1
        prod = actx.is_prod_path(entry.rel)
        if not prod:
            metric["test_files"] += 1

        if entry.size > SIZE_CAP:
            large_files.append(
                {"path": entry.rel, "data_shaped": True, "reason": "size_cap"}
            )
            actx.skip(KEY, "size_cap", entry.rel)
            continue
        if entry.size > TEXT_LIMIT:
            lines = _stream_lines(entry.path)
            if lines is not None:
                metric["lines"] += lines
                if not prod:
                    metric["test_lines"] += lines
            large_files.append(
                {
                    "path": entry.rel,
                    "data_shaped": _sample_data_shaped(entry.path, entry.size),
                    "reason": None,
                }
            )
            continue

        data = actx.read(entry, max_bytes=TEXT_LIMIT)
        if data is None:
            continue
        if language == "python":
            lines, sloc, no_strings = pyast.sloc(data, python=True)
        else:
            lines, _, _ = pyast.sloc(data, python=False)
            sloc = _non_python_sloc(data, language)
            no_strings = sloc
        metric["lines"] += lines
        metric["sloc"] += sloc
        if prod:
            metric["prod_sloc"] += no_strings if language == "python" else sloc
        else:
            metric["test_lines"] += lines

    prod_sloc = sum(metric["prod_sloc"] for metric in metrics.values())
    test_lines = sum(metric["test_lines"] for metric in metrics.values())
    groups = 0
    classification = actx.out.get("classification")
    if isinstance(classification, dict):
        value = classification.get("groups")
        groups = len(value) if isinstance(value, list) else 0
    if prod_sloc < 1500 and groups == 1:
        tier = "S"
    elif prod_sloc <= 10000:
        tier = "M"
    else:
        tier = "L"

    actx.out[KEY] = {
        "by_language": metrics,
        "bytes": {
            "tracked": tracked_bytes if tracked is not None else None,
            "on_disk": on_disk,
            "ignored_dirs": _ignored_dirs(actx),
        },
        "test_prod_ratio": round(test_lines / prod_sloc, 6) if prod_sloc else None,
        "large_files": large_files,
    }
    if isinstance(classification, dict):
        classification["size_tier"] = tier
    actx.rule_inputs["G1"] = {
        "size_tier": tier,
        "prod_sloc": prod_sloc,
        "groups": groups,
    }
