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


def test_no_run_wins_over_outside(fake_home, tmp_path, monkeypatch):
    out_dir, _document = _case(fake_home, tmp_path, monkeypatch, "no-run-outside")
    outside = fake_home / ".claude" / "CLAUDE.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("background change\n", encoding="utf-8")

    result = build_verdict(out_dir / "sandbox.json")

    expected = {"status": "not_checked", "reason": "no_run"}
    assert result["handoff"] == expected
    assert result["changelog"] == expected
    assert "~/.claude/CLAUDE.md" in result["outside_changes"]["created"]
    cleanup(out_dir / "sandbox.json")


def test_outside_change_outside_window_is_not_violation(
    fake_home, tmp_path, monkeypatch
):
    outside = fake_home / ".claude" / "CLAUDE.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("before\n", encoding="utf-8")
    out_dir, _document = _case(fake_home, tmp_path, monkeypatch, "late-outside")
    started = time.time()
    finished = started + 1
    write_run(out_dir / "run.json", started_at=started, finished_at=finished)
    outside.write_text("after\n", encoding="utf-8")
    late = finished + 6
    os.utime(outside, (late, late))

    result = build_verdict(out_dir / "sandbox.json")

    assert result["handoff"]["status"] != "not_isolated"
    assert "~/.claude/CLAUDE.md" in result["outside_changes_out_of_window"]
    assert result["outside_changes"]["modified"] == []
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
    write_run(out_dir / "run.json", started_at=time.time())
    result = build_verdict(out_dir / "sandbox.json")

    assert document["snapshot_truncated"] is True
    assert result["snapshot_truncated"] is True
    assert result["handoff"] == {
        "status": "not_checked",
        "reason": "snapshot_truncated",
    }
    cleanup(out_dir / "sandbox.json")


def test_noise_paths_ignored(fake_home, tmp_path, monkeypatch):
    unique = f"claude-{os.getuid()}-{uuid.uuid4().hex}"
    outside_dir = Path("/tmp") / unique
    outside_dir.mkdir()
    tmp_changed = outside_dir / "changed"
    tmp_changed.write_text("before\n", encoding="utf-8")
    tmp_deleted = outside_dir / "deleted"
    tmp_deleted.write_text("before\n", encoding="utf-8")
    synced = fake_home / ".claude" / "skills" / "synced" / "session"
    synced.mkdir(parents=True)
    synced_changed = synced / "changed.json"
    synced_changed.write_text("before\n", encoding="utf-8")
    synced_deleted = synced / "deleted.json"
    synced_deleted.write_text("before\n", encoding="utf-8")
    protected = fake_home / ".claude" / "CLAUDE.md"
    protected.write_text("before\n", encoding="utf-8")
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
        finished = started + 1
        write_run(out_dir / "run.json", started_at=started, finished_at=finished)
        tmp_changed.write_text("after\n", encoding="utf-8")
        synced_changed.write_text("after\n", encoding="utf-8")
        protected.write_text("after\n", encoding="utf-8")
        changed = started + 0.5
        for path in (tmp_changed, synced_changed, protected):
            os.utime(path, (changed, changed))
        tmp_deleted.unlink()
        synced_deleted.unlink()

        result = build_verdict(out_dir / "sandbox.json")

        assert str(tmp_changed) in result["outside_changes"]["modified"]
        assert str(tmp_deleted) in result["outside_changes"]["deleted"]
        assert "~/.claude/skills/synced/session/changed.json" in result["outside_changes"]["modified"]
        assert "~/.claude/skills/synced/session/deleted.json" in result["outside_changes"]["deleted"]
        assert result["handoff"]["paths"] == ["~/.claude/CLAUDE.md"]
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
    write_run(out_dir / "run.json", started_at=time.time())

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
