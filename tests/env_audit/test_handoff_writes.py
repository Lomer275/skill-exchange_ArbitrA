import time

from envaudit.core import skills_index
from envaudit.core.context import Context, Flags
from envaudit.handoff.writes import agents_md_close_section, write_targets
from envaudit.sections import handoff

from .test_handoff_canon import _write_skill


def test_verb_on_line_vs_mention():
    targets = write_targets(
        "запиши `handoffs/HANDOFF_{ДАТА}.md`\n"
        'find handoffs -name "HANDOFF_*.md" — только предложи\n'
    )

    assert [(item.target, item.confidence) for item in targets] == [
        ("handoffs/HANDOFF_*.md", "verb_on_line"),
        ("HANDOFF_*.md", "mention_only"),
    ]


def test_list_item_verb_scope():
    targets = write_targets(
        "8. Write the daily Codex handoff to\n"
        "   `handoffs/HANDOFF_YYYY-MM-DD_CODEX.md`\n"
    )

    assert len(targets) == 1
    assert targets[0].target == "handoffs/HANDOFF_*_CODEX.md"
    assert targets[0].confidence == "verb_on_line"


def test_agents_md_close_section_bounds():
    text = (
        "### /intro\nRead `handoffs/HANDOFF_*.md`.\n"
        "### /close\nWrite `handoffs/HANDOFF_{DATE}.md`.\n"
        "#### Detail\nKeep this.\n"
        "## Other\nDo not keep.\n"
    )

    section = agents_md_close_section(text)

    assert section is not None
    assert section.startswith("### /close")
    assert "/intro" not in section
    assert "Detail" in section
    assert "Other" not in section


def test_outside_root_target(fake_home, monkeypatch):
    monkeypatch.setattr(skills_index, "MANAGED_DIRS", ())
    root = fake_home / "projects" / "outside"
    root.mkdir()
    (root / "SUP-HANDOFF.md").write_text("state\n", encoding="utf-8")
    _write_skill(
        root / ".claude" / "skills" / "close" / "SKILL.md",
        "close",
        "обнови `/home/u/.claude/projects/x/memory/MEMORY.md`\n",
    )
    started = time.time()
    ctx = Context(Flags(), fake_home, [root], started, started + 300)

    result = handoff.collect(ctx)["roots"][str(root.resolve())]

    assert result["close_writes"][0]["outside_root"] is True
