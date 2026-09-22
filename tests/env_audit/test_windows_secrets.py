import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from envaudit.core import cli, osinfo
from envaudit.core.context import Context, Flags
from envaudit.sections import secrets
from envaudit.secrets import sshkeys

from .canaries import canary
from .conftest import SKILL_DIR
from .schema_check import validate


def _context(home: Path, roots: list[Path] | None = None) -> Context:
    started = time.time()
    return Context(
        Flags(only=["secrets"]),
        home,
        roots or [],
        started,
        started + 300,
        shared={"host": {"codex_home": str(home / ".codex")}},
    )


def _run_windows_cli(monkeypatch, capsys, fake_home, *args: object):
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(osinfo, "is_windows", lambda: True)
    monkeypatch.setattr(cli, "_lower_priority", lambda: None)
    monkeypatch.setattr(cli.getpass, "getuser", lambda: "windows-user")
    code = cli.main([str(arg) for arg in args])
    captured = capsys.readouterr()
    document = json.loads(captured.out) if captured.out.strip() else None
    return code, document, captured


def test_only_secrets_runs_with_windows_host_and_acl(
    monkeypatch, capsys, fake_home, tmp_path
):
    root = tmp_path / "root"
    protected = root / ".secrets"
    protected.mkdir(parents=True)
    (protected / "value.txt").write_text("ordinary", encoding="utf-8")
    private_key = fake_home / ".ssh" / "id_test"
    private_key.parent.mkdir()
    private_key.write_bytes(
        canary("private_key").encode("ascii")
        + b"\nAA==\n-----END RSA PRIVATE KEY-----\n"
    )

    code, document, captured = _run_windows_cli(
        monkeypatch,
        capsys,
        fake_home,
        "--root",
        root,
        "--expect-user",
        "windows-user",
        "--only",
        "secrets",
    )

    assert code == 0
    assert captured.err == ""
    expected_host = {
        "user": "windows-user",
        "uid": None,
        "users_with_home": None,
        "logged_in_count": None,
        "mem_total_mb": None,
    }
    assert {
        name: document["host"][name] for name in expected_host
    } == expected_host
    section = document["sections"]["secrets"]
    assert set(section["positive_controls"].values()) == {"pass"}
    directory = section["roots"][str(root)]["secrets_dir"]
    assert directory["mode"] is None
    assert directory["files_wider_than_600"] is None
    assert directory["acl"] == "not_checked"
    assert section["ssh_keys"][0]["mode"] is None
    assert section["ssh_keys"][0]["wider_than_600"] is None
    assert section["ssh_keys"][0]["acl"] == "not_checked"


@pytest.mark.parametrize("windows", [True, False], ids=["windows", "linux"])
def test_secrets_document_with_storage_and_ssh_key_matches_schema(
    monkeypatch, capsys, fake_home, tmp_path, windows
):
    root = tmp_path / "root"
    root.mkdir()
    protected = fake_home / ".secrets"
    protected.mkdir()
    (protected / "value.txt").write_text("ordinary", encoding="utf-8")
    private_key = fake_home / ".ssh" / "id_test"
    private_key.parent.mkdir()
    private_key.write_bytes(
        canary("private_key").encode("ascii")
        + b"\nAA==\n-----END RSA PRIVATE KEY-----\n"
    )

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(osinfo, "is_windows", lambda: windows)
    monkeypatch.setattr(cli, "_lower_priority", lambda: None)
    monkeypatch.setattr(cli.getpass, "getuser", lambda: "schema-user")
    if windows:
        monkeypatch.setenv("PATH", "")

    code = cli.main(["--root", str(root), "--only", "secrets"])
    captured = capsys.readouterr()
    document = json.loads(captured.out)

    assert code == 0
    assert captured.err == ""
    validate(document)

    section = document["sections"]["secrets"]
    directory = section["storage"]["secrets_dirs"][0]
    key = section["ssh_keys"][0]
    if windows:
        assert directory["files_wider_than_600"] is None
        assert directory["acl"] == "not_checked"
        assert key["wider_than_600"] is None
        assert key["acl"] == "not_checked"
        assert section["positive_controls"]["git_head"] == "not_checked"
        assert section["positive_controls"]["git_history"] == "not_checked"
    else:
        assert isinstance(directory["files_wider_than_600"], int)
        assert "acl" not in directory
        assert isinstance(key["wider_than_600"], bool)
        assert "acl" not in key
        assert set(section["positive_controls"].values()) == {"pass"}


