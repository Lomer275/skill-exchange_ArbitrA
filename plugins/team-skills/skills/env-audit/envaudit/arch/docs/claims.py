import ast
from io import BytesIO
import os
from pathlib import Path
import re
import tarfile

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext, path_inside
from envaudit.core import patterns
from envaudit.core.runner import git

from . import Document


STACK_PAIRS = (
    ("python-jose", "pyjwt", "jwt", "python"),
    ("LiveCharts2", "OxyPlot", "charts", "csharp"),
    ("requests", "httpx", "http_client", "python"),
    ("aiogram", "python-telegram-bot", "telegram_bot", "python"),
    ("psycopg2", "asyncpg", "postgresql", "python"),
)
ROOT_STATUS_FILES = frozenset({"CLAUDE.md", "AGENTS.md", "README.md"})
BACKTICK = re.compile(r"`([^`\r\n]+)`")
PYTHON_VERSION = re.compile(r"\bPython\s+(3\.\d+)\b", re.IGNORECASE)
DOCKER_PYTHON = re.compile(
    r"^\s*FROM\s+python:(3\.\d+)(?:\b|[-@])", re.IGNORECASE | re.MULTILINE
)
THIN = re.compile(r"тонк\w*|\bthin\b", re.IGNORECASE)
UNRELATED_MARKER = (
    r"(?:отдельн\w+|не\s+связан\w*|standalone|separate|unrelated)"
)
UNRELATED_KIND = r"(?:модуль|пакет|сервис|module|package|service)"
UNRELATED_AFTER = re.compile(
    rf"^\s*[—–-]\s*[*_]*(?P<marker>{UNRELATED_MARKER})",
    re.IGNORECASE,
)
UNRELATED_BEFORE = re.compile(
    rf"(?P<marker>{UNRELATED_MARKER})[*_]*\s+{UNRELATED_KIND}\b"
    rf"(?P<gap>[^.!?]{{0,40}})$",
    re.IGNORECASE,
)
QUALIFIED_MODULE = re.compile(
    r"^(.+?\.py):{1,2}[A-Za-z_][\w.]*$", re.IGNORECASE
)
TEST_COUNT = re.compile(
    r"(?:\b(?P<before>\d+)\s+(?:тест(?:ов|а)?|tests?)\b|"
    r"\b(?:тест(?:ов|а)?|tests?)\s*[:=]?\s*(?P<after>\d+)\b)",
    re.IGNORECASE,
)
MANAGE_COMMAND = re.compile(
    r"\bmanage\.py\s+(?P<command>[\w-]+)\s+(?P<label>[\w.-]+)"
)


def _package_present(text: str, name: str) -> bool:
    normalized = re.escape(name).replace(r"\-", "[-_]")
    return re.search(rf"(?<![A-Za-z0-9_-]){normalized}(?![A-Za-z0-9_-])", text, re.IGNORECASE) is not None


def _manifest_kind(rel: str) -> str | None:
    name = Path(rel).name
    lower = name.lower()
    if (
        (lower.startswith("requirements") and lower.endswith(".txt"))
        or lower in {"pyproject.toml", "setup.py", "setup.cfg", "pipfile", "poetry.lock"}
    ):
        return "python"
    if lower.endswith(".csproj") or lower in {
        "directory.packages.props",
        "packages.config",
    }:
        return "csharp"
    return None


def _manifests(actx: ArchContext) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for entry in actx.files():
        kind = _manifest_kind(entry.rel)
        if kind is None:
            continue
        data = actx.read(entry)
        if data is None:
            continue
        result.setdefault(kind, []).append(
            (entry.rel, data.decode("utf-8", "replace"))
        )
    return result


def stack_contradictions(
    actx: ArchContext, documents: list[Document]
) -> list[dict]:
    manifests = _manifests(actx)
    result = []
    directions = [
        (claimed, alternative, role, language)
        for left, right, role, language in STACK_PAIRS
        for claimed, alternative in ((left, right), (right, left))
    ]
    for claimed, alternative, role, language in directions:
        language_manifests = manifests.get(language, [])
        if not language_manifests:
            continue
        if not any(_package_present(document.text, claimed) for document in documents):
            continue
        if any(_package_present(text, claimed) for _, text in language_manifests):
            continue
        for rel, text in language_manifests:
            if _package_present(text, alternative):
                result.append(
                    {
                        "doc_name": claimed,
                        "manifest_alternative": alternative,
                        "role": role,
                        "manifest_file": rel,
                    }
                )
    return result


