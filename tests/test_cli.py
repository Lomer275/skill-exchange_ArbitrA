import json
import pytest
from pathlib import Path
from unittest.mock import patch


def run_cli(args: list, skills_dir: Path = None):
    """Calls main() with patched sys.argv, captures stdout."""
    import sys
    from io import StringIO
    import skill_exchange

    captured = StringIO()
    with patch("sys.argv", ["skill-exchange"] + args):
        with patch("sys.stdout", captured):
            if skills_dir:
                with patch("indexer.SKILLS_DIR", skills_dir):
                    skill_exchange.main()
            else:
                skill_exchange.main()
    return captured.getvalue()


def make_index(skills_dir: Path, skills: list):
    skills_dir.mkdir(parents=True, exist_ok=True)
    index = {"skills": skills}
    (skills_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")


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
    assert "не найдены" in output or output.strip() == "" or "пуст" in output


def make_skill_in_dir(skills_dir: Path, name: str):
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name, "display_name": name.title(),
        "author": "test", "version": "1.0.0",
        "description": "test skill", "tags": [], "created": "2026-04-10",
    }
    (skill_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (skill_dir / "skill.md").write_text("# skill", encoding="utf-8")
    (skill_dir / "README.md").write_text("# readme", encoding="utf-8")


def test_install_copies_skill_to_target(tmp_path):
    skills_dir = tmp_path / "skills"
    install_dir = tmp_path / "plugins"
    make_skill_in_dir(skills_dir, "cool-skill")
    config = {"default_path": str(install_dir), "installed": []}
    with patch("indexer.SKILLS_DIR", skills_dir), \
         patch("skill_exchange.cfg_module.load_config", return_value=config), \
         patch("skill_exchange.cfg_module.save_config"):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "install", "cool-skill"]):
            skill_exchange.main()
    assert (install_dir / "cool-skill" / "skill.md").exists()


def test_install_missing_skill_exits(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    config = {"default_path": str(tmp_path / "plugins"), "installed": []}
    with patch("indexer.SKILLS_DIR", skills_dir), \
         patch("skill_exchange.cfg_module.load_config", return_value=config), \
         patch("skill_exchange.cfg_module.save_config"):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "install", "nonexistent"]):
            with pytest.raises(SystemExit):
                skill_exchange.main()


def test_install_path_flag(tmp_path):
    skills_dir = tmp_path / "skills"
    custom_dir = tmp_path / "custom"
    make_skill_in_dir(skills_dir, "my-skill")
    config = {"default_path": str(tmp_path / "plugins"), "installed": []}
    with patch("indexer.SKILLS_DIR", skills_dir), \
         patch("skill_exchange.cfg_module.load_config", return_value=config), \
         patch("skill_exchange.cfg_module.save_config"):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "install", "my-skill", "--path", str(custom_dir)]):
            skill_exchange.main()
    assert (custom_dir / "my-skill").exists()


def test_new_creates_skill_files(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    with patch("indexer.SKILLS_DIR", skills_dir):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "new", "test-skill"]):
            skill_exchange.main()
    skill_dir = skills_dir / "test-skill"
    assert (skill_dir / "skill.md").exists()
    assert (skill_dir / "meta.json").exists()
    assert (skill_dir / "README.md").exists()
    meta = json.loads((skill_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == "test-skill"
    assert meta["version"] == "1.0.0"


def test_new_exits_if_skill_exists(tmp_path):
    skills_dir = tmp_path / "skills"
    (skills_dir / "existing-skill").mkdir(parents=True)
    with patch("indexer.SKILLS_DIR", skills_dir):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "new", "existing-skill"]):
            with pytest.raises(SystemExit):
                skill_exchange.main()
