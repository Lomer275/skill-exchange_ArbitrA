import json
import pytest
from pathlib import Path
from unittest.mock import patch


def make_skill(skills_dir: Path, name: str, author: str = "test", tags=None, description: str = "desc") -> dict:
    """Creates a skill folder in tmp skills_dir, returns meta dict."""
    skill_dir = skills_dir / name
    skill_dir.mkdir()
    meta = {
        "name": name,
        "display_name": name.replace("-", " ").title(),
        "author": author,
        "version": "1.0.0",
        "description": description,
        "tags": tags or [],
        "created": "2026-04-10",
    }
    (skill_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (skill_dir / "skill.md").write_text(f"# {name}", encoding="utf-8")
    (skill_dir / "README.md").write_text(f"# {name} readme", encoding="utf-8")
    return meta


def patched_skills_dir(tmp_path):
    import sys
    # Remove indexer from sys.modules to force reimport
    if 'indexer' in sys.modules:
        del sys.modules['indexer']
    return patch("indexer.SKILLS_DIR", tmp_path)


def test_scan_finds_skills_alphabetically(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "beta-skill")
        make_skill(tmp_path, "alpha-skill")
        import indexer
        result = indexer.scan_skills()
        assert len(result) == 2
        assert result[0]["name"] == "alpha-skill"
        assert result[1]["name"] == "beta-skill"


def test_scan_ignores_non_directories(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "skill-a")
        (tmp_path / "index.json").write_text("{}")  # file, not dir
        import indexer
        result = indexer.scan_skills()
        assert len(result) == 1


def test_scan_ignores_dirs_without_meta(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "valid-skill")
        (tmp_path / "no-meta-dir").mkdir()  # dir without meta.json
        import indexer
        result = indexer.scan_skills()
        assert len(result) == 1


def test_write_index_creates_file(tmp_path):
    with patched_skills_dir(tmp_path):
        import indexer
        skills = [{"name": "s1", "description": "d1", "tags": []}]
        indexer.write_index(skills)
        data = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
        assert data["skills"] == skills


def test_generate_readme_contains_skill_names(tmp_path):
    import indexer
    skills = [
        {"name": "skill-a", "author": "ivan", "tags": ["git"], "description": "does git"},
        {"name": "skill-b", "author": "anna", "tags": [], "description": "does b"},
    ]
    readme = indexer.generate_readme(skills)
    assert "skill-a" in readme
    assert "skill-b" in readme
    assert "ivan" in readme
    assert "does git" in readme
