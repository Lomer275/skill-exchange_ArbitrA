import base64
import json
import os
from pathlib import Path
import pwd
import time
from types import SimpleNamespace

from envaudit.core.context import Context, Flags
from envaudit.sections import run_sections

from .conftest import SKILL_DIR
from .schema_check import validate


def _context(tmp_path: Path, *, flags: Flags | None = None, deadline: float | None = None) -> Context:
    started = time.time()
    return Context(
        flags=flags or Flags(),
        home=tmp_path,
        roots=[tmp_path],
        started_at=started,
        deadline=deadline if deadline is not None else started + 300,
    )


def test_default_roots_from_projects(fake_home, run_collect):
    for name in ("b", "a", ".hidden"):
        (fake_home / "projects" / name).mkdir()
    result = run_collect()
    assert result.rc == 0
    assert result.data is not None
    assert [Path(item["path"]).name for item in result.data["roots"]] == ["a", "b"]
    assert result.data["exit_code"] == 0
    validate(result.data)


def test_root_not_found_exit_2(run_collect, tmp_path):
    missing = tmp_path / "nonexistent-xyz"
    result = run_collect("--root", missing)
    assert result.rc == 2
    assert {"section": "roots", "kind": "root_not_found"} in result.data["errors"]


def test_root_b64_cyrillic_spaces(run_collect, tmp_path):
    root = tmp_path / "Битрикс (Ирина, dev2)"
    root.mkdir()
    encoded = base64.b64encode(str(root).encode("utf-8")).decode("ascii")
    result = run_collect("--root-b64", encoded)
    assert result.rc == 0
    assert result.data["roots"] == [{"path": str(root), "exists": True}]


def test_expect_user_wrong_name_exit_4(run_collect):
    result = run_collect("--expect-user", "nobody-xyz")
    assert result.rc == 4
    assert result.stdout == "{}\n"


def test_expect_user_wrong_home_exit_4(run_collect):
    user = pwd.getpwuid(os.geteuid()).pw_name
    result = run_collect("--expect-user", user)
    assert result.rc == 4
    assert result.stdout == "{}\n"


def test_expect_user_ok(run_collect, tmp_path):
    account = pwd.getpwuid(os.geteuid())
    result = run_collect(
        "--expect-user",
        account.pw_name,
        "--root",
        tmp_path,
        "--only",
        "none",
        env_extra={"HOME": account.pw_dir},
    )
    assert result.rc == 0


def test_output_file_mode_600_utf8(run_collect, tmp_path):
    root = tmp_path / "проект"
    root.mkdir()
    output = tmp_path / "facts.json"
    result = run_collect("--root", root, "--output", output)
    assert result.rc == 0
    assert result.stdout == ""
    assert result.data is None
    assert output.stat().st_mode & 0o777 == 0o600
    raw = output.read_bytes()
    assert "проект".encode("utf-8") in raw
    validate(json.loads(raw))


def test_only_filter_flag_off(tmp_path):
    ctx = _context(tmp_path, flags=Flags(only=["x"]))
    modules = [
        SimpleNamespace(NAME="a", ORDER=20, collect=lambda ctx: {}),
        SimpleNamespace(NAME="b", ORDER=10, collect=lambda ctx: {}),
    ]
    sections, _ = run_sections(ctx, modules)
    assert sections == {"b": None, "a": None}
    assert [item["reason"] for item in ctx.skipped] == ["flag_off", "flag_off"]


def test_budget_expired_truncated(tmp_path):
    ctx = _context(tmp_path, deadline=time.time() - 1)
    modules = [
        SimpleNamespace(NAME="a", ORDER=10, collect=lambda ctx: {}),
        SimpleNamespace(NAME="b", ORDER=20, collect=lambda ctx: {}),
    ]
    sections, _ = run_sections(ctx, modules)
    assert sections == {"a": None, "b": None}
    assert [item["reason"] for item in ctx.skipped] == ["budget", "budget"]
    assert ctx.truncated is True


def test_section_exception_to_errors(tmp_path):
    def fail(ctx):
        raise KeyError("not exposed")

    ctx = _context(tmp_path)
    sections, _ = run_sections(ctx, [SimpleNamespace(NAME="stub", ORDER=1, collect=fail)])
    assert sections == {"stub": None}
    assert ctx.errors == [{"section": "stub", "kind": "KeyError"}]


def test_section_order_sorted(tmp_path):
    ctx = _context(tmp_path)
    modules = [
        SimpleNamespace(NAME="late", ORDER=50, collect=lambda ctx: {}),
        SimpleNamespace(NAME="early", ORDER=10, collect=lambda ctx: {}),
    ]
    sections, _ = run_sections(ctx, modules)
    assert list(sections) == ["early", "late"]


def _snapshot(root: Path) -> list[tuple[str, int, int]]:
    return sorted(
        (str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    )


def test_no_writes_to_roots(run_collect, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "source.txt").write_text("content", encoding="utf-8")
    before = _snapshot(root)
    result = run_collect("--root", root)
    assert result.rc == 0
    assert _snapshot(root) == before


def test_no_pycache_in_skill_dir(run_collect, tmp_path):
    before = set(SKILL_DIR.rglob("__pycache__"))
    result = run_collect("--root", tmp_path)
    assert result.rc == 0
    assert set(SKILL_DIR.rglob("__pycache__")) == before