def python_version_claims(
    actx: ArchContext, documents: list[Document]
) -> list[dict]:
    docker_versions = []
    for entry in actx.files():
        if not Path(entry.rel).name.startswith("Dockerfile"):
            continue
        data = actx.read(entry)
        if data is None:
            continue
        for match in DOCKER_PYTHON.finditer(data.decode("utf-8", "replace")):
            docker_versions.append((entry.rel, match.group(1)))
    result = []
    for document in documents:
        for number, line in enumerate(document.lines, 1):
            for match in PYTHON_VERSION.finditer(line):
                claimed = match.group(1)
                for dockerfile, actual in docker_versions:
                    if claimed != actual:
                        result.append(
                            {
                                "doc": document.rel,
                                "line": number,
                                "claimed": claimed,
                                "dockerfile": dockerfile,
                                "actual": actual,
                            }
                        )
    return result


def _prod_sloc(actx: ArchContext) -> int:
    size = actx.out.get("size", {})
    languages = size.get("by_language", {}) if isinstance(size, dict) else {}
    if isinstance(languages, dict):
        return sum(
            metric.get("prod_sloc", 0)
            for metric in languages.values()
            if isinstance(metric, dict) and isinstance(metric.get("prod_sloc"), int)
        )
    return 0


def _test_files(actx: ArchContext) -> int:
    python = actx.out.get("python", {})
    tests = python.get("tests", {}) if isinstance(python, dict) else {}
    files = tests.get("files") if isinstance(tests, dict) else None
    if isinstance(files, int) and not isinstance(files, bool):
        return files
    size = actx.out.get("size", {})
    languages = size.get("by_language", {}) if isinstance(size, dict) else {}
    if not isinstance(languages, dict):
        return 0
    return sum(
        metric.get("test_files", 0)
        for metric in languages.values()
        if isinstance(metric, dict) and isinstance(metric.get("test_files"), int)
    )


