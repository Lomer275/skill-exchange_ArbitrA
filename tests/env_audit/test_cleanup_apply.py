import json
from pathlib import Path
import stat

import jsonschema

from envaudit.cleanup.apply import apply_plan, rollback_plan
from envaudit.cleanup.plan import build_plan, render_plan
from envaudit.cleanup.verify import verify_plan

from .cleanup_builders import (
    collect_facts,
    irina_like,
    write_facts,
    write_large_claude,
    write_user_skill,
)
from .conftest import SKILL_DIR


def _prepared(fake_home: Path, monkeypatch, tmp_path: Path, *, guide: bool = False):
    root = irina_like(fake_home)
    if guide:
        write_large_claude(root)
    facts = collect_facts(fake_home, [root], monkeypatch)
    output = tmp_path / "cleanup"
    assert build_plan(write_facts(tmp_path / "facts.json", facts), output) == 0
    return root, output


def _document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _item(plan: dict, kind: str) -> dict:
    return next(item for item in plan["items"] if item["kind"] == kind)


def test_apply_requires_confirmed(fake_home, monkeypatch, tmp_path):
    root, output = _prepared(fake_home, monkeypatch, tmp_path)
    close_path = root / ".claude" / "skills" / "close" / "SKILL.md"
    before = close_path.read_bytes()

    assert apply_plan(output / "plan.json", confirmed=False) == 2
    assert close_path.read_bytes() == before
    assert not (output / "apply.json").exists()


def test_apply_backup_and_write(fake_home, monkeypatch, tmp_path):
    root, output = _prepared(fake_home, monkeypatch, tmp_path)
    close_path = root / ".claude" / "skills" / "close" / "SKILL.md"
    before = close_path.read_bytes()

    assert apply_plan(output / "plan.json", confirmed=True) == 0

    applied = _document(output / "apply.json")
    close_result = next(item for item in applied["items"] if item["kind"] == "close_canon_step")
    backup = Path(close_result["backup_path"])
    assert close_result["status"] == "applied"
    assert backup.read_bytes() == before
    assert stat.S_IMODE(Path(applied["backup_root"]).stat().st_mode) == 0o700
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert "Обнови канонический HANDOFF" in close_path.read_text(encoding="utf-8")


def test_apply_stale_skipped(fake_home, monkeypatch, tmp_path):
    root, output = _prepared(fake_home, monkeypatch, tmp_path)
    close_path = root / ".claude" / "skills" / "close" / "SKILL.md"
    close_path.write_text(close_path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")

    assert apply_plan(output / "plan.json", confirmed=True) == 0

    applied = _document(output / "apply.json")
    close_result = next(item for item in applied["items"] if item["kind"] == "close_canon_step")
    assert close_result["status"] == "stale"
    assert close_path.read_text(encoding="utf-8").endswith("changed\n")


def test_verify_after_apply(fake_home, monkeypatch, tmp_path):
    _root, output = _prepared(fake_home, monkeypatch, tmp_path)
    plan_path = output / "plan.json"

    assert apply_plan(plan_path, confirmed=True) == 0
    assert verify_plan(plan_path) == 0

    verified = _document(output / "verify.json")
    assert verified["changed_as_expected"] is True
    assert all(item["hash_ok"] for item in verified["items"])
    before = next(iter(verified["before"]["handoff"]["roots"].values()))
    after = next(iter(verified["after"]["handoff"]["roots"].values()))
    assert before["close_writes_canon"] is False
    assert after["close_writes_canon"] is True


def test_rollback(fake_home, monkeypatch, tmp_path):
    root, output = _prepared(fake_home, monkeypatch, tmp_path, guide=True)
    plan_path = output / "plan.json"
    plan = _document(plan_path)
    guide_item = _item(plan, "claude_md_section_to_guide")
    guide_item["selected"] = True
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    assert render_plan(plan_path) == 0
    original = {
        Path(item["path"]): Path(item["path"]).read_bytes()
        for item in plan["items"]
        if item["selected"] and item["blocked"] is None and Path(item["path"]).exists()
    }
    guide_path = Path(guide_item["related"][0]["path"])

    assert apply_plan(plan_path, confirmed=True) == 0
    assert guide_path.exists()
    assert rollback_plan(plan_path, confirmed=True) == 0

    assert not guide_path.exists()
    assert all(path.read_bytes() == value for path, value in original.items())
    assert all(item["status"] == "rolled_back" for item in _document(output / "rollback.json")["items"])


def test_rollback_modified_after_apply(fake_home, monkeypatch, tmp_path):
    root, output = _prepared(fake_home, monkeypatch, tmp_path)
    plan_path = output / "plan.json"
    close_path = root / ".claude" / "skills" / "close" / "SKILL.md"
    assert apply_plan(plan_path, confirmed=True) == 0
    close_path.write_text(close_path.read_text(encoding="utf-8") + "manual\n", encoding="utf-8")

    assert rollback_plan(plan_path, confirmed=True) == 0

    results = _document(output / "rollback.json")["items"]
    close_id = _item(_document(plan_path), "close_canon_step")["id"]
    close_result = next(item for item in results if item["id"] == close_id)
    assert close_result["status"] == "modified_after_apply"
    assert close_path.read_text(encoding="utf-8").endswith("manual\n")


def test_schema_valid(fake_home, monkeypatch, tmp_path):
    _root, output = _prepared(fake_home, monkeypatch, tmp_path)
    assert apply_plan(output / "plan.json", confirmed=True) == 0
    plan_schema = _document(SKILL_DIR / "schema" / "cleanup_plan.schema.json")
    apply_schema = _document(SKILL_DIR / "schema" / "cleanup_apply.schema.json")

    jsonschema.Draft202012Validator.check_schema(plan_schema)
    jsonschema.Draft202012Validator(plan_schema).validate(_document(output / "plan.json"))
    jsonschema.Draft202012Validator.check_schema(apply_schema)
    jsonschema.Draft202012Validator(apply_schema).validate(_document(output / "apply.json"))


def test_render_rechains_after_deselect(fake_home, monkeypatch, tmp_path):
    root = fake_home / "projects" / "rechain"
    root.mkdir()
    for name in ("old-one", "old-two", "old-three"):
        write_user_skill(fake_home, name)
    facts = collect_facts(fake_home, [root], monkeypatch)
    output = tmp_path / "cleanup"
    plan_path = output / "plan.json"

    assert build_plan(write_facts(tmp_path / "facts.json", facts), output) == 0
    plan = _document(plan_path)
    items = [
        item
        for item in plan["items"]
        if item["kind"] == "skill_override_off"
        and item["edit"]["name"] in {"old-one", "old-two", "old-three"}
    ]
    assert len(items) == 3
    items[1]["selected"] = False
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    assert render_plan(plan_path) == 0
    assert apply_plan(plan_path, confirmed=True) == 0

    applied = _document(output / "apply.json")["items"]
    results = [item for item in applied if item["id"] in {items[0]["id"], items[2]["id"]}]
    assert len(results) == 2
    assert all(item["status"] == "applied" for item in results)
    settings = _document(fake_home / ".claude" / "settings.json")
    assert settings["skillOverrides"] == {
        items[0]["edit"]["name"]: "off",
        items[2]["edit"]["name"]: "off",
    }
