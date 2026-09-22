import time

from envaudit.core.context import Context, Flags
from envaudit.core.runner import RunResult
from envaudit.core.skills_index import memory_dir_name
from envaudit.sections import instructions

from .schema_check import validate
from .skill_builders import write_memory
from .transcript_builders import (
    assistant_line,
    attachment_line,
    iso,
    user_line,
    write_session,
)


def _context(home, roots):
    started = time.time()
    ctx = Context(Flags(), home, roots, started, started + 300)
    ctx.shared["host"] = {"codex_home": str(home / ".codex")}
    return ctx


def _fake_worktrees(monkeypatch, root, worktree):
    monkeypatch.setattr(instructions.runner, "is_git_repo", lambda path: path == root)

    def git(path, *args, **_kwargs):
        if path == root and args == ("worktree", "list", "--porcelain"):
            output = f"worktree {root}\nHEAD abc\n\nworktree {worktree}\nHEAD def\n".encode()
            return RunResult(0, output, False, None)
        return RunResult(1, b"", False, None)

    monkeypatch.setattr(instructions.runner, "git", git)


def _sized_index(lines, size):
    prefix = "\n".join("x" for _ in range(lines - 1)) + "\n"
    assert len(prefix.encode()) <= size
    return prefix + "y" * (size - len(prefix.encode()))


