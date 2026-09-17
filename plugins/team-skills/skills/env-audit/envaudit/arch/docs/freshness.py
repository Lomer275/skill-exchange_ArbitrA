from pathlib import Path
import re

from envaudit.arch.context import ArchContext
from envaudit.core.runner import git


CODE_SUFFIXES = frozenset(
    {".py", ".sh", ".php", ".js", ".jsx", ".ts", ".tsx", ".cs", ".sql", ".ps1"}
)
COMMIT = re.compile(rb"^[0-9a-f]{40}$")


def _is_status_doc(rel: str) -> bool:
    name = Path(rel).name.lower()
    return Path(rel).suffix.lower() == ".md" and (
        name == "readme.md"
        or "handoff" in name
        or "changelog" in name
        or "architecture" in name
    )


def _commits_since(actx: ArchContext, revision: str) -> tuple[int, int]:
    result = git(
        actx.root,
        "log",
        "--format=%H",
        "--name-only",
        f"{revision}..HEAD",
        timeout=180,
    )
    if result.rc != 0:
        return 0, 0
    code_commits = set()
    status_commits = set()
    current: str | None = None
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if COMMIT.fullmatch(line):
            current = line.decode("ascii")
            continue
        if not line or current is None:
            continue
        rel = line.decode("utf-8", "surrogateescape")
        if Path(rel).suffix.lower() in CODE_SUFFIXES:
            code_commits.add(current)
        if _is_status_doc(rel):
            status_commits.add(current)
    return len(code_commits), len(status_commits)


def collect(actx: ArchContext) -> list[dict]:
    documents = sorted(
        entry.rel for entry in actx.files() if _is_status_doc(entry.rel)
    )
    if not actx.vcs:
        actx.skip("docs", "no_vcs", "A6")
        return []
    output = []
    for rel in documents:
        revision_result = git(
            actx.root,
            "log",
            "-1",
            "--format=%H%x00%cI",
            "--",
            rel,
        )
        raw = revision_result.stdout.strip()
        if revision_result.rc != 0 or b"\x00" not in raw:
            output.append(
                {
                    "doc": rel,
                    "last_commit_at": None,
                    "code_commits_since": None,
                    "status_doc_commits_since": None,
                }
            )
            continue
        revision_raw, date_raw = raw.split(b"\x00", 1)
        revision = revision_raw.decode("ascii", "replace")
        code_commits, status_commits = _commits_since(actx, revision)
        output.append(
            {
                "doc": rel,
                "last_commit_at": date_raw.decode("ascii", "replace"),
                "code_commits_since": code_commits,
                "status_doc_commits_since": status_commits,
            }
        )
    return output
