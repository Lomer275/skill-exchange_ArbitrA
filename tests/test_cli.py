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
