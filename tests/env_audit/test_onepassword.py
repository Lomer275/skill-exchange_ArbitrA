import json
import os
from pathlib import Path
import time

from envaudit.core.context import Context, Flags
from envaudit.core.runner import RunResult
from envaudit.sections import onepassword

from .canaries import canary, fragments


def _context(home: Path, root: Path | None = None) -> Context:
    started = time.time()
    return Context(
        flags=Flags(),
        home=home,
        roots=[root or home],
        started_at=started,
        deadline=started + 300,
    )


def _definitions(home: Path, vault_name: str = "Team Shared") -> None:
    path = home / ".config" / "env-audit" / "network.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": "test",
                "must_reach": [],
                "restricted": [],
                "granted": {},
                "team_vault_names": [vault_name],
            }
        ),
        encoding="utf-8",
    )


def test_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(onepassword.runner, "which", lambda name: None)
    result = onepassword.collect(_context(tmp_path))
    assert result["op_path"] is None
    assert result["signed_in_reason"] == "not_installed"
    assert result["op_version"] is None
    assert result["vaults_count"] is None


def _fake_op(tmp_path: Path, monkeypatch, *, signed_in: bool = True) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "biometric-marker"
    script = bin_dir / "op"
    status = "0" if signed_in else "1"
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 2.30.0; exit 0; fi\n"
        "if [ \"$1\" = \"whoami\" ]; then\n"
        "  printf '%s' \"$OP_BIOMETRIC_UNLOCK_ENABLED\" > \"$ENV_AUDIT_MARKER\"\n"
        f"  exit {status}\n"
        "fi\n"
        "if [ \"$1\" = \"vault\" ]; then\n"
        "  printf '%s\\n' '[{\"name\":\"Team Shared\"},{\"name\":\"Personal\"}]'\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("ENV_AUDIT_MARKER", str(marker))
    return marker


def test_signed_in_and_team_vault(tmp_path, monkeypatch, capsys):
    _definitions(tmp_path)
    _fake_op(tmp_path, monkeypatch)
    result = onepassword.collect(_context(tmp_path))
    assert result["signed_in"] is True
    assert result["vaults_count"] == 2
    assert result["team_vault_present"] is True
    serialized = json.dumps(result)
    assert "Team Shared" not in serialized
    assert "Personal" not in serialized
    assert capsys.readouterr().out == ""


def test_session_expired(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(onepassword.runner, "which", lambda name: "/fake/op")

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:] == ["--version"]:
            return RunResult(0, b"2.30.0\n", False, None)
        return RunResult(1, b"", False, None)

    monkeypatch.setattr(onepassword.runner, "run", fake_run)
    result = onepassword.collect(_context(tmp_path))
    assert result["signed_in"] is None
    assert result["signed_in_reason"] == "not_confirmed"
    assert not any(command[1:3] == ["vault", "list"] for command in calls)


def test_biometric_disabled_env(tmp_path, monkeypatch):
    marker = _fake_op(tmp_path, monkeypatch)
    onepassword.collect(_context(tmp_path))
    assert marker.read_text(encoding="utf-8") == "false"


def test_env_counters(tmp_path, monkeypatch, capsys):
    root = tmp_path / "project"
    root.mkdir()
    sample = canary("generic_assignment")
    (root / ".env").write_text("REF=op://vault/item/field\n", encoding="utf-8")
    local = root / ".env.local"
    local.write_text(sample + "\n", encoding="utf-8")
    local.chmod(0o644)
    mixed = root / ".env.prod"
    mixed.write_text(
        "REF=op://vault/item/field\n" + canary("generic_assignment", 7) + "\n",
        encoding="utf-8",
    )
    mixed.chmod(0o600)
    (root / ".env.example").write_text(
        canary("generic_assignment", 11) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(onepassword.runner, "which", lambda name: None)
    result = onepassword.collect(_context(tmp_path, root))["env_files"]
    assert result["op_refs_only"] == 1
    assert result["with_values"] == 1
    assert result["mixed"] == 1
    assert result["templates"] == 1
    assert result["mode_wider_than_600_with_values"] == 1
    output = capsys.readouterr().out
    assert all(fragment not in output for fragment in fragments(sample))
