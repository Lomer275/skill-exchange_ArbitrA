import json
import os
from pathlib import Path
import shutil
import time
import uuid

import jsonschema
import pytest

from envaudit.reality import snapshot
from envaudit.reality.cli import cleanup, run_agent
from envaudit.reality.sandbox import prepare
from envaudit.reality.verdict import build_verdict

from .conftest import SKILL_DIR
from .reality_builders import (
    facts_document,
    install_fake_tools,
    isolate_host,
    irina_like,
    write_run,
)


@pytest.fixture(autouse=True)
def _fake_host_commands(monkeypatch, tmp_path):
    install_fake_tools(monkeypatch, tmp_path)


def _case(
    fake_home,
    tmp_path,
    monkeypatch,
    name="case",
    *,
    changelog=True,
    task_dir=False,
    changelog_writers=None,
):
    isolate_host(monkeypatch, fake_home, tmp_path)
    root = irina_like(
        fake_home / "projects" / name,
        changelog=changelog,
        task_dir=task_dir,
    )
    out_dir = tmp_path / (name + "-result")
    document = prepare(
        facts_document(
            fake_home,
            root,
            changelog=changelog,
            changelog_writers=changelog_writers,
        ),
        root,
        out_dir,
    )
    return out_dir, document


def _run(out_dir, monkeypatch, mode):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    return run_agent(
        out_dir / "sandbox.json", max_turns=40, max_budget_usd=1, model=None
    )


def test_works(fake_home, tmp_path, monkeypatch):
    out_dir, _document = _case(fake_home, tmp_path, monkeypatch, "works")
    _run(out_dir, monkeypatch, "works")

    result = build_verdict(out_dir / "sandbox.json")

    assert result["handoff"]["status"] == "works"
    assert result["readme_typo_fixed"] is True
    cleanup(out_dir / "sandbox.json")


def test_not_working_journal(fake_home, tmp_path, monkeypatch):
    out_dir, _document = _case(fake_home, tmp_path, monkeypatch, "journal")
    _run(out_dir, monkeypatch, "journal")

    result = build_verdict(out_dir / "sandbox.json")

    assert result["handoff"]["status"] == "not_working"
    assert result["handoff"]["written_to"] == ["handoffs/HANDOFF_2026-09-17.md"]
    cleanup(out_dir / "sandbox.json")


def test_not_isolated(fake_home, tmp_path, monkeypatch):
    out_dir, _document = _case(fake_home, tmp_path, monkeypatch, "leak")
    _run(out_dir, monkeypatch, "leak")

    result = build_verdict(out_dir / "sandbox.json")

    assert result["handoff"]["status"] == "not_isolated"
    assert "~/.claude/CLAUDE.md" in result["handoff"]["paths"]
    cleanup(out_dir / "sandbox.json")


@pytest.mark.parametrize(
    ("mode", "reason"),
    (("max_turns", "max_turns"), ("denied", "permission_denied"), (None, "no_run")),
)
def test_not_checked_reasons(fake_home, tmp_path, monkeypatch, mode, reason):
    out_dir, _document = _case(fake_home, tmp_path, monkeypatch, "reason-" + reason)
    if mode is not None:
        _run(out_dir, monkeypatch, mode)

    result = build_verdict(out_dir / "sandbox.json")

    assert result["handoff"] == {"status": "not_checked", "reason": reason}
    cleanup(out_dir / "sandbox.json")


def test_snapshot_truncation_marks_not_checked(fake_home, tmp_path, monkeypatch):
    isolate_host(monkeypatch, fake_home, tmp_path)
    monkeypatch.setattr(snapshot, "MAX_FILES", 1)
    root = irina_like(fake_home / "projects" / "truncated")
    out_dir = tmp_path / "truncated-result"

    document = prepare(facts_document(fake_home, root), root, out_dir)
    result = build_verdict(out_dir / "sandbox.json")

    assert document["snapshot_truncated"] is True
    assert result["snapshot_truncated"] is True
    assert result["handoff"] == {
        "status": "not_checked",
        "reason": "snapshot_truncated",
    }
    cleanup(out_dir / "sandbox.json")


def test_tmp_claude_writes_ignored_deletes_flagged(fake_home, tmp_path, monkeypatch):
    unique = f"claude-{os.getuid()}-{uuid.uuid4().hex}"
    outside_dir = Path("/tmp") / unique
    outside_dir.mkdir()
    old = outside_dir / "old"
    old.write_text("old\n", encoding="utf-8")
    old_time = time.time() - 120
    os.utime(old, (old_time, old_time))
    try:
        isolate_host(
            monkeypatch,
            fake_home,
            tmp_path,
            tmp_pattern=str(Path("/tmp") / (unique + "*")),
        )
        root = irina_like(fake_home / "projects" / "tmp-change")
        out_dir = tmp_path / "tmp-change-result"
        prepare(facts_document(fake_home, root), root, out_dir)
        started = time.time()
        write_run(out_dir / "run.json", started_at=started)
        (outside_dir / "new").write_text("new\n", encoding="utf-8")
        old.unlink()

        result = build_verdict(out_dir / "sandbox.json")

        assert result["outside_changes"]["created"] == []
        assert str(old) in result["outside_changes"]["deleted"]
        assert result["handoff"]["status"] == "not_isolated"
        cleanup(out_dir / "sandbox.json")
    finally:
        shutil.rmtree(outside_dir, ignore_errors=True)


def test_changelog_no_path(fake_home, tmp_path, monkeypatch):
    out_dir, _document = _case(
        fake_home,
        tmp_path,
        monkeypatch,
        "no-changelog",
        changelog=True,
        changelog_writers=[],
    )

    result = build_verdict(out_dir / "sandbox.json")

    assert result["changelog"] == {
        "status": "not_checked",
        "reason": "no_changelog_path",
    }
    cleanup(out_dir / "sandbox.json")


def test_cleanup_idempotent(fake_home, tmp_path, monkeypatch):
    out_dir, document = _case(fake_home, tmp_path, monkeypatch, "cleanup")
    sandbox = Path(document["sandbox"])

    first = cleanup(out_dir / "sandbox.json")
    second = cleanup(out_dir / "sandbox.json")

    assert str(sandbox) in first["removed"]
    assert not sandbox.exists()
    assert second == {"removed": []}


def test_schema_valid(fake_home, tmp_path, monkeypatch):
    out_dir, document = _case(fake_home, tmp_path, monkeypatch, "schema")
    verdict = build_verdict(out_dir / "sandbox.json")
    sandbox_schema = json.loads(
        (SKILL_DIR / "schema" / "reality_sandbox.schema.json").read_text(encoding="utf-8")
    )
    verdict_schema = json.loads(
        (SKILL_DIR / "schema" / "reality_verdict.schema.json").read_text(encoding="utf-8")
    )

    jsonschema.Draft202012Validator.check_schema(sandbox_schema)
    jsonschema.Draft202012Validator(sandbox_schema).validate(document)
    jsonschema.Draft202012Validator.check_schema(verdict_schema)
    jsonschema.Draft202012Validator(verdict_schema).validate(verdict)
    cleanup(out_dir / "sandbox.json")
