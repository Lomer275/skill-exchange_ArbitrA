from pathlib import Path
import subprocess
import time

import pytest

from envaudit.arch.checks import classification, docs, gates, runtime, size, tree
from envaudit.arch.context import ArchContext
from envaudit.core.context import Context, Flags
from envaudit.core.runner import is_git_repo

from .arch_builders import (
    isolated_runtime,
    make_bare,
    make_repo,
    write_crontab_stub,
    write_systemctl_stub,
)
from .canaries import canary, fragments
from .schema_check import validate


def _arch(result, root: Path) -> dict:
    assert result.rc == 0, result.stdout
    validate(result.data)
    return result.data["sections"]["architecture"][str(root.resolve())]


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _direct_docs(
    root: Path,
    home: Path,
    *,
    collected: int | None = None,
    include_collected: bool = False,
    candidates: list[str] | None = None,
) -> tuple[dict, Context]:
    started = time.time()
    ctx = Context(
        flags=Flags(),
        home=home,
        roots=[root],
        started_at=started,
        deadline=started + 300,
    )
    output = {
        "schema": "env-audit/arch",
        "definitions_version": "3.0.0",
        "definitions": {},
        "rule_inputs": {},
        "blind_spots": [],
    }
    actx = ArchContext(
        ctx=ctx,
        root=root,
        vcs=is_git_repo(root),
        out=output,
        rule_inputs=output["rule_inputs"],
    )
    for check in (tree, runtime, classification, size, gates):
        check.run(actx)
    if include_collected:
        output["python"] = {"tests": {"collected": collected}}
    if candidates is not None:
        output["rule_inputs"]["A11"] = {"candidates": candidates}
    docs.run(actx)
    return output, ctx


