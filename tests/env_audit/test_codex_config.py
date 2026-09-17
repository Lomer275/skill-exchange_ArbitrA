import json
import os
from pathlib import Path
from types import SimpleNamespace
import time

import jsonschema

from envaudit.core.context import Context, Flags
from envaudit.net.probe import TcpResult
from envaudit.sections import codex_config, memory_codex, network, onepassword

from .conftest import SKILL_DIR


def _context(home: Path) -> Context:
    started = time.time()
    ctx = Context(
        flags=Flags(),
        home=home,
        roots=[home],
        started_at=started,
        deadline=started + 300,
    )
    ctx.shared["host"] = {
        "codex_home": str(home / ".codex"),
        "codex_version": "0.146.0",
    }
    return ctx


def _config(home: Path) -> Path:
    codex_home = home / ".codex"
    codex_home.mkdir()
    path = codex_home / "config.toml"
    path.write_text(
        'model = "gpt-5.5"\n'
        'approval_policy = "never"\n'
        'sandbox_mode = "danger-full-access"\n'
        'model_reasoning_effort = "high"\n'
        "[profiles.fast]\n"
        'model = "gpt-fast"\n'
        'sandbox_mode = "workspace-write"\n'
        "[sandbox_workspace_write]\n"
        "network_access = true\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_parse_top_and_profiles(tmp_path):
    _config(tmp_path)
    result = codex_config.collect(_context(tmp_path))
    assert result["top"] == {
        "model": "gpt-5.5",
        "approval_policy": "never",
        "sandbox_mode": "danger-full-access",
        "model_reasoning_effort": "high",
    }
    assert result["profiles"]["fast"]["model"] == "gpt-fast"
    assert result["profiles"]["fast"]["approval_policy"] is None
    assert result["sandbox_workspace_write_network_access"] is True
    assert result["danger_full_access_anywhere"] is True


def test_root_owned_config(tmp_path, monkeypatch):
    path = _config(tmp_path)
    real_stat = os.stat

    def foreign_stat(candidate, *args, **kwargs):
        info = real_stat(candidate, *args, **kwargs)
        if Path(candidate) == path:
            return SimpleNamespace(st_mode=info.st_mode, st_uid=os.getuid() + 1)
        return info

    monkeypatch.setattr(codex_config.os, "stat", foreign_stat)
    result = codex_config.collect(_context(tmp_path))
    assert result["config_owner_is_user"] is False


def test_memory_codex_dates(tmp_path):
    memory = tmp_path / ".codex" / "memories"
    memory.mkdir(parents=True)
    (memory / "2026-09-15_note.md").write_text("dated", encoding="utf-8")
    (memory / "notes.md").write_text("undated", encoding="utf-8")
    result = memory_codex.collect(_context(tmp_path))
    assert result["files"] == 2
    assert result["newest"]["source"] == "name"
    assert result["newest"]["date"] == "2026-09-15"


def test_schema_valid(tmp_path, monkeypatch):
    _config(tmp_path)
    memory = tmp_path / ".codex" / "memories"
    memory.mkdir()
    (memory / "2026-09-15_note.md").write_text("dated", encoding="utf-8")
    monkeypatch.setattr(onepassword.runner, "which", lambda name: None)
    monkeypatch.setattr(
        network,
        "tcp_probe",
        lambda host, port, **kwargs: TcpResult(
            True,
            0.1,
            "ipv4",
            kwargs.get("attempts", 3),
            kwargs.get("attempts", 3),
            0.2,
            "open",
        ),
    )
    documents = {
        "codex_config": codex_config.collect(_context(tmp_path)),
        "memory_codex": memory_codex.collect(_context(tmp_path)),
        "onepassword": onepassword.collect(_context(tmp_path)),
        "network": network.collect(_context(tmp_path)),
    }
    for name, document in documents.items():
        schema = json.loads(
            (SKILL_DIR / "schema" / "sections" / f"{name}.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(document)
