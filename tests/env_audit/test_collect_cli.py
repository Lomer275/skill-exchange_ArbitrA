import json
from pathlib import Path
import stat

from envaudit.core import cli
from envaudit.core import output as output_module


def test_output_creates_parent_dirs(run_collect, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    output = tmp_path / "first" / "second" / "facts.json"

    result = run_collect(
        "--only",
        "none",
        "--root",
        root,
        "--output",
        output,
    )

    assert result.rc == 0
    assert output.is_file()
    assert stat.S_IMODE((tmp_path / "first").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "first" / "second").stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_output_unwritable_exits_early(monkeypatch, capsys, tmp_path):
    parent = tmp_path / "unwritable"
    parent.mkdir(mode=0o500)
    parent.chmod(0o500)
    collected = False

    def fail_if_collected(_ctx):
        nonlocal collected
        collected = True
        raise AssertionError("collection started")

    monkeypatch.setattr(cli, "collect_host", fail_if_collected)
    code = cli.main(["--output", str(parent / "facts.json")])
    captured = capsys.readouterr()

    assert code == 2
    assert collected is False
    assert not (parent / "facts.json").exists()
    assert "не удаётся писать в" in captured.err
    assert captured.err.count("\n") == 1
    assert "Traceback" not in captured.err


def test_output_failure_falls_back_to_stdout(monkeypatch, capsys, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    output = tmp_path / "facts.json"

    def fail_open(*_args, **_kwargs):
        raise PermissionError("write failed")

    monkeypatch.setattr(output_module.os, "open", fail_open)
    code = cli.main(
        ["--only", "none", "--root", str(root), "--output", str(output)]
    )
    captured = capsys.readouterr()

    document = json.loads(captured.out)
    assert code == 2
    assert document["roots"] == [{"exists": True, "path": str(root)}]
    assert "не удаётся писать в" in captured.err
    assert "write failed" in captured.err
    assert captured.err.count("\n") == 1
    assert "Traceback" not in captured.err