def test_missing_path_tree_listing(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "tree-listing"
    (root / "Handler").mkdir(parents=True)
    (root / "CLAUDE.md").write_text(
        "Project tree:\n├── Tracker/\n└── Handler/\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert any(
        item["path"] == "Tracker/" and item["source"] == "tree_listing"
        for item in arch["docs"]["missing_paths"]
    )
    assert not any(
        item["path"] == "Handler/" for item in arch["docs"]["missing_paths"]
    )


def test_tree_listing_nested_and_comments(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "nested-tree"
    existing = (
        "max_bot/handlers/auth.py",
        "max_bot/handlers/chat.py",
        "max_bot/handlers/documents.py",
        "max_bot/handlers/my_deal.py",
        "max_bot/middlewares/auth.py",
        "max_bot/middlewares/debt.py",
        "tg_bot/handlers/menu/ai_chat.py",
        "tg_bot/handlers/menu/my_case.py",
        "tg_bot/handlers/utils.py",
    )
    for rel in existing:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text(
        """Project tree:
```text
max_bot/                    # MAX Platform bot
  ├── handlers/               # auth.py, chat.py, documents.py,
  │                           # my_deal.py, nps.py
  ├── middlewares/            # auth.py, debt.py
tg_bot/
  ├── handlers/
  │   ├── menu/               # ai_chat.py, my_case.py,
  │   └── utils.py
```
""",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["missing_paths"] == [
        {
            "doc": "CLAUDE.md",
            "line": 5,
            "path": "max_bot/handlers/nps.py",
            "source": "tree_listing",
            "resolved_on_other_branch": None,
        }
    ]


def test_backtick_and_fenced_paths(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "path-lines"
    root.mkdir()
    lines = [f"line {number}" for number in range(1, 28)]
    lines.extend(
        [
            "Run `scripts/probe.py`.",
            "```bash",
            "python3 scripts/probe.py",
            "```",
        ]
    )
    (root / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    found = [
        (item["line"], item["source"])
        for item in arch["docs"]["missing_paths"]
        if item["path"] == "scripts/probe.py"
    ]

    assert found == [(28, "backtick"), (30, "fenced")]


def test_path_trailing_punctuation(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "trailing-punctuation"
    (root / "bitrix").mkdir(parents=True)
    (root / "bitrix" / "files.py").write_text("\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text(
        "Use `bitrix/files.py,;:.)]»\"'`.\n", encoding="utf-8"
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["missing_paths"] == []


def test_tree_listing_repo_root_is_virtual(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "Arbitra_support"
    files = (
        "max_bot/handlers/message.py",
        "max_bot/middlewares/auth.py",
    )
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n", encoding="utf-8")
    (root / "README.md").write_text(
        """Project tree:
```text
Arbitra_support/
├── max_bot/
│   ├── handlers/
│   │   └── message.py
│   └── middlewares/
│       └── auth.py
```
""",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["missing_paths"] == []


def test_path_resolves_by_tree_suffix(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "suffix-path"
    files = (
        "local/tools/ai_deal_assistant/lib/inn.php",
        "local/tools/ai_deal_assistant/lib/prompt.php",
        "local/tools/ai_deal_assistant/templates/widget.php",
    )
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<?php\n", encoding="utf-8")
    (root / "DA-HANDOFF.md").write_text(
        "Use `lib/inn.php`, `lib/prompt.php`, and `templates/widget.php`.\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["missing_paths"] == []


def test_prefixed_command_documents_resolve(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "command-documents"
    (root / "docs").mkdir(parents=True)
    (root / "SUP-HANDOFF.md").write_text("State.\n", encoding="utf-8")
    (root / "SUP-CHANGELOG.md").write_text("Changes.\n", encoding="utf-8")
    (root / "docs" / "SUP-architecture.md").write_text(
        "Architecture.\n", encoding="utf-8"
    )
    (root / "CLAUDE.md").write_text(
        "Read `HANDOFF.md`, `CHANGELOG.md`, and `architecture.md`.\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["missing_paths"] == []


def test_skips(tmp_path: Path, run_collect) -> None:
    root = make_repo(
        tmp_path / "skips",
        {
            ".gitignore": ".env\n",
            "CLAUDE.md": (
                "`/opt/ccm`\n"
                "`https://x/y.py`\n"
                "`glet234/arbitra-support`\n"
                "`.env`\n"
                "`dev_restore.sh` выкинут\n"
            ),
        },
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["missing_paths"] == []


def test_non_paths_and_basenames(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "non-paths"
    (root / "tg_bot").mkdir(parents=True)
    (root / "local" / "tools" / "x").mkdir(parents=True)
    (root / "tg_bot" / "enums.py").write_text("\n", encoding="utf-8")
    (root / "local" / "tools" / "x" / "controller.php").write_text(
        "<?php\n", encoding="utf-8"
    )
    (root / "CLAUDE.md").write_text(
        """```bash
python3 -m venv .venv && pip install
php ..._install.php
```
`_done.md`
`tg_bot/enums.py:States`
`controller.php`
""",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["missing_paths"] == []


def test_resolved_on_other_branch(tmp_path: Path, run_collect) -> None:
    remote = make_bare(tmp_path / "remote.git")
    root = make_repo(
        tmp_path / "branch-path",
        {"CLAUDE.md": "Use `future.py`.\n"},
        remote=remote,
    )
    _git(root, "checkout", "-b", "dev")
    (root / "future.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "future.py")
    _git(root, "commit", "-m", "future file")
    _git(root, "push", "-u", "origin", "dev")
    _git(root, "checkout", "main")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    item = next(
        item
        for item in arch["docs"]["missing_paths"]
        if item["path"] == "future.py"
    )

    assert item["resolved_on_other_branch"] == "origin/dev"


def test_stack_pair(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    (root / "README.md").write_text(
        "Используем python-jose.\n", encoding="utf-8"
    )
    (root / "requirements.txt").write_text("pyjwt==2.9.0\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["stack_contradictions"] == [
        {
            "doc_name": "python-jose",
            "manifest_alternative": "pyjwt",
            "role": "jwt",
            "manifest_file": "requirements.txt",
        }
    ]


def test_status_claims_ru_en(tmp_path: Path, run_collect) -> None:
    root = make_repo(
        tmp_path / "claims",
        {
            "README.md": "Кода ещё нет.\nТестов нет.\n",
            "CLAUDE.md": "This project has no git.\n",
            "app.py": "VALUE = 1\n",
            "tests/test_app.py": "def test_value():\n    assert True\n",
        },
    )

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)
    claims = {item["claim"]: item for item in arch["docs"]["status_claims"]}

    assert {"no_code", "no_git", "no_tests"} <= set(claims)
    assert claims["no_code"]["evidence"]["prod_sloc"] > 0
    assert claims["no_git"]["evidence"] == {"vcs.present": True}
    assert claims["no_tests"]["evidence"]["tests.files"] == 1
    assert "Кода ещё нет" not in result.stdout
    assert "This project has no git" not in result.stdout


def test_no_secrets_claim(tmp_path: Path, run_collect) -> None:
    probe = canary("openai_key", seed=458)
    root = make_repo(
        tmp_path / "head-scan",
        {
            "CLAUDE.md": "Секреты не коммитятся.\n",
            "fixture.txt": probe + "\n",
        },
    )

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)

    assert any(
        item["claim"] == "no_secrets"
        and item["evidence"]["head_distinct"] > 0
        for item in arch["docs"]["status_claims"]
    )
    assert all(fragment not in result.stdout for fragment in fragments(probe))


def test_unrelated_module_tight(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "unrelated"
    (root / "bitrix").mkdir(parents=True)
    (root / "bitrix" / "__init__.py").write_text("\n", encoding="utf-8")
    (root / "consumer.py").write_text("import bitrix\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text(
        "Каждый хендлер получает `user` — не делай отдельных запросов.\n"
        "`bitrix/` — отдельный пакет, с ботами не связан.\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    claims = [
        item
        for item in arch["docs"]["status_claims"]
        if item["claim"] == "unrelated_module"
    ]

    assert len(claims) == 1
    assert claims[0]["evidence"] == {"path": "bitrix/", "fan_in": 1}


def test_thin_module_claim(tmp_path: Path) -> None:
    root = tmp_path / "thin"
    root.mkdir()
    (root / "service.php").write_text("<?php\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text(
        "`service.php` — тонкий диспетчер.\n", encoding="utf-8"
    )

    output, _ = _direct_docs(
        root,
        tmp_path,
        candidates=["service.php"],
    )

    assert output["rule_inputs"]["A11"]["thin_module_claims"] == [
        "service.php"
    ]
    assert any(
        item["claim"] == "thin_module" for item in output["docs"]["status_claims"]
    )


@pytest.mark.parametrize(
    ("collected", "expected"),
    [(194, True), (None, False)],
)
def test_test_count_needs_collected(
    tmp_path: Path, collected: int | None, expected: bool
) -> None:
    root = tmp_path / ("collected" if collected is not None else "not-collected")
    root.mkdir()
    (root / "README.md").write_text("В проекте 20 тестов.\n", encoding="utf-8")

    output, _ = _direct_docs(
        root,
        tmp_path,
        collected=collected,
        include_collected=True,
    )
    claims = [
        item
        for item in output["docs"]["status_claims"]
        if item["claim"] == "test_count"
    ]

    assert bool(claims) is expected
    if claims:
        assert claims[0]["evidence"] == {"doc": 20, "collected": 194}


def test_a6_freshness(tmp_path: Path, run_collect) -> None:
    commits = [
        {
            "files": {"app.py": f"VALUE = {number}\n"},
            "message": f"code {number}",
        }
        for number in range(1, 13)
    ]
    root = make_repo(
        tmp_path / "freshness",
        {"HANDOFF.md": "Current state.\n", "app.py": "VALUE = 0\n"},
        commits=commits,
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    item = next(
        item for item in arch["docs"]["freshness"] if item["doc"] == "HANDOFF.md"
    )

    assert item["last_commit_at"] is not None
    assert item["code_commits_since"] == 12
    assert item["status_doc_commits_since"] == 0


def test_a7_draft_with_done_task(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "spec-status"
    (root / "docs" / "tasks").mkdir(parents=True)
    (root / "docs" / "specifications").mkdir(parents=True)
    (root / "tests").mkdir()
    spec = root / "docs" / "specifications" / "S03.md"
    spec.write_text(
        "# S03\n\n**Статус:** draft (review)\n\n- T13 implementation\n",
        encoding="utf-8",
    )
    (root / "docs" / "tasks" / "T13.md").write_text(
        "# T13\n\nСДЕЛАНО\n", encoding="utf-8"
    )
    (root / "tests" / "test_t13.py").write_text(
        "# T13\ndef test_done():\n    assert True\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["specs"]["draft_with_done_tasks"] == [
        spec.relative_to(root).as_posix()
    ]


def test_a7_scope_and_pyver_scope(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "scopes"
    specifications = root / "docs" / "2. SUP-specifications"
    tasks = root / "docs" / "3. SUP-tasks"
    backlog = root / "docs" / "backlog"
    unsorted = root / "docs" / "5. SUP-unsorted"
    for directory in (specifications, tasks, backlog, unsorted):
        directory.mkdir(parents=True)
    (specifications / "S01.md").write_text(
        "**Статус:** draft\n\n- T13 implementation\n", encoding="utf-8"
    )
    (tasks / "T13.md").write_text("СДЕЛАНО\n", encoding="utf-8")
    (backlog / "S02.md").write_text(
        "**Статус:** queued\n", encoding="utf-8"
    )
    (root / "SKILL.md").write_text(
        "**Статус:** rejected\nT99\n", encoding="utf-8"
    )
    (root / "docs" / "project-architecture.md").write_text(
        "**Статус:** active\nT13\n", encoding="utf-8"
    )
    (unsorted / "notes.md").write_text(
        "**Статус:** paused\nPython 3.9.\n", encoding="utf-8"
    )
    (root / "CLAUDE.md").write_text("Python 3.10.\n", encoding="utf-8")
    (root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["specs"]["by_status"] == {
        "draft": 1,
        "queued": 1,
    }
    assert arch["docs"]["specs"]["draft_with_done_tasks"] == [
        "docs/2. SUP-specifications/S01.md"
    ]
    assert {item["doc"] for item in arch["docs"]["python_version_claims"]} == {
        "CLAUDE.md"
    }


def test_python_version_ignores_unsorted_architecture(
    tmp_path: Path, run_collect
) -> None:
    root = tmp_path / "python-version-agent-files"
    unsorted = root / "docs" / "5. SUP-unsorted"
    unsorted.mkdir(parents=True)
    (unsorted / "dev1_server_architecture_and_access_2026-08-03.md").write_text(
        "Runtime Python 3.10.\n", encoding="utf-8"
    )
    (root / "CLAUDE.md").write_text("Project instructions.\n", encoding="utf-8")
    (root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["agent_files"] == ["CLAUDE.md"]
    assert arch["docs"]["python_version_claims"] == []


def test_a8_md_code_copy_diverged(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "md-copy"
    root.mkdir()
    code = []
    copied = []
    for number in range(10):
        code.append(f"def sample_{number}():\n    return {number}\n")
        returned = 999 if number == 7 else number
        copied.append(f"def sample_{number}():\n    return {returned}\n")
    (root / "module.py").write_text("\n".join(code), encoding="utf-8")
    (root / "guide.md").write_text(
        "# Examples\n\n```python\n" + "\n".join(copied) + "```\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    matches = arch["docs"]["md_code_copies"]

    assert any(
        item["function"] == "sample_7" and item["ratio"] < 1.0
        for item in matches
    )


def test_no_canonical_fields(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "locations"
    (root / ".claude" / "skills" / "close").mkdir(parents=True)
    (root / "HANDOFF.md").write_text("State.\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("Changes.\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text(
        "Read `HANDOFF.md`.\n", encoding="utf-8"
    )
    (root / ".claude" / "skills" / "close" / "SKILL.md").write_text(
        "Write docs/TEAM-HANDOFF.md.\n", encoding="utf-8"
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    locations = arch["docs"]["doc_locations"]

    assert locations["handoff_files"] == ["HANDOFF.md"]
    assert "HANDOFF.md" in locations["paths_named_in_agent_files"]
    assert not any(key.startswith("canonical_") for key in locations)


def test_python_version_and_app_label(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "versions-labels"
    root.mkdir()
    (root / "README.md").write_text(
        "Runtime Python 3.10.\nRun manage.py migrate missing_app.\n",
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (root / "settings.py").write_text(
        "INSTALLED_APPS = ['known_app']\n", encoding="utf-8"
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["python_version_claims"][0]["claimed"] == "3.10"
    assert arch["docs"]["python_version_claims"][0]["actual"] == "3.12"
    assert arch["docs"]["app_label_mismatches"][0]["label"] == "missing_app"


def test_host_runtime_stubs_do_not_change_docs(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    write_crontab_stub(
        isolated_runtime,
        ["*/5 * * * * cd /home/x/p && python3 run.py"],
    )
    write_systemctl_stub(
        isolated_runtime,
        {
            "outside.timer": "[Timer]\nOnCalendar=hourly\n",
            "outside.service": (
                "[Service]\nWorkingDirectory=/home/x/p\n"
                "ExecStart=/usr/bin/python3 /home/x/p/run.py\n"
            ),
        },
    )
    root = tmp_path / "host-isolation"
    root.mkdir()
    (root / "CLAUDE.md").write_text("Use `missing.py`.\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["docs"]["agent_files"] == ["CLAUDE.md"]
    assert arch["docs"]["missing_paths"][0]["path"] == "missing.py"


def test_schema_valid(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "schema"
    root.mkdir()
    (root / "CLAUDE.md").write_text("Use `missing.py`.\n", encoding="utf-8")
    (root / "README.md").write_text("Python 3.10.\n", encoding="utf-8")
    (root / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")

    result = run_collect("--only", "architecture", "--root", root)

    validate(result.data)
