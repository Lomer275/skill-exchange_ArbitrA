import json
from unittest.mock import patch


SKILL_MD_VALID = """---
name: {name}
description: A test skill description
---

# {name}

Body of skill.
"""


def make_skill(skills_dir, name, author="test", tags=None, description="desc",
               with_skill_md=True, with_meta=True, frontmatter_name=None):
    """Creates a skill folder; returns the meta dict."""
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
    if with_meta:
        (skill_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if with_skill_md:
        (skill_dir / "SKILL.md").write_text(
            SKILL_MD_VALID.format(name=frontmatter_name or name),
            encoding="utf-8",
        )
    (skill_dir / "README.md").write_text(f"# {name} readme", encoding="utf-8")
    return meta


def patched_skills_dir(tmp_path):
    import sys
    if 'indexer' in sys.modules:
        del sys.modules['indexer']
    return patch.multiple(
        "indexer",
        SKILLS_DIR=tmp_path,
        INDEX_FILE=tmp_path / "index.json",
    )


# ── scan / write_index ────────────────────────────────────────────────────────

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
        (tmp_path / "index.json").write_text("{}")
        import indexer
        result = indexer.scan_skills()
        assert len(result) == 1


def test_scan_ignores_dirs_without_meta(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "valid-skill")
        (tmp_path / "no-meta-dir").mkdir()
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
    assert "marketplace" in readme.lower()


# ── frontmatter parser ───────────────────────────────────────────────────────

def test_parse_frontmatter_extracts_fields():
    import indexer
    text = "---\nname: my-skill\ndescription: Does X\n---\n\n# Body\n"
    fm = indexer.parse_frontmatter(text)
    assert fm == {"name": "my-skill", "description": "Does X"}


def test_parse_frontmatter_returns_none_when_missing():
    import indexer
    assert indexer.parse_frontmatter("# No frontmatter here\n") is None


def test_parse_frontmatter_strips_quotes():
    import indexer
    text = '---\nname: "my-skill"\ndescription: \'Quoted\'\n---\n\nbody\n'
    fm = indexer.parse_frontmatter(text)
    assert fm == {"name": "my-skill", "description": "Quoted"}


def test_parse_frontmatter_folded_scalar():
    import indexer
    text = (
        "---\n"
        "name: my-skill\n"
        "description: >\n"
        "  Multi-phase review of a task.\n"
        "  Use when the user says \"/codereview\".\n"
        "---\n\nbody\n"
    )
    fm = indexer.parse_frontmatter(text)
    assert fm == {
        "name": "my-skill",
        "description": 'Multi-phase review of a task. Use when the user says "/codereview".',
    }


def test_parse_frontmatter_literal_scalar_keeps_newlines():
    import indexer
    text = "---\nname: my-skill\ndescription: |\n  line one\n  line two\n---\n\nbody\n"
    fm = indexer.parse_frontmatter(text)
    assert fm["description"] == "line one\nline two"


def test_parse_frontmatter_accepts_chomping_indicators():
    import indexer
    for head in (">-", ">+", "|-", "|+"):
        text = f"---\nname: my-skill\ndescription: {head}\n  text here\n---\n\nbody\n"
        fm = indexer.parse_frontmatter(text)
        assert fm is not None, f"{head} rejected"
        assert fm["description"] == "text here"


def test_parse_frontmatter_block_scalar_ends_at_next_key():
    import indexer
    text = (
        "---\n"
        "description: >\n"
        "  folded text\n"
        "name: my-skill\n"
        "---\n\nbody\n"
    )
    fm = indexer.parse_frontmatter(text)
    assert fm == {"description": "folded text", "name": "my-skill"}


def test_parse_frontmatter_empty_block_scalar():
    import indexer
    fm = indexer.parse_frontmatter("---\nname: my-skill\ndescription: >\n---\n\nbody\n")
    assert fm == {"name": "my-skill", "description": ""}


def test_parse_frontmatter_hash_inside_block_is_text():
    import indexer
    text = "---\nname: my-skill\ndescription: |\n  # not a comment\n---\n\nbody\n"
    fm = indexer.parse_frontmatter(text)
    assert fm["description"] == "# not a comment"


def test_parse_frontmatter_rejects_line_without_colon():
    import indexer
    assert indexer.parse_frontmatter("---\nname: my-skill\nbroken line\n---\n\nbody\n") is None


# ── validate_skill ───────────────────────────────────────────────────────────

def test_validate_skill_passes_for_valid_skill(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "good-skill")
        import indexer
        errors = indexer.validate_skill(tmp_path / "good-skill")
        assert errors == []


def test_validate_skill_flags_missing_meta(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "no-meta", with_meta=False)
        import indexer
        errors = indexer.validate_skill(tmp_path / "no-meta")
        assert any("meta.json" in e for e in errors)


def test_validate_skill_flags_missing_skill_md(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "no-skill-md", with_skill_md=False)
        import indexer
        errors = indexer.validate_skill(tmp_path / "no-skill-md")
        assert any("SKILL.md" in e for e in errors)


def test_validate_skill_flags_missing_required_meta_field(tmp_path):
    with patched_skills_dir(tmp_path):
        skill_dir = tmp_path / "incomplete-meta"
        skill_dir.mkdir()
        meta = {"name": "incomplete-meta"}  # missing author + description
        (skill_dir / "meta.json").write_text(json.dumps(meta))
        (skill_dir / "SKILL.md").write_text(SKILL_MD_VALID.format(name="incomplete-meta"))
        import indexer
        errors = indexer.validate_skill(skill_dir)
        assert any("author" in e for e in errors)
        assert any("description" in e for e in errors)


def test_validate_skill_flags_invalid_meta_json(tmp_path):
    with patched_skills_dir(tmp_path):
        skill_dir = tmp_path / "bad-json"
        skill_dir.mkdir()
        (skill_dir / "meta.json").write_text("{ this is not json")
        (skill_dir / "SKILL.md").write_text(SKILL_MD_VALID.format(name="bad-json"))
        import indexer
        errors = indexer.validate_skill(skill_dir)
        assert any("невалидный JSON" in e for e in errors)


def test_validate_skill_flags_missing_frontmatter(tmp_path):
    with patched_skills_dir(tmp_path):
        skill_dir = tmp_path / "no-fm"
        skill_dir.mkdir()
        (skill_dir / "meta.json").write_text(json.dumps({
            "name": "no-fm", "author": "x", "description": "y",
        }))
        (skill_dir / "SKILL.md").write_text("# Just a heading\n\nNo frontmatter.\n")
        import indexer
        errors = indexer.validate_skill(skill_dir)
        assert any("frontmatter" in e for e in errors)


def test_validate_skill_flags_name_mismatch(tmp_path):
    with patched_skills_dir(tmp_path):
        # frontmatter name doesn't match dir name
        make_skill(tmp_path, "real-name", frontmatter_name="wrong-name")
        import indexer
        errors = indexer.validate_skill(tmp_path / "real-name")
        assert any("не совпадает" in e for e in errors)


def test_validate_all_aggregates_errors(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "good-skill")
        make_skill(tmp_path, "bad-skill", with_skill_md=False)
        import indexer
        errors = indexer.validate_all()
        assert any("bad-skill" in e for e in errors)
        assert not any("good-skill" in e for e in errors)


# ── name validation (path-traversal guard) ──────────────────────────────────

def test_validate_name_accepts_kebab_case():
    import indexer
    # All these should not raise
    indexer.validate_name("my-skill")
    indexer.validate_name("git-helper")
    indexer.validate_name("skill1")
    indexer.validate_name("a")


def test_validate_name_rejects_path_traversal():
    import indexer
    import pytest
    for bad in ["..", "../foo", "foo/bar", "../../etc/passwd",
                "/abs/path", "foo\\bar", ".hidden", "-leading-dash"]:
        with pytest.raises(indexer.InvalidSkillNameError):
            indexer.validate_name(bad)


def test_validate_name_rejects_uppercase_and_specials():
    import indexer
    import pytest
    for bad in ["MySkill", "skill_name", "skill name", "skill@v1", ""]:
        with pytest.raises(indexer.InvalidSkillNameError):
            indexer.validate_name(bad)


def test_validate_name_rejects_too_long():
    import indexer
    import pytest
    with pytest.raises(indexer.InvalidSkillNameError):
        indexer.validate_name("a" * 65)
    # 64 is the upper bound (1 leading char + 63 trailing)
    indexer.validate_name("a" * 64)
