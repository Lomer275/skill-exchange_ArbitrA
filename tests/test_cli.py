import json
import pytest
from io import StringIO
from unittest.mock import patch


SKILL_MD_TEMPLATE = """---
name: {name}
description: Test skill
---

# {name}

body
"""


def make_skill_in_dir(skills_dir, name):
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name, "display_name": name.title(),
        "author": "test", "version": "1.0.0",
        "description": "test skill", "tags": [], "created": "2026-04-10",
    }
    (skill_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(SKILL_MD_TEMPLATE.format(name=name), encoding="utf-8")
    (skill_dir / "README.md").write_text("# readme", encoding="utf-8")


def make_index(skills_dir, skills):
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "index.json").write_text(json.dumps({"skills": skills}), encoding="utf-8")


def run_cli(args, skills_dir=None, config=None):
    """Calls main() with patched sys.argv, captures stdout."""
    import sys
    if "skill_exchange" in sys.modules:
        del sys.modules["skill_exchange"]
    if "indexer" in sys.modules:
        del sys.modules["indexer"]

    captured = StringIO()
    patches = [patch("sys.argv", ["skill-exchange"] + args), patch("sys.stdout", captured)]
    if skills_dir is not None:
        patches.append(patch("indexer.SKILLS_DIR", skills_dir))
        patches.append(patch("indexer.INDEX_FILE", skills_dir / "index.json"))
    if config is not None:
        patches.append(patch("skill_exchange.cfg_module.load_config", return_value=config))
        patches.append(patch("skill_exchange.cfg_module.save_config"))

    import skill_exchange  # imports indexer too
    if skills_dir is not None:
        skill_exchange.idx_module.SKILLS_DIR = skills_dir
        skill_exchange.idx_module.INDEX_FILE = skills_dir / "index.json"

    for p in patches:
        p.start()
    try:
        skill_exchange.main()
    finally:
        for p in reversed(patches):
            p.stop()
    return captured.getvalue()


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_shows_all_skills(tmp_path):
    skills = [
        {"name": "skill-a", "author": "ivan", "tags": ["git"], "description": "does git"},
        {"name": "skill-b", "author": "anna", "tags": [], "description": "does b"},
    ]
    make_index(tmp_path, skills)
    output = run_cli(["list"], skills_dir=tmp_path)
    assert "skill-a" in output
    assert "skill-b" in output
    assert "ivan" in output


def test_list_filters_by_tag(tmp_path):
    skills = [
        {"name": "skill-a", "author": "ivan", "tags": ["git"], "description": "desc"},
        {"name": "skill-b", "author": "anna", "tags": ["python"], "description": "desc"},
    ]
    make_index(tmp_path, skills)
    output = run_cli(["list", "--tag", "git"], skills_dir=tmp_path)
    assert "skill-a" in output
    assert "skill-b" not in output


def test_list_empty_catalog(tmp_path):
    make_index(tmp_path, [])
    output = run_cli(["list"], skills_dir=tmp_path)
    assert "не найдены" in output or "пуст" in output


# ── install ──────────────────────────────────────────────────────────────────

def test_install_copies_whole_skill_directory(tmp_path):
    """A skill is a folder, not a pair of files.

    Skills ship references/, scripts and data next to SKILL.md, and every one of
    those is load-bearing: a whitelist installs a skill that lists fine and fails
    on first use. Only build artefacts are left behind.
    """
    skills_dir = tmp_path / "skills"
    install_dir = tmp_path / "target"
    make_skill_in_dir(skills_dir, "cool-skill")
    src = skills_dir / "cool-skill"
    (src / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (src / "references").mkdir()
    (src / "references" / "api.md").write_text("# api\n")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "junk.pyc").write_text("x")

    config = {"default_path": str(install_dir), "installed": []}
    run_cli(["install", "cool-skill"], skills_dir=skills_dir, config=config)

    dest = install_dir / "cool-skill"
    assert (dest / "SKILL.md").exists()
    assert (dest / "README.md").exists()
    assert (dest / "meta.json").exists()
    assert (dest / "run.sh").exists()
    assert (dest / "references" / "api.md").exists()
    assert not (dest / "__pycache__").exists()