def _head_distinct(actx: ArchContext) -> int:
    if not actx.vcs:
        return 0
    result = git(actx.root, "archive", "--format=tar", "HEAD", timeout=180)
    if result.rc != 0:
        return 0
    found: set[bytes] = set()
    try:
        with tarfile.open(fileobj=BytesIO(result.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.size > 20 * 1024 * 1024:
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                data = stream.read()
                for match in patterns.find(data):
                    found.add(data[match.start : match.end])
    except (tarfile.TarError, OSError):
        return 0
    return len(found)


def _module_name(rel: str) -> str:
    path = Path(rel).with_suffix("")
    parts = list(path.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_index(actx: ArchContext) -> dict[str, set[str]]:
    cached = actx.cache.get("docs:import_index")
    if isinstance(cached, dict):
        return cached
    result: dict[str, set[str]] = {}
    for entry in actx.code_files(exts=frozenset({".py"})):
        if not actx.is_prod_path(entry.rel):
            continue
        data = actx.read(entry)
        if data is None:
            continue
        parsed = pyast.parse(data, entry.rel)
        if parsed is None:
            continue
        for imported, _, guarded in pyast.imports(parsed):
            if guarded or not imported:
                continue
            result.setdefault(imported.lstrip("."), set()).add(entry.rel)
    actx.cache["docs:import_index"] = result
    return result


def _fan_in(actx: ArchContext, rel: str) -> int:
    module = _module_name(rel)
    if not module:
        return 0
    importers = set()
    for imported, sources in _import_index(actx).items():
        if (
            imported == module
            or imported.startswith(module + ".")
            or module.startswith(imported + ".")
            or imported.rsplit(".", 1)[-1] == module.rsplit(".", 1)[-1]
        ):
            importers.update(sources)
    return len(importers)


def _project_module(actx: ArchContext, raw: str) -> str | None:
    raw = raw.strip()
    rel = raw.removeprefix("./")
    qualified = QUALIFIED_MODULE.match(rel)
    if qualified:
        rel = qualified.group(1)
    path = Path(rel.rstrip("/"))
    if (
        not rel
        or (raw.startswith(".") and not raw.startswith("./"))
        or any(character.isspace() for character in rel)
        or any(character in rel for character in "()")
        or not path.parts
        or any(part == ".." or part.startswith(".") for part in path.parts)
    ):
        return None
    root = actx.trees["primary"].path
    candidate = Path(os.path.abspath(root / path))
    if not path_inside(candidate, Path(os.path.abspath(root))):
        return None
    if candidate.is_dir() and (candidate / "__init__.py").is_file():
        return rel
    if candidate.is_file() and candidate.suffix.lower() == ".py":
        return rel
    return None


def _unrelated_statement(line: str, match: re.Match[str]) -> bool:
    after = UNRELATED_AFTER.match(line[match.end() :])
    if after and after.start("marker") <= 40:
        return True
    before = UNRELATED_BEFORE.search(line[: match.start()])
    if before and match.start() - before.end("marker") <= 40:
        return True
    return False


def _claim(
    claim: str,
    lang: str,
    document: Document,
    line: int,
    evidence: dict,
) -> dict:
    return {
        "claim": claim,
        "lang": lang,
        "doc": document.rel,
        "line": line,
        "evidence": evidence,
    }


def _root_status_claims(
    actx: ArchContext, documents: list[Document]
) -> list[dict]:
    prod_sloc = _prod_sloc(actx)
    test_files = _test_files(actx)
    tree = actx.out.get("tree", {})
    vcs = tree.get("vcs", {}) if isinstance(tree, dict) else {}
    vcs_present = vcs.get("present") is True if isinstance(vcs, dict) else False
    relevant = [
        document
        for document in documents
        if "/" not in document.rel and Path(document.rel).name in ROOT_STATUS_FILES
    ]
    needs_head_scan = any(
        re.search(r"no secrets (?:are )?committed|секреты не коммит\w+", line, re.IGNORECASE)
        for document in relevant
        for line in document.lines
    )
    head_distinct = _head_distinct(actx) if needs_head_scan else 0
    result = []
    patterns_by_claim = (
        (
            "no_code",
            re.compile(
                r"кода ещё нет|только документация|стадия проектирования|no code yet",
                re.IGNORECASE,
            ),
            prod_sloc > 0,
            {"prod_sloc": prod_sloc},
        ),
        (
            "no_git",
            re.compile(r"\bno git\b|not (?:under|in) git|без git|нет git", re.IGNORECASE),
            vcs_present,
            {"vcs.present": vcs_present},
        ),
        (
            "no_tests",
            re.compile(r"no (?:build,? )?tests?|тестов нет|нет тестов", re.IGNORECASE),
            test_files > 0,
            {"tests.files": test_files},
        ),
        (
            "no_secrets",
            re.compile(r"no secrets (?:are )?committed|секреты не коммит\w+", re.IGNORECASE),
            head_distinct > 0,
            {"head_distinct": head_distinct},
        ),
    )
    for document in relevant:
        for number, line in enumerate(document.lines, 1):
            for claim, regex, contradicted, evidence in patterns_by_claim:
                match = regex.search(line)
                if match and contradicted:
                    lang = "ru" if re.search(r"[А-Яа-яЁё]", match.group(0)) else "en"
                    result.append(_claim(claim, lang, document, number, evidence))
            for match in BACKTICK.finditer(line):
                if not _unrelated_statement(line, match):
                    continue
                rel = _project_module(actx, match.group(1))
                if rel is None:
                    continue
                fan_in = _fan_in(actx, rel)
                if fan_in:
                    lang = "ru" if re.search(r"[А-Яа-яЁё]", line) else "en"
                    result.append(
                        _claim(
                            "unrelated_module",
                            lang,
                            document,
                            number,
                            {"path": rel, "fan_in": fan_in},
                        )
                    )
    return result


def _thin_claims(
    actx: ArchContext, documents: list[Document]
) -> tuple[list[dict], list[str]]:
    a11 = actx.rule_inputs.setdefault("A11", {})
    raw_candidates = a11.get("candidates")
    if not isinstance(raw_candidates, list):
        actx.skip("docs", "not_applicable", "A5.5")
        a11["thin_module_claims"] = []
        return [], []
    candidates = sorted({item.removeprefix("./") for item in raw_candidates if isinstance(item, str)})
    by_basename: dict[str, list[str]] = {}
    for candidate in candidates:
        by_basename.setdefault(Path(candidate).name, []).append(candidate)
    found = set()
    claims = []
    for document in documents:
        for number, line in enumerate(document.lines, 1):
            if not THIN.search(line):
                continue
            for match in BACKTICK.finditer(line):
                mentioned = match.group(1).strip().removeprefix("./")
                matches = [candidate for candidate in candidates if candidate == mentioned]
                if not matches:
                    matches = by_basename.get(Path(mentioned).name, [])
                for candidate in matches:
                    if candidate in found:
                        continue
                    found.add(candidate)
                    lang = "ru" if re.search(r"[А-Яа-яЁё]", line) else "en"
                    claims.append(
                        _claim(
                            "thin_module",
                            lang,
                            document,
                            number,
                            {"path": candidate},
                        )
                    )
    thin = sorted(found)
    a11["thin_module_claims"] = thin
    return claims, thin


def _collected(actx: ArchContext) -> int | None:
    python = actx.out.get("python")
    tests = python.get("tests") if isinstance(python, dict) else None
    value = tests.get("collected") if isinstance(tests, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _more_than_twice(left: int, right: int) -> bool:
    if left == right:
        return False
    smaller = min(left, right)
    larger = max(left, right)
    return smaller == 0 or larger > smaller * 2


def _test_count_claims(
    actx: ArchContext, documents: list[Document]
) -> list[dict]:
    collected = _collected(actx)
    if collected is None:
        actx.skip("docs", "not_applicable", "A5.6")
        return []
    result = []
    for document in documents:
        for number, line in enumerate(document.lines, 1):
            for match in TEST_COUNT.finditer(line):
                claimed = int(match.group("before") or match.group("after"))
                if not _more_than_twice(claimed, collected):
                    continue
                lang = "ru" if re.search(r"тест", match.group(0), re.IGNORECASE) else "en"
                result.append(
                    _claim(
                        "test_count",
                        lang,
                        document,
                        number,
                        {"doc": claimed, "collected": collected},
                    )
                )
    return result


def status_claims(actx: ArchContext, documents: list[Document]) -> list[dict]:
    result = _root_status_claims(actx, documents)
    thin, _ = _thin_claims(actx, documents)
    result.extend(thin)
    result.extend(_test_count_claims(actx, documents))
    return result


def _installed_apps(actx: ArchContext) -> set[str]:
    result = set()
    configs = {}
    for entry in actx.code_files(exts=frozenset({".py"})):
        data = actx.read(entry)
        if data is None:
            continue
        parsed = pyast.parse(data, entry.rel)
        if parsed is None:
            continue
        for node in ast.walk(parsed):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if any(isinstance(target, ast.Name) and target.id == "INSTALLED_APPS" for target in targets):
                    try:
                        items = ast.literal_eval(value)
                    except (ValueError, TypeError):
                        items = []
                    if isinstance(items, (list, tuple)):
                        for item in items:
                            if isinstance(item, str):
                                result.add(item)
                if any(isinstance(target, ast.Name) and target.id == "name" for target in targets):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        configs[entry.rel] = value.value
            if isinstance(node, ast.ClassDef):
                label = None
                name = None
                for child in node.body:
                    if not isinstance(child, ast.Assign) or len(child.targets) != 1:
                        continue
                    target = child.targets[0]
                    if not isinstance(target, ast.Name) or not isinstance(child.value, ast.Constant):
                        continue
                    if target.id == "label" and isinstance(child.value.value, str):
                        label = child.value.value
                    if target.id == "name" and isinstance(child.value.value, str):
                        name = child.value.value
                if label:
                    result.add(label)
                if name:
                    result.add(name)
    expanded = set(result)
    for item in result:
        parts = item.split(".")
        expanded.add(parts[0])
        if parts:
            expanded.add(parts[-1])
        if len(parts) >= 2 and parts[-2] == "apps":
            expanded.add(parts[-3] if len(parts) >= 3 else parts[0])
    expanded.update(configs.values())
    return expanded


def app_label_mismatches(
    actx: ArchContext, documents: list[Document]
) -> list[dict]:
    installed = _installed_apps(actx)
    if not installed:
        return []
    result = []
    for document in documents:
        for number, line in enumerate(document.lines, 1):
            for match in MANAGE_COMMAND.finditer(line):
                label = match.group("label").rstrip(".,;:")
                if label.startswith("-") or label in installed:
                    continue
                result.append(
                    {
                        "doc": document.rel,
                        "line": number,
                        "command": match.group("command"),
                        "label": label,
                    }
                )
    return result