def test_instruction_file_sizes(fake_home):
    root = fake_home / "projects" / "project"
    nested = root / "service"
    nested.mkdir(parents=True)
    (fake_home / ".claude" / "CLAUDE.md").write_text(
        "<!-- BEGIN team-context -->\nglobal\n", encoding="utf-8"
    )
    codex = fake_home / ".codex" / "AGENTS.md"
    codex.parent.mkdir(parents=True)
    codex.write_text("codex\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("one\ntwo\n", encoding="utf-8")
    (nested / "AGENTS.md").write_text("three\n", encoding="utf-8")

    section = instructions.collect(_context(fake_home, [root]))
    assert section["global"]["claude_md"]["team_context_blocks"] == 1
    project = section["projects"][str(root)]
    assert [item["rel"] for item in project["files"]] == [
        "CLAUDE.md",
        "service/AGENTS.md",
    ]
    assert project["total_bytes"] == 14


def test_memory_mapping_root_worktree_cwd(fake_home, monkeypatch):
    root = fake_home / "projects" / "project"
    worktree = fake_home / "worktrees" / "project-a"
    cwd = root / "nested"
    cwd.mkdir(parents=True)
    worktree.mkdir(parents=True)
    _fake_worktrees(monkeypatch, root, worktree)
    for path in (root, worktree, cwd):
        write_memory(fake_home, memory_dir_name(str(path)))
    write_memory(fake_home, "unmapped-memory")
    write_session(
        fake_home,
        str(root),
        "cwd",
        [user_line(iso(1), cwd=str(cwd))],
    )

    memory = instructions.collect(_context(fake_home, [root]))["memory"]
    matches = {item["name"]: item["matched_by"] for item in memory["dirs"]}
    assert matches[memory_dir_name(str(root))] == "root"
    assert matches[memory_dir_name(str(worktree))] == "worktree"
    assert matches[memory_dir_name(str(cwd))] == "cwd"
    assert memory["unmapped_memory_dirs"] == ["unmapped-memory"]
    assert len(memory["roots_with_multiple_dirs"][str(root)]) == 3


def test_memory_dir_collisions(fake_home):
    colliding = [
        fake_home / "projects" / "Экспресс-Банкрот",
        fake_home / "projects" / "Кредитный доктор",
    ]
    distinct = [
        fake_home / "projects" / "alpha",
        fake_home / "projects" / "bravo",
    ]
    for root in colliding + distinct:
        root.mkdir(parents=True)
    encoded = memory_dir_name(str(colliding[0]))
    assert encoded == memory_dir_name(str(colliding[1]))
    write_memory(fake_home, encoded)

    section = instructions.collect(_context(fake_home, colliding + distinct))

    assert section["memory_dir_collisions"] == [
        {
            "encoded": encoded,
            "roots": sorted(str(root) for root in colliding),
            "memory_exists": True,
        }
    ]


def test_index_limits(fake_home):
    root = fake_home / "projects" / "project"
    within_limit = root / "within-limit"
    over_limit = root / "over-limit"
    within_limit.mkdir(parents=True)
    over_limit.mkdir(parents=True)
    write_memory(
        fake_home,
        memory_dir_name(str(root)),
        index=_sized_index(201, 24_000),
    )
    write_memory(
        fake_home,
        memory_dir_name(str(within_limit)),
        index=_sized_index(100, 25_023),
    )
    write_memory(
        fake_home,
        memory_dir_name(str(over_limit)),
        index=_sized_index(100, 25_700),
    )
    write_session(
        fake_home,
        str(root),
        "within-limit",
        [user_line(iso(1), cwd=str(within_limit))],
    )
    write_session(
        fake_home,
        str(root),
        "over-limit",
        [user_line(iso(2), cwd=str(over_limit))],
    )

    items = {
        item["name"]: item
        for item in instructions.collect(_context(fake_home, [root]))["memory"]["dirs"]
    }
    first = items[memory_dir_name(str(root))]
    second = items[memory_dir_name(str(within_limit))]
    third = items[memory_dir_name(str(over_limit))]
    assert (first["index_over_lines"], first["index_over_bytes"]) == (True, False)
    assert (second["index_over_lines"], second["index_over_bytes"]) == (False, False)
    assert (third["index_over_lines"], third["index_over_bytes"]) == (False, True)


def test_start_context_median_and_exclusions(fake_home):
    root = fake_home / "projects" / "project"
    root.mkdir()
    for number, amount in enumerate((30_000, 43_000, 74_000), 1):
        write_session(
            fake_home,
            str(root),
            f"vscode-{number}",
            [
                user_line(
                    iso(number),
                    cwd=str(root),
                    entrypoint="claude-vscode",
                    compact=number == 1,
                ),
                assistant_line(
                    iso(number),
                    msg_id=f"m{number}",
                    req_id=f"r{number}",
                    usage=(amount, 0, 0, 0),
                    cwd=str(root),
                    entrypoint="claude-vscode",
                ),
            ],
        )
    write_session(
        fake_home,
        str(root),
        "synthetic",
        [
            user_line(iso(1), cwd=str(root), entrypoint="cli"),
            assistant_line(
                iso(1),
                msg_id="synthetic",
                req_id="synthetic",
                model="<synthetic>",
                cwd=str(root),
            ),
        ],
    )
    write_session(
        fake_home,
        str(root),
        "cli",
        [
            user_line(iso(1), cwd=str(root), entrypoint="cli"),
            assistant_line(
                iso(1),
                msg_id="side",
                req_id="side",
                usage=(10_000, 0, 0, 0),
                cwd=str(root),
                sidechain=True,
            ),
            assistant_line(
                iso(1),
                msg_id="main",
                req_id="main",
                usage=(50_000, 0, 0, 0),
                cwd=str(root),
            ),
        ],
    )

    facts = instructions.collect(_context(fake_home, [root]))["start_context"][str(root)]
    assert facts["by_entrypoint"]["claude-vscode"]["median"] == 43_000
    assert facts["by_entrypoint_fresh"]["claude-vscode"] == {
        "n": 2,
        "median": 58_500,
        "min": 43_000,
        "max": 74_000,
    }
    assert facts["by_entrypoint"]["cli"]["n"] == 1
    assert facts["by_entrypoint_fresh"]["cli"]["n"] == 1
    assert facts["excluded"] == 1
    assert facts["excluded_started_before_window"] == 0
    assert facts["history_marked"] == 1


def test_session_started_before_window_excluded(fake_home):
    root = fake_home / "projects" / "project"
    root.mkdir()
    write_session(
        fake_home,
        str(root),
        "started-before-window",
        [
            user_line(iso(45), cwd=str(root), entrypoint="claude-vscode"),
            attachment_line(iso(45), type="instructions", cwd=str(root)),
            assistant_line(
                iso(45),
                msg_id="old",
                req_id="old",
                usage=(40_000, 0, 0, 0),
                cwd=str(root),
                entrypoint="claude-vscode",
            ),
            assistant_line(
                iso(2),
                msg_id="recent",
                req_id="recent",
                usage=(900_000, 0, 0, 0),
                cwd=str(root),
                entrypoint="claude-vscode",
            ),
        ],
    )

    facts = instructions.collect(_context(fake_home, [root]))["start_context"][str(root)]
    assert facts["sessions_considered"] == 1
    assert facts["excluded_started_before_window"] == 1
    assert facts["by_entrypoint"] == {}
    assert facts["by_entrypoint_fresh"] == {}


def test_history_marked_only_for_continuations(fake_home):
    root = fake_home / "projects" / "project"
    root.mkdir()
    ordinary_follow_up = user_line(iso(1), cwd=str(root))
    ordinary_follow_up["parentUuid"] = "ordinary-start"
    continuation = user_line(iso(2), cwd=str(root))
    continuation["parentUuid"] = "earlier-file"
    write_session(
        fake_home,
        str(root),
        "ordinary",
        [
            user_line(iso(1), cwd=str(root)),
            attachment_line(iso(1), type="instructions", cwd=str(root)),
            ordinary_follow_up,
            assistant_line(iso(1), msg_id="ordinary", req_id="ordinary"),
        ],
    )
    write_session(
        fake_home,
        str(root),
        "continuation",
        [
            continuation,
            assistant_line(iso(2), msg_id="continuation", req_id="continuation"),
        ],
    )
    write_session(
        fake_home,
        str(root),
        "compact",
        [
            user_line(iso(3), cwd=str(root), compact=True),
            assistant_line(iso(3), msg_id="compact", req_id="compact"),
        ],
    )

    facts = instructions.collect(_context(fake_home, [root]))["start_context"][str(root)]
    assert facts["history_marked"] == 2
    assert facts["excluded_started_before_window"] == 0
    assert facts["by_entrypoint"]["cli"]["n"] == 3
    assert facts["by_entrypoint_fresh"]["cli"]["n"] == 1


def test_last_instructions_length(fake_home):
    root = fake_home / "projects" / "project"
    root.mkdir()
    write_session(
        fake_home,
        str(root),
        "instructions",
        [
            user_line(iso(1), cwd=str(root)),
            attachment_line(
                iso(1),
                type="instructions",
                rendered=["a" * 100, "b" * 100],
                files=["User", "Project", "Project"],
                cwd=str(root),
            ),
        ],
    )

    item = instructions.collect(_context(fake_home, [root]))["start_context"][str(root)]
    assert item["last_instructions"]["length"] == 200
    assert item["last_instructions"]["file_types"] == {"Project": 2, "User": 1}


def test_no_transcripts(fake_home):
    root = fake_home / "projects" / "project"
    root.mkdir()
    facts = instructions.collect(_context(fake_home, [root]))["start_context"][str(root)]
    assert facts == {
        "sessions_considered": 0,
        "excluded": 0,
        "excluded_started_before_window": 0,
        "history_marked": 0,
        "by_entrypoint": {},
        "by_entrypoint_fresh": {},
        "last_instructions": None,
    }


def test_schema_valid(fake_home, run_collect):
    root = fake_home / "projects" / "project"
    root.mkdir()
    result = run_collect("--root", root, "--only", "instructions")
    assert result.rc == 0
    validate(result.data)
