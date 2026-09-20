from dataclasses import dataclass
from pathlib import Path

from envaudit.arch.context import ArchContext
from envaudit.core.walk import FileEntry


@dataclass(frozen=True)
class Document:
    entry: FileEntry
    rel: str
    text: str

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()


def _in_docs_scope(rel: str) -> bool:
    parts = Path(rel).parts
    return bool(parts) and parts[0].lower() == "docs" and len(parts) <= 4


def _in_unsorted_docs(rel: str) -> bool:
    parts = Path(rel).parts
    return (
        bool(parts)
        and parts[0].lower() == "docs"
        and any("unsorted" in part.lower() for part in parts[1:-1])
    )


def is_agent_file(rel: str) -> bool:
    path = Path(rel)
    name = path.name
    lower = name.lower()
    if name == "CLAUDE.md":
        return True
    if path.parent != Path(".") and (
        not _in_docs_scope(rel) or _in_unsorted_docs(rel)
    ):
        return False
    return (
        name in {"AGENTS.md", "README.md"}
        or (lower.endswith(".md") and "architecture" in lower)
        or (lower.endswith(".md") and "handoff" in lower)
    )


def read_document(actx: ArchContext, entry: FileEntry) -> Document | None:
    data = actx.read(entry)
    if data is None:
        return None
    return Document(entry, entry.rel, data.decode("utf-8", "replace"))


def agent_documents(actx: ArchContext) -> list[Document]:
    result = []
    for entry in actx.files():
        if not is_agent_file(entry.rel):
            continue
        document = read_document(actx, entry)
        if document is not None:
            result.append(document)
    return result


def markdown_documents(actx: ArchContext) -> list[Document]:
    result = []
    for entry in actx.files():
        if Path(entry.rel).suffix.lower() != ".md":
            continue
        document = read_document(actx, entry)
        if document is not None:
            result.append(document)
    return result
