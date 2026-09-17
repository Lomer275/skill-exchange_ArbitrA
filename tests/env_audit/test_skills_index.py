from envaudit.core import skills_index

from .skill_builders import install_plugin, write_skill


def _without_managed(monkeypatch):
    monkeypatch.setattr(skills_index, "MANAGED_DIRS", ())


def test_resolution_order_user_wins(fake_home, tmp_path, monkeypatch):
    _without_managed(monkeypatch)
    root = fake_home / "projects" / "project"
    write_skill(fake_home / ".claude" / "skills", "close")
    write_skill(root / ".claude" / "skills", "close")
    install_plugin(fake_home, tmp_path / "team-plugin", "team-skills@exchange", ["close"])

    entries = skills_index.list_skills(fake_home, [root])
    assert skills_index.resolve("close", entries).source == "user"
    assert skills_index.plugin_twins("close", entries) == ["team-skills:close"]


def test_resolution_project_plus_plugin(fake_home, tmp_path, monkeypatch):
    _without_managed(monkeypatch)
    root = fake_home / "projects" / "project"
    write_skill(root / ".claude" / "skills", "close")
    install_plugin(fake_home, tmp_path / "team-plugin", "team-skills@exchange", ["close"])

    entries = skills_index.list_skills(fake_home, [root])
    assert skills_index.resolve("close", entries).source == "project"
    assert skills_index.resolve("team-skills:close", entries).source == "plugin"


def test_disabled_plugin_not_listed(fake_home, tmp_path, monkeypatch):
    _without_managed(monkeypatch)
    install_plugin(
        fake_home,
        tmp_path / "team-plugin",
        "team-skills@exchange",
        ["close"],
        enabled=False,
    )

    entries = skills_index.list_skills(fake_home, [])
    assert all(item.source != "plugin" for item in entries)


def test_frontmatter_multiline(fake_home, monkeypatch):
    _without_managed(monkeypatch)
    path = fake_home / ".claude" / "skills" / "multiline" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: multiline\n"
        "description: >\n"
        "  English first\n"
        "  Русская second\n"
        "  third\n"
        "when_to_use: |\n"
        "  one\n"
        "  two\n"
        "---\n"
        "ignored body\n",
        encoding="utf-8",
    )

    entry = skills_index.list_skills(fake_home, [])[0]
    assert entry.description_len == len("English first Русская second third")
    assert entry.when_to_use_len == len("onetwo")
    assert entry.has_cyrillic is True


def test_memory_dir_name_cyrillic():
    assert (
        skills_index.memory_dir_name("/home/utkinais/projects/Битрикс")
        == "-home-utkinais-projects--------"
    )


def test_command_without_frontmatter_uses_filename(fake_home, monkeypatch):
    _without_managed(monkeypatch)
    command = fake_home / ".claude" / "commands" / "nested" / "plain.md"
    command.parent.mkdir(parents=True)
    command.write_text("Command body only.\n", encoding="utf-8")

    entry = skills_index.list_skills(fake_home, [])[0]
    assert entry.name == "plain"
    assert entry.source == "user_command"
    assert entry.description_len == 0
