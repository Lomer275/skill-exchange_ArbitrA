from dataclasses import dataclass, field
from pathlib import Path
import time


SKIP_REASONS = (
    "budget",
    "linked_worktree",
    "no_vcs",
    "not_owner",
    "permission",
    "no_sibling",
    "flag_off",
    "not_applicable",
    "size_cap",
    "blocked",
    "no_definitions",
)


@dataclass
class Flags:
    budget_seconds: int = 300
    arch_root_seconds: int = 90
    max_text_mb: int = 2
    max_hash_mb: int = 20
    pytest_collect: bool = False
    pytest_python: str | None = None
    docker: bool = False
    sibling: str | None = None
    only: list[str] = field(default_factory=list)


@dataclass
class Context:
    flags: Flags
    home: Path
    roots: list[Path]
    started_at: float
    deadline: float
    skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    truncated: bool = False
    shared: dict[str, object] = field(default_factory=dict)

    def skip(self, section: str, reason: str, details: str | None = None) -> None:
        if reason not in SKIP_REASONS:
            raise ValueError(f"unknown skip reason: {reason}")
        self.skipped.append(
            {"section": section, "reason": reason, "details": details}
        )

    def error(self, section: str, kind: str) -> None:
        self.errors.append({"section": section, "kind": kind})

    def expired(self) -> bool:
        return time.time() >= self.deadline

    def mark_truncated(self) -> None:
        self.truncated = True
