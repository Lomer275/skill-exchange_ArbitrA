from pathlib import Path

from .arch_builders import _git, isolated_runtime, make_repo
from .schema_check import validate


def _arch(result, root: Path) -> dict:
    assert result.rc == 0, result.stdout
    validate(result.data)
    return result.data["sections"]["architecture"][str(root.resolve())]


def test_h1_tracked_backups(tmp_path: Path, run_collect) -> None:
    root = make_repo(
        tmp_path / "project",
        {"app.py.bak": "old\n", "x.orig": "old\n", "app.py": "VALUE = 1\n"},
    )
    (root / "cert.pem").write_text("certificate fixture\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    root_files = arch["hygiene"]["root_files"]
    assert root_files["backup_patterns"] == ["app.py.bak", "x.orig"]
    assert "cert.pem" in root_files["untracked_not_ignored"]


def test_h2_broken_names(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    root.mkdir()
    for name in ('"file.py', "report (копия).docx", "data.csv.1", "Дубли email (Ирина).py"):
        (root / name).write_text("fixture\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    broken = arch["hygiene"]["broken_names"]

    assert '"file.py' in broken
    assert "report (копия).docx" in broken
    assert "data.csv.1" in broken
    assert "Дубли email (Ирина).py" not in broken


def test_h3_tracked_but_ignored(tmp_path: Path, run_collect) -> None:
    root = make_repo(
        tmp_path / "project",
        {".playwright-mcp/log.txt": "log\n", "app.py": "VALUE = 1\n"},
    )
    (root / ".gitignore").write_text(".playwright-mcp/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-m", "ignore logs")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["hygiene"]["tracked_but_ignored"] == [".playwright-mcp/log.txt"]


def test_h5_metric_only(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    files = {
        "docs/X-HANDOFF.md": "one\n",
        "handoffs/HANDOFF_2026-09-08.md": "two\n",
        "n8n/handoff_sync.py": "VALUE = 1\n",
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert len(arch["hygiene"]["doc_duplicates"]["handoff_md"]) == 2
    assert arch["rule_inputs"]["H5"] == {"metric_only": True, "count": 2}


def test_h7_manifest(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    (root / "tests").mkdir(parents=True)
    (root / "app.py").write_text("import requests\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("import pytest\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["hygiene"]["dependency_manifest"] == {
        "present": False,
        "third_party_imports_prod": 1,
    }


def test_no_vcs_git_fields_skipped(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / '"broken.py').write_text("VALUE = 1\n", encoding="utf-8")

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)

    assert arch["hygiene"]["root_files"]["backup_patterns"] is None
    assert arch["hygiene"]["tracked_but_ignored"] is None
    assert arch["hygiene"]["broken_names"] == ['"broken.py']
    details = {
        item["details"]
        for item in result.data["skipped"]
        if item["section"] == "architecture" and item["reason"] == "no_vcs"
    }
    assert any(":H1" in (item or "") for item in details)
    assert any(":H3" in (item or "") for item in details)