@pytest.mark.parametrize(
    ("windows", "relative"),
    [
        (
            True,
            "AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt",
        ),
        (
            False,
            ".local/share/powershell/PSReadLine/ConsoleHost_history.txt",
        ),
    ],
)
def test_powershell_histories_are_scanned(
    monkeypatch, fake_home, windows, relative
):
    monkeypatch.setattr(osinfo, "is_windows", lambda: windows)
    history = fake_home / relative
    history.parent.mkdir(parents=True)
    history.write_text(canary("bitrix_webhook", 466), encoding="utf-8")

    _home, shell, _config = secrets._scan_home_blocks(
        _context(fake_home), fake_home / ".codex"
    )

    assert shell["files"] == 1
    assert shell["with_matches"] == 1
    assert shell["by_class"]["bitrix_webhook"]["files"] == 1


def test_windows_home_skips_local_temp_but_scans_roaming(
    monkeypatch, fake_home
):
    monkeypatch.setattr(osinfo, "is_windows", lambda: True)
    ignored = fake_home / "AppData" / "Local" / "Temp" / "ignored.txt"
    included = fake_home / "AppData" / "Roaming" / "app" / "included.txt"
    for index, path in enumerate((ignored, included)):
        path.parent.mkdir(parents=True)
        path.write_text(canary("github_token", index + 1), encoding="utf-8")

    home, _shell, _config = secrets._scan_home_blocks(
        _context(fake_home), fake_home / ".codex"
    )

    assert home["files_with_matches"] == 1
    assert home["by_class"]["github_token"]["files"] == 1
    assert "~/AppData/Local/Temp" in home["excluded"]


def test_missing_git_marks_roots_without_failing(
    monkeypatch, fake_home, tmp_path
):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("PATH", "")

    ctx = _context(fake_home, [root])
    section = secrets.collect(ctx)

    assert section["roots"][str(root)]["vcs"] is False
    assert section["positive_controls"]["git_head"] == "not_checked"
    assert section["positive_controls"]["git_history"] == "not_checked"
    assert {"section": "secrets", "reason": "no_git", "details": str(root)} in ctx.skipped
    assert ctx.errors == []


def test_missing_ssh_keygen_is_not_checked(monkeypatch, tmp_path):
    path = tmp_path / "id_test"
    path.write_bytes(
        canary("private_key").encode("ascii")
        + b"\nAA==\n-----END RSA PRIVATE KEY-----\n"
    )
    monkeypatch.setenv("PATH", "")

    assert sshkeys.key_info(path)["passphrase"] == "not_checked"


def test_other_only_on_windows_exits_5(monkeypatch, capsys, fake_home):
    code, document, captured = _run_windows_cli(
        monkeypatch, capsys, fake_home, "--only", "instructions"
    )

    assert code == 5
    assert document is None
    assert "Сборщик рассчитан на Linux/WSL" in captured.err
    assert "Traceback" not in captured.err


def test_cp866_console_is_reconfigured_to_utf8(fake_home):
    wrapper = (
        "import sys\n"
        f"sys.path.insert(0, {str(SKILL_DIR)!r})\n"
        "from envaudit.core import osinfo\n"
        "osinfo.is_windows = lambda: True\n"
        "from envaudit.core.cli import main\n"
        "raise SystemExit(main(['--only', 'instructions']))\n"
    )
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env.pop("CODEX_HOME", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "cp866"

    result = subprocess.run(
        [sys.executable, "-c", wrapper],
        check=False,
        capture_output=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 5
    assert "На Windows аудит идёт вручную" in result.stderr.decode("utf-8")
    assert b"Traceback" not in result.stderr