def test_install_missing_skill_exits(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    config = {"default_path": str(tmp_path / "target"), "installed": []}
    with pytest.raises(SystemExit):
        run_cli(["install", "nonexistent"], skills_dir=skills_dir, config=config)


def test_install_path_flag(tmp_path):
    skills_dir = tmp_path / "skills"
    custom_dir = tmp_path / "custom"
    make_skill_in_dir(skills_dir, "my-skill")
    config = {"default_path": str(tmp_path / "default"), "installed": []}
    run_cli(["install", "my-skill", "--path", str(custom_dir)],
            skills_dir=skills_dir, config=config)
    assert (custom_dir / "my-skill" / "SKILL.md").exists()


def test_install_fails_if_no_skill_md(tmp_path):
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "meta.json").write_text(json.dumps({
        "name": "broken", "author": "x", "description": "y",
    }))
    # No SKILL.md
    config = {"default_path": str(tmp_path / "target"), "installed": []}
    with pytest.raises(SystemExit):
        run_cli(["install", "broken"], skills_dir=skills_dir, config=config)


# ── uninstall ────────────────────────────────────────────────────────────────

def test_uninstall_removes_skill_folder(tmp_path):
    skills_dir = tmp_path / "skills"
    install_dir = tmp_path / "target"
    make_skill_in_dir(skills_dir, "to-remove")
    config = {"default_path": str(install_dir), "installed": ["to-remove"]}

    run_cli(["install", "to-remove"], skills_dir=skills_dir, config=config)
    assert (install_dir / "to-remove" / "SKILL.md").exists()

    saved = {}
    def fake_save(c):
        saved.update(c)
    with patch("skill_exchange.cfg_module.save_config", side_effect=fake_save):
        run_cli(["uninstall", "to-remove"], skills_dir=skills_dir, config=config)
    assert not (install_dir / "to-remove").exists()


def test_uninstall_handles_missing_install(tmp_path):
    skills_dir = tmp_path / "skills"
    config = {"default_path": str(tmp_path / "target"), "installed": []}
    output = run_cli(["uninstall", "ghost"], skills_dir=skills_dir, config=config)
    assert "не установлен" in output


# ── new ──────────────────────────────────────────────────────────────────────

def test_new_creates_skill_with_frontmatter(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    run_cli(["new", "test-skill"], skills_dir=skills_dir)
    skill_dir = skills_dir / "test-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "meta.json").exists()
    assert (skill_dir / "README.md").exists()

    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert skill_md.startswith("---\n")
    assert "name: test-skill" in skill_md
    assert "description:" in skill_md

    meta = json.loads((skill_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == "test-skill"
    assert meta["version"] == "1.0.0"


def test_new_exits_if_skill_exists(tmp_path):
    skills_dir = tmp_path / "skills"
    (skills_dir / "existing-skill").mkdir(parents=True)
    with pytest.raises(SystemExit):
        run_cli(["new", "existing-skill"], skills_dir=skills_dir)


# ── validate ─────────────────────────────────────────────────────────────────

def test_validate_passes_on_clean_repo(tmp_path):
    skills_dir = tmp_path / "skills"
    make_skill_in_dir(skills_dir, "clean-skill")
    output = run_cli(["validate"], skills_dir=skills_dir)
    assert "валидны" in output


def test_validate_exits_nonzero_on_errors(tmp_path):
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "meta.json").write_text("{ invalid json")
    (skill_dir / "SKILL.md").write_text("no frontmatter\n")
    with pytest.raises(SystemExit):
        run_cli(["validate"], skills_dir=skills_dir)


# ── path-traversal guards on user-supplied name ─────────────────────────────

def test_install_rejects_path_traversal_name(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    config = {"default_path": str(tmp_path / "target"), "installed": []}
    with pytest.raises(SystemExit):
        run_cli(["install", "../evil", "--path", str(tmp_path / "target")],
                skills_dir=skills_dir, config=config)


def test_uninstall_rejects_path_traversal_name(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    config = {"default_path": str(tmp_path / "target"), "installed": []}
    with pytest.raises(SystemExit):
        run_cli(["uninstall", "..", "--path", str(tmp_path)],
                skills_dir=skills_dir, config=config)


def test_new_rejects_path_traversal_name(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    with pytest.raises(SystemExit):
        run_cli(["new", "../escapee"], skills_dir=skills_dir)


# ── uninstall safety guard (won't rmtree non-skill folder) ──────────────────

def test_uninstall_refuses_to_delete_non_skill_folder(tmp_path):
    """If <target>/<name>/ exists but contains no SKILL.md, refuse to delete.

    Uses a kebab-case name that passes name validation, so this tests the
    SKILL.md presence guard rather than the regex.
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    install_dir = tmp_path / "target"
    important = install_dir / "user-data"
    important.mkdir(parents=True)
    (important / "important.txt").write_text("do not delete!")

    config = {"default_path": str(install_dir), "installed": []}
    with pytest.raises(SystemExit):
        run_cli(["uninstall", "user-data", "--path", str(install_dir)],
                skills_dir=skills_dir, config=config)
    # File must still exist
    assert (important / "important.txt").exists()
