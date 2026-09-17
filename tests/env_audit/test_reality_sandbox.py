import json
import os
from pathlib import Path
import shutil
import uuid

import pytest

from envaudit.reality.cli import cleanup, command_view, main, run_agent
from envaudit.reality import snapshot
from envaudit.reality.sandbox import prepare

from .canaries import canary, fragments
from .reality_builders import (
    facts_document,
    install_fake_tools,
    isolate_host,
    irina_like,
    write_facts,
)


@pytest.fixture(autouse=True)
def _fake_host_commands(monkeypatch, tmp_path):
    install_fake_tools(monkeypatch, tmp_path)


def _prepared(fake_home, tmp_path, monkeypatch, *, task_dir=False):
    isolate_host(monkeypatch, fake_home, tmp_path)
    root = irina_like(fake_home / "projects" / "sandbox", task_dir=task_dir)
    out_dir = tmp_path / "result"
    document = prepare(facts_document(fake_home, root), root, out_dir)
    return root, out_dir, document


def test_prepare_copies_skeleton_only(fake_home, tmp_path, monkeypatch):
    isolate_host(monkeypatch, fake_home, tmp_path)
    root = irina_like(fake_home / "projects" / "skeleton")
    (root / ".secrets").mkdir()
    (root / ".secrets" / "value.txt").write_text("private material\n", encoding="utf-8")
    (root / "n8n").mkdir()
    (root / "n8n" / "big.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.env"
    outside.write_text("outside\n", encoding="utf-8")
    os.symlink(outside, root / ".env")
    out_dir = tmp_path / "result"

    document = prepare(facts_document(fake_home, root), root, out_dir)
    sandbox = Path(document["sandbox"])

    assert (sandbox / "README.md").is_file()
    assert (sandbox / "CLAUDE.md").is_file()
    assert (sandbox / "docs" / "CRM-HANDOFF.md").is_file()
    assert len(list((sandbox / "handoffs").glob("HANDOFF_*.md"))) == 5
    assert not (sandbox / ".git").exists()
    assert not (sandbox / ".secrets").exists()
    assert not (sandbox / "n8n").exists()
    assert not (sandbox / "app.py").exists()
    assert ".env" in document["skipped_symlinks"]
    cleanup(out_dir / "sandbox.json")


def test_prepare_excludes_secret_files(fake_home, tmp_path, monkeypatch):
    isolate_host(monkeypatch, fake_home, tmp_path)
    root = irina_like(fake_home / "projects" / "excluded")
    sample = canary("openai_key", seed=462)
    settings = root / ".claude" / "settings.local.json"
    settings.write_text(json.dumps({"value": sample}), encoding="utf-8")
    out_dir = tmp_path / "result"

    document = prepare(facts_document(fake_home, root), root, out_dir)
    raw = (out_dir / "sandbox.json").read_text(encoding="utf-8")

    assert not (Path(document["sandbox"]) / ".claude" / "settings.local.json").exists()
    assert {item["path"] for item in document["excluded_secret"]} == {
        ".claude/settings.local.json"
    }
    assert all(part not in raw for part in fragments(sample))
    cleanup(out_dir / "sandbox.json")


def test_prepare_task_file_and_typo(fake_home, tmp_path, monkeypatch):
    _root, out_dir, document = _prepared(
        fake_home, tmp_path, monkeypatch, task_dir=True
    )
    sandbox = Path(document["sandbox"])

    assert document["has_task_file"] is True
    assert (sandbox / "docs" / "3. CRM-tasks" / "T999_env_audit_reality_check.md").is_file()
    assert document["typo_line"] in (sandbox / "README.md").read_text(encoding="utf-8")
    cleanup(out_dir / "sandbox.json")


def test_snapshot_survives_non_utf8_names(fake_home, tmp_path, monkeypatch, capsys):
    isolate_host(monkeypatch, fake_home, tmp_path)
    outside = fake_home / ".claude" / "skills"
    outside.mkdir(parents=True)
    bad_path = outside / os.fsdecode(b"bad-\xff.txt")
    bad_path.write_text("bad name\n", encoding="utf-8")
    root = irina_like(fake_home / "projects" / "non-utf8")
    facts = write_facts(tmp_path / "facts.json", facts_document(fake_home, root))
    out_dir = tmp_path / "result"

    code = main(
        [
            "prepare",
            "--facts",
            str(facts),
            "--root",
            str(root),
            "--out-dir",
            str(out_dir),
        ]
    )
    capsys.readouterr()
    before = json.loads((out_dir / "snapshot_before.json").read_text(encoding="utf-8"))
    safe_path = str(bad_path).encode("utf-8", "replace").decode("utf-8")

    assert code == 0
    assert before["outside"][safe_path]["path_sanitized"] is True
    cleanup(out_dir / "sandbox.json")


def test_snapshot_skips_other_users_tmp(fake_home, tmp_path, monkeypatch):
    outside = Path("/tmp") / f"claude-{os.getuid()}-{uuid.uuid4().hex}"
    outside.mkdir()
    (outside / "foreign").write_text("foreign\n", encoding="utf-8")
    original_stat = Path.stat

    def stat_with_other_owner(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path == outside:
            fields = list(value)
            fields[4] = os.getuid() + 1
            return os.stat_result(fields)
        return value

    try:
        isolate_host(monkeypatch, fake_home, tmp_path, tmp_pattern=str(outside))
        monkeypatch.setattr(Path, "stat", stat_with_other_owner)
        root = irina_like(fake_home / "projects" / "foreign-tmp")
        out_dir = tmp_path / "result"

        document = prepare(facts_document(fake_home, root), root, out_dir)
        before = json.loads(
            (out_dir / "snapshot_before.json").read_text(encoding="utf-8")
        )

        assert all(not path.startswith(str(outside)) for path in before["outside"])
        assert all(item["path"] != str(outside) for item in document["snapshot_skipped"])
        cleanup(out_dir / "sandbox.json")
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_profile_codex(fake_home, tmp_path, monkeypatch, capsys):
    isolate_host(monkeypatch, fake_home, tmp_path)
    root = irina_like(fake_home / "projects" / "codex")
    facts = write_facts(
        tmp_path / "facts.json",
        facts_document(fake_home, root, profile="codex"),
    )

    code = main(["prepare", "--facts", str(facts), "--root", str(root), "--out-dir", str(tmp_path / "out")])
    output = json.loads(capsys.readouterr().out)

    assert code == 5
    assert output == {"not_applicable": "profile=codex"}


def test_command_argv(fake_home, tmp_path, monkeypatch):
    _root, out_dir, document = _prepared(fake_home, tmp_path, monkeypatch)

    result = command_view(
        out_dir / "sandbox.json", max_turns=30, max_budget_usd=2, model=None
    )

    assert result["cwd"] == document["sandbox"]
    assert "--no-session-persistence" in result["argv"]
    assert "--strict-mcp-config" in result["argv"]
    assert "--disallowedTools" in result["argv"]
    assert any("Bash(git push:*)" in item for item in result["argv"])
    cleanup(out_dir / "sandbox.json")


def test_sandbox_arg_accepts_dir_and_file(
    fake_home, tmp_path, monkeypatch, capsys
):
    _root, out_dir, document = _prepared(fake_home, tmp_path, monkeypatch)

    file_code = main(["command", "--sandbox", str(out_dir / "sandbox.json")])
    file_output = json.loads(capsys.readouterr().out)
    dir_code = main(["command", "--sandbox", str(out_dir)])
    dir_output = json.loads(capsys.readouterr().out)
    missing = tmp_path / "missing"
    missing_code = main(["command", "--sandbox", str(missing)])
    missing_output = json.loads(capsys.readouterr().out)

    assert file_code == 0
    assert dir_code == 0
    assert file_output["cwd"] == document["sandbox"]
    assert dir_output == file_output
    assert missing_code == 2
    assert missing_output == {
        "error": f"не найден sandbox.json по пути {missing}"
    }
    cleanup(out_dir / "sandbox.json")


def test_run_requires_confirmed(fake_home, tmp_path, monkeypatch, capsys):
    _root, out_dir, _document = _prepared(fake_home, tmp_path, monkeypatch)
    marker = tmp_path / "called"
    monkeypatch.setenv("FAKE_CLAUDE_MARKER", str(marker))

    code = main(["run", "--sandbox", str(out_dir / "sandbox.json")])
    capsys.readouterr()

    assert code == 2
    assert not marker.exists()
    assert not (out_dir / "run.json").exists()
    cleanup(out_dir / "sandbox.json")


def test_result_text_redacted(fake_home, tmp_path, monkeypatch):
    _root, out_dir, _document = _prepared(fake_home, tmp_path, monkeypatch)
    sample = canary("anthropic_key", seed=462)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "max_turns")
    monkeypatch.setenv(
        "FAKE_RESULT",
        "Стоп-линии: запрещены сеть, коммиты и пуши.\n" + sample,
    )

    result = run_agent(
        out_dir / "sandbox.json", max_turns=40, max_budget_usd=1, model=None
    )

    assert "Стоп-линии" in result["result_text"]
    assert sample not in result["result_text"]
    assert "<redacted>" in result["result_text"]
    cleanup(out_dir / "sandbox.json")
