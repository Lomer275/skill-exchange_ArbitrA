from collections import Counter
from pathlib import Path
import re

from envaudit.arch.context import ArchContext

from . import Document, markdown_documents


TASK_REF = re.compile(r"(?<![A-Za-z0-9_])T\d{2,3}(?![A-Za-z0-9_])", re.IGNORECASE)
DONE = re.compile(r"СДЕЛАНО|\bdone\b|✅", re.IGNORECASE)
STATUS = re.compile(
    r"(?:\*\*(?:Статус|Status):\*\*|^\s*status:)\s*([^\s()]+)",
    re.IGNORECASE | re.MULTILINE,
)
CONVENTION = re.compile(
    r"active\s+(?:до\s+раскатки|until\s+rollout)", re.IGNORECASE
)
CODE_SUFFIXES = frozenset(
    {".py", ".sh", ".php", ".js", ".jsx", ".ts", ".tsx", ".cs", ".sql", ".ps1"}
)


def _in_a7_scope(rel: str) -> bool:
    parts = tuple(part.lower() for part in Path(rel).parts[:-1])
    if len(parts) >= 2 and parts[:2] == ("docs", "backlog"):
        return True
    return any(
        "specifications" in part or "tasks" in part for part in parts
    )


def _status(document: Document) -> str | None:
    match = STATUS.search(document.text)
    if match is None:
        return None
    return match.group(1).strip("*_`[]{}.,;:").lower()


def _task_file_ids(documents: list[Document]) -> set[str]:
    result = set()
    for document in documents:
        result.update(item.upper() for item in TASK_REF.findall(Path(document.rel).name))
    return result


def _done_ids(documents: list[Document]) -> set[str]:
    result = set()
    for document in documents:
        filename_ids = {item.upper() for item in TASK_REF.findall(Path(document.rel).name)}
        if filename_ids and DONE.search(document.text):
            result.update(filename_ids)
        for line in document.lines:
            if not DONE.search(line):
                continue
            result.update(item.upper() for item in TASK_REF.findall(line))
    return result


def _execution_refs(actx: ArchContext) -> set[str]:
    result = set()
    for entry in actx.files():
        path = Path(entry.rel)
        in_ci = (
            entry.rel.startswith(".github/workflows/")
            or entry.rel.startswith(".gitlab-ci")
            or path.name in {"Jenkinsfile", "azure-pipelines.yml"}
        )
        if not (
            path.suffix.lower() in CODE_SUFFIXES
            or not actx.is_prod_path(entry.rel)
            or in_ci
        ):
            continue
        if path.suffix.lower() == ".md":
            continue
        data = actx.read(entry)
        if data is None:
            continue
        text = data.decode("utf-8", "replace")
        result.update(item.upper() for item in TASK_REF.findall(text))
    return result


def _sibling_ids(actx: ArchContext) -> set[str]:
    sibling = actx.ctx.flags.sibling
    if not sibling:
        return set()
    root = Path(sibling).expanduser()
    if not root.is_dir():
        return set()
    result = set()
    try:
        paths = root.rglob("*.md")
        for path in paths:
            result.update(item.upper() for item in TASK_REF.findall(path.name))
    except OSError:
        return set()
    return result


def collect(actx: ArchContext, agent_documents: list[Document]) -> dict:
    documents = [
        document
        for document in markdown_documents(actx)
        if _in_a7_scope(document.rel)
    ]
    statuses = []
    for document in documents:
        status = _status(document)
        if status is not None:
            statuses.append((document, status))
    by_status = dict(sorted(Counter(status for _, status in statuses).items()))
    done = _done_ids(documents)
    execution = _execution_refs(actx)
    completed = done | execution
    task_files = _task_file_ids(documents)
    draft = []
    active = []
    refs_without_file = set()
    inline_documented = False
    local_ids = set(task_files)
    for document, status in statuses:
        refs = {item.upper() for item in TASK_REF.findall(document.text)}
        local_ids.update(refs)
        missing = refs - task_files
        if missing and any(
            re.search(rf"(?:^|\s){re.escape(item)}(?:\s|[:.—-])", document.text, re.IGNORECASE | re.MULTILINE)
            for item in missing
        ):
            inline_documented = True
        refs_without_file.update(missing)
        if status == "draft" and refs & completed:
            draft.append(document.rel)
        if (
            status == "active"
            and refs
            and refs <= completed
        ):
            active.append(document.rel)
    convention = any(
        CONVENTION.search(document.text)
        for document in agent_documents
        if Path(document.rel).name == "CLAUDE.md"
        or "handoff" in Path(document.rel).name.lower()
    )
    if convention:
        active = []
    sibling_ids = _sibling_ids(actx)
    return {
        "by_status": by_status,
        "draft_with_done_tasks": sorted(draft),
        "active_with_all_done": sorted(active),
        "status_convention_declared": convention,
        "task_refs_without_file": sorted(refs_without_file),
        "tasks_inline_documented": inline_documented,
        "numbering_collisions": sorted(local_ids & sibling_ids),
    }
