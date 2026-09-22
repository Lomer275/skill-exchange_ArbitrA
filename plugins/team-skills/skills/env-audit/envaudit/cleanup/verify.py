import json
from pathlib import Path
import time

from envaudit.core.constants import MEMORY_INDEX_MAX_BYTES
from envaudit.core.context import Context, Flags
from envaudit.sections import handoff, instructions, run_sections, skills

from .items import file_sha1, json_text, write_private
from .plan import PLAN_SCHEMA


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _section(document: dict, name: str) -> dict:
    sections = document.get("sections")
    value = sections.get(name) if isinstance(sections, dict) else None
    return value if isinstance(value, dict) else {}


def _projection(sections: dict) -> dict:
    instruction_view = sections.get("instructions")
    instruction_view = instruction_view if isinstance(instruction_view, dict) else {}
    memory = instruction_view.get("memory")
    directories = memory.get("dirs") if isinstance(memory, dict) else []
    memory_view = [
        {
            "name": item.get("name"),
            "root": item.get("root"),
            "index_lines": item.get("index_lines"),
            "index_bytes": item.get("index_bytes"),
        }
        for item in directories
        if isinstance(item, dict)
    ]

    handoff_view = sections.get("handoff")
    handoff_view = handoff_view if isinstance(handoff_view, dict) else {}
    handoff_roots = handoff_view.get("roots")
    handoff_roots = handoff_roots if isinstance(handoff_roots, dict) else {}

    skills_view = sections.get("skills")
    skills_view = skills_view if isinstance(skills_view, dict) else {}
    skill_roots = skills_view.get("roots")
    skill_roots = skill_roots if isinstance(skill_roots, dict) else {}
    return {
        "memory": {"dirs": memory_view},
        "handoff": {
            "roots": {
                root: {"close_writes_canon": value.get("close_writes_canon")}
                for root, value in handoff_roots.items()
                if isinstance(value, dict)
            }
        },
        "skills": {
            "overrides_user": skills_view.get("overrides_user", {}),
            "roots": {
                root: {"overrides": value.get("overrides", {})}
                for root, value in skill_roots.items()
                if isinstance(value, dict)
            },
        },
    }


def _before_projection(facts: dict) -> dict:
    return _projection(
        {
            "instructions": _section(facts, "instructions"),
            "handoff": _section(facts, "handoff"),
            "skills": _section(facts, "skills"),
        }
    )


def _collect_again(facts: dict, home: Path) -> tuple[dict, list[dict]]:
    roots = [
        Path(item["path"])
        for item in facts.get("roots", [])
        if isinstance(item, dict) and item.get("exists") is True and isinstance(item.get("path"), str)
    ]
    started = time.time()
    ctx = Context(
        flags=Flags(only=["instructions", "handoff", "skills"]),
        home=home,
        roots=roots,
        started_at=started,
        deadline=started + 300,
    )
    host = facts.get("host")
    ctx.shared["host"] = host if isinstance(host, dict) else {"codex_home": str(home / ".codex")}
    sections, _durations = run_sections(ctx, [instructions, handoff, skills])
    return sections, ctx.errors


def _override_expected(item: dict, after: dict, home: Path) -> bool:
    edit = item.get("edit")
    if not isinstance(edit, dict):
        return False
    name = edit.get("name")
    if not isinstance(name, str):
        return False
    path = Path(item["path"])
    if path == home / ".claude" / "settings.json":
        mapping = after["skills"]["overrides_user"]
    else:
        root = item.get("root")
        root_view = after["skills"]["roots"].get(root, {})
        overrides = root_view.get("overrides", {}) if isinstance(root_view, dict) else {}
        level = "project_local" if path.name == "settings.local.json" else "project"
        mapping = overrides.get(level, {}) if isinstance(overrides, dict) else {}
    if not isinstance(mapping, dict):
        return False
    return mapping.get(name) == "off" if edit.get("action") == "off" else name not in mapping


def _item_expected(item: dict, after: dict, home: Path) -> bool:
    kind = item.get("kind")
    if kind == "close_canon_step":
        root = item.get("root")
        view = after["handoff"]["roots"].get(root, {})
        return isinstance(view, dict) and view.get("close_writes_canon") is True
    if kind == "memory_index_compress":
        path = Path(item["path"])
        name = path.parents[1].name if len(path.parents) > 1 else ""
        match = next(
            (entry for entry in after["memory"]["dirs"] if entry.get("name") == name),
            None,
        )
        return (
            isinstance(match, dict)
            and isinstance(match.get("index_lines"), int)
            and match["index_lines"] <= 200
            and isinstance(match.get("index_bytes"), int)
            and match["index_bytes"] <= MEMORY_INDEX_MAX_BYTES
        )
    if kind in {"skill_override_off", "skill_override_restore"}:
        return _override_expected(item, after, home)
    return True


def verify_plan(plan_path: Path) -> int:
    plan_path = plan_path.resolve()
    plan = _read_json(plan_path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("not a cleanup plan")
    apply_document = _read_json(plan_path.parent / "apply.json")
    facts = _read_json(Path(plan["facts_path"]))
    home = Path(plan["home"])
    sections, errors = _collect_again(facts, home)
    before = _before_projection(facts)
    after = _projection(sections)
    plan_items = {
        item["id"]: item for item in plan.get("items", []) if isinstance(item, dict)
    }
    item_results = []
    expected = True
    for applied in apply_document.get("items", []):
        if not isinstance(applied, dict) or applied.get("status") != "applied":
            continue
        files = applied.get("files") if isinstance(applied.get("files"), list) else []
        hash_ok = all(
            isinstance(record, dict)
            and file_sha1(Path(record["path"])) == record.get("after_sha1")
            for record in files
        )
        item = plan_items.get(applied.get("id"), {})
        item_expected = _item_expected(item, after, home)
        expected = expected and hash_ok and item_expected
        item_results.append(
            {
                "id": applied.get("id"),
                "hash_ok": hash_ok,
                "changed_as_expected": item_expected,
            }
        )
    if errors:
        expected = False
    document = {
        "schema": "env-audit/cleanup-verify",
        "before": before,
        "after": after,
        "items": item_results,
        "changed_as_expected": expected,
        "errors": errors,
    }
    write_private(plan_path.parent / "verify.json", json_text(document))
    return 0 if expected else 1
