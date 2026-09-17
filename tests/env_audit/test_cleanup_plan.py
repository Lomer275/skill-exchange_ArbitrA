import json
from pathlib import Path
import stat

from envaudit.cleanup.plan import build_plan

from .arch_builders import isolated_runtime, write_crontab_stub, write_systemctl_stub
from .canaries import canary, fragments
from .cleanup_builders import (
    collect_facts,
    install_plugin,
    irina_like,
    write_facts,
    write_large_claude,
    write_user_skill,
)


def _plan(fake_home: Path, monkeypatch, tmp_path: Path):
    root = irina_like(fake_home)
    facts = collect_facts(fake_home, [root], monkeypatch)
    facts_path = write_facts(tmp_path / "facts.json", facts)
    output = tmp_path / "cleanup"
    assert build_plan(facts_path, output) == 0
    return root, output, json.loads((output / "plan.json").read_text(encoding="utf-8"))


def _by_kind(plan: dict, kind: str) -> list[dict]:
    return [item for item in plan["items"] if item["kind"] == kind]


def test_irina_like_plan(fake_home, monkeypatch, tmp_path, isolated_runtime):
    write_crontab_stub(
        isolated_runtime,
        ["*/5 * * * * cd /home/x/p && python3 run.py"],
    )
    write_systemctl_stub(
        isolated_runtime,
        {"probe.service": "[Service]\nExecStart=/home/x/p/run.py\n"},
    )

    _root, output, plan = _plan(fake_home, monkeypatch, tmp_path)

    assert len(_by_kind(plan, "close_canon_step")) == 1
    assert len(_by_kind(plan, "codex_close_canon_step")) == 1
    assert len(_by_kind(plan, "memory_index_compress")) == 1
    assert _by_kind(plan, "handoff_archive_mark") == []
    close_item = _by_kind(plan, "close_canon_step")[0]
    after = (output / "after" / close_item["id"]).read_text(encoding="utf-8").splitlines()
    journal_line = next(index for index, line in enumerate(after) if "Хендофф: запиши" in line)
    assert "Обнови канонический HANDOFF" in after[journal_line + 1]


def test_plugin_close_blocked(fake_home, monkeypatch, tmp_path):
    root = fake_home / "projects" / "plugin-only"
    (root / "handoffs").mkdir(parents=True)
    (root / "SUP-HANDOFF.md").write_text("state\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "Read `handoffs/HANDOFF_*.md`.\n", encoding="utf-8"
    )
    install_plugin(fake_home, ["close"])
    facts = collect_facts(fake_home, [root], monkeypatch)
    facts_path = write_facts(tmp_path / "facts.json", facts)
    output = tmp_path / "cleanup"

    assert build_plan(facts_path, output) == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    items = _by_kind(plan, "close_canon_step")
    assert not items or all(item["blocked"] == "plugin_close" for item in items)


def test_protected_and_plugin_not_overridden(fake_home, monkeypatch, tmp_path):
    root = fake_home / "projects" / "skills"
    root.mkdir()
    write_user_skill(fake_home, "my-old")
    write_user_skill(fake_home, "impl")
    install_plugin(fake_home, ["brainstorming"])
    facts = collect_facts(fake_home, [root], monkeypatch)
    entries = facts["sections"]["skills"]["entries"]
    plugin = next(item for item in entries if item["source"] == "plugin")
    plugin["qualified"] = "superpowers:brainstorming"
    plugin["namespace"] = "superpowers"
    plugin["protected"] = True
    plugin["protected_reasons"] = ["superpowers"]
    facts_path = write_facts(tmp_path / "facts.json", facts)
    output = tmp_path / "cleanup"

    assert build_plan(facts_path, output) == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    names = [item["edit"]["name"] for item in _by_kind(plan, "skill_override_off")]
    assert names == ["my-old"]


def test_secret_section_blocked(fake_home, monkeypatch, tmp_path):
    root = fake_home / "projects" / "section"
    root.mkdir()
    sample = canary("github_token", 461)
    write_large_claude(root, body=("plain text\n" * 160) + sample + "\n")
    facts = collect_facts(fake_home, [root], monkeypatch)
    output = tmp_path / "cleanup"

    assert build_plan(write_facts(tmp_path / "facts.json", facts), output) == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    item = _by_kind(plan, "claude_md_section_to_guide")[0]
    assert item["blocked"] == "secret"
    combined = b"".join(path.read_bytes() for path in output.rglob("*") if path.is_file())
    for part in fragments(sample):
        assert part.encode("utf-8") not in combined


def test_settings_with_secret_blocked(fake_home, monkeypatch, tmp_path):
    root = fake_home / "projects" / "settings"
    root.mkdir()
    write_user_skill(fake_home, "my-old")
    sample = canary("anthropic_key", 462)
    settings = fake_home / ".claude" / "settings.json"
    settings.write_text(json.dumps({"env": {"PROBE": sample}}), encoding="utf-8")
    facts = collect_facts(fake_home, [root], monkeypatch)
    output = tmp_path / "cleanup"

    assert build_plan(write_facts(tmp_path / "facts.json", facts), output) == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    item = _by_kind(plan, "skill_override_off")[0]
    assert item["blocked"] == "secret_in_settings"
    assert sample not in (output / "plan.json").read_text(encoding="utf-8")


def test_manual_items_no_values(fake_home, monkeypatch, tmp_path):
    root = fake_home / "projects" / "manual"
    root.mkdir()
    facts = collect_facts(fake_home, [root], monkeypatch)
    facts["sections"]["secrets"] = {
        "context_files": [
            {"path": "/private/place", "classes": {"github_token": {"matches": 1}}}
        ],
        "roots": {
            str(root): {"patterns": {"github_token": {"head_files": 2}}}
        },
    }
    facts["sections"]["architecture"] = {
        str(root): {
            "rule_inputs": {
                "A1": {"outside_git_lines": 41},
                "I1": {"vcs_present": False, "live_units": 1},
                "I2": {"vcs_present": False, "live_units": 1},
            }
        }
    }
    output = tmp_path / "cleanup"

    assert build_plan(write_facts(tmp_path / "facts.json", facts), output) == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    rendered = json.dumps(plan["manual"], ensure_ascii=False)
    assert "context_values" in rendered
    assert "code_outside_git" in rendered
    assert "/private/place" not in rendered


def test_plan_dir_modes(fake_home, monkeypatch, tmp_path):
    _root, output, _document = _plan(fake_home, monkeypatch, tmp_path)

    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE((output / "after").stat().st_mode) == 0o700
    for path in output.rglob("*"):
        if path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
