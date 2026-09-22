import json
import os
import time

from envaudit.core.context import Context, Flags
from envaudit.sections import secrets

from .canaries import canary, fragments


def _context(home):
    started = time.time()
    return Context(Flags(), home, [], started, started + 300)


def test_recent_transcript_found_old_transcript_skipped(fake_home):
    directory = fake_home / ".claude" / "projects" / "project"
    directory.mkdir(parents=True)
    recent = directory / "recent.jsonl"
    recent.write_text(canary("bitrix_webhook"), encoding="utf-8")
    old = directory / "old.jsonl"
    old.write_text(canary("github_token"), encoding="utf-8")
    old_time = time.time() - 31 * 24 * 60 * 60
    os.utime(old, (old_time, old_time))

    item = secrets._scan_agent_histories(
        _context(fake_home), fake_home / ".codex"
    )["claude_transcripts"]

    assert item["present"] is True
    assert item["files_scanned"] == 1
    assert item["files_with_hits"] == 1
    assert item["by_class"] == {"bitrix_webhook": 1}
    assert item["paths_sample"] == ["~/.claude/projects/project/recent.jsonl"]
    assert item["window_days"] == 30
    assert item["lower_bound"] is True


def test_agent_history_value_not_in_json_output(run_collect, fake_home, tmp_path):
    value = canary("github_token", 47)
    transcript = fake_home / ".claude" / "projects" / "project" / "recent.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(value, encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()

    result = run_collect("--root", root, "--only", "secrets")

    assert result.rc == 0
    assert result.data["sections"]["secrets"]["agent_histories"][
        "claude_transcripts"
    ]["by_class"] == {"github_token": 1}
    assert all(part not in result.stdout for part in fragments(value))


def test_agent_history_byte_cap_sets_truncated(fake_home):
    transcript = fake_home / ".claude" / "projects" / "project" / "large.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(b"x" * 100)
    ctx = _context(fake_home)

    item = secrets._scan_agent_histories(
        ctx,
        fake_home / ".codex",
        max_bytes=20,
        chunk_bytes=8,
    )["claude_transcripts"]

    assert item["bytes_read"] == 20
    assert item["truncated"] is True
    assert ctx.truncated is True
    assert {"section": "secrets", "reason": "size_cap", "details": "agent_histories"} in ctx.skipped


def test_agent_history_match_across_chunk_boundary(fake_home):
    value = b"rest/4242/k9m2n5p8q4r7s3t6"
    transcript = fake_home / ".claude" / "projects" / "project" / "boundary.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(b"x" * 28 + b" " + value)

    item = secrets._scan_agent_histories(
        _context(fake_home),
        fake_home / ".codex",
        chunk_bytes=32,
    )["claude_transcripts"]

    assert item["files_with_hits"] == 1
    assert item["by_class"] == {"bitrix_webhook": 1}


def test_agent_history_missing_locations_are_explicit(fake_home):
    result = secrets._scan_agent_histories(
        _context(fake_home), fake_home / ".codex"
    )

    assert set(result) == {
        "claude_transcripts",
        "claude_subagents",
        "codex_sessions",
    }
    assert all(item["present"] is False for item in result.values())
    assert all(item["files_scanned"] == 0 for item in result.values())
    assert json.dumps(result)
