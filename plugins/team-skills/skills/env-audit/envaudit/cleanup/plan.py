from datetime import date, timedelta
import difflib
import fnmatch
import json
import os
from pathlib import Path
import re
import unicodedata

from envaudit.core.patterns import find
from envaudit.core.redact import scan_file
from envaudit.core.walk import EXCLUDED_DIRS

from .items import EMPTY_SHA1, json_text, read_text, secure_directory, sha1_bytes, write_private
from .textops import (
    TEAM_BEGIN,
    TEAM_END,
    compress_memory_index,
    insert_after_line,
    line_in_team_block,
    links,
    md_sections,
)


PLAN_SCHEMA = "env-audit/cleanup-plan"
BLOCK_REASONS = {
    "secret",
    "team_context",
    "target_exists",
    "cannot_fit",
    "secret_in_settings",
    "plugin_close",
    "no_canon",
}

_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
    }
)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _facts_section(facts: dict, name: str) -> dict:
    sections = facts.get("sections")
    if not isinstance(sections, dict):
        return {}
    value = sections.get(name)
    return value if isinstance(value, dict) else {}


def _classes(data: bytes) -> list[str]:
    return sorted({match.cls for match in find(data)})


def _self_check_classes(data: bytes) -> list[str]:
    return sorted({match.cls for match in find(data, self_check_only=True)})


def _slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title.lower().translate(_TRANSLIT))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return value or "section"


def _guide_dir(root: Path) -> Path:
    docs = root / "docs"
    try:
        candidates = sorted(
            path
            for path in docs.iterdir()
            if path.is_dir() and re.fullmatch(r"4\.\s+.+-guides", path.name)
        )
    except OSError:
        candidates = []
    return candidates[0] if candidates else docs / "guides"


def _diff_lines(before: str, after: str, path: Path) -> list[str]:
    label = str(path).lstrip("/")
    return list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
        )
    )


def _diff_stats(before: str, after: str) -> dict:
    lines = _diff_lines(before, after, Path("file"))
    return {
        "added": sum(line.startswith("+") and not line.startswith("+++") for line in lines),
        "removed": sum(line.startswith("-") and not line.startswith("---") for line in lines),
    }


class _Builder:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.after_dir = output_dir / "after"
        self.items: list[dict] = []

    def add(
        self,
        *,
        kind: str,
        path: Path,
        before: str | None,
        after: str,
        selected: bool,
        summary: str,
        blocked: str | None = None,
        root: Path | None = None,
        edit: dict | None = None,
        related: list[dict] | None = None,
    ) -> dict:
        if blocked is not None and blocked not in BLOCK_REASONS:
            raise ValueError(f"unknown block reason: {blocked}")
        if blocked is None:
            detected_classes = set(_self_check_classes(after.encode("utf-8")))
            for operation in related or []:
                content = operation.get("content")
                if isinstance(content, str):
                    detected_classes.update(_self_check_classes(content.encode("utf-8")))
            if detected_classes:
                blocked = "secret_in_settings" if kind.startswith("skill_override_") else "secret"
                summary = f"Правка заблокирована; классы: {', '.join(sorted(detected_classes))}"
                related = None
                edit = None
        if blocked in {"secret", "secret_in_settings"}:
            related = None
            edit = None
        identifier = f"{len(self.items) + 1:04d}"
        before_text = before or ""
        item = {
            "id": identifier,
            "kind": kind,
            "list": "after_yes",
            "path": str(path),
            "before_sha1": sha1_bytes(before_text.encode("utf-8")),
            "after_sha1": sha1_bytes(after.encode("utf-8")),
            "selected": selected,
            "blocked": blocked,
            "summary": summary,
            "diff_stats": _diff_stats(before_text, after) if blocked is None else {"added": 0, "removed": 0},
            "before_missing": before is None,
        }
        if root is not None:
            item["root"] = str(root)
        if edit is not None:
            item["edit"] = edit
        if related:
            item["related"] = related
        self.items.append(item)
        if blocked is None:
            write_private(self.after_dir / identifier, after)
            for index, operation in enumerate(related or [], 1):
                write_private(
                    self.after_dir / f"{identifier}.{index}",
                    operation["content"],
                )
                operation["artifact"] = f"after/{identifier}.{index}"
                operation.pop("content")
        return item


def _replace_section(text: str, start_line: int, end_line: int, replacement: str) -> str:
    lines = text.splitlines(keepends=True)
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        raise ValueError("section coordinates are stale")
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    lines[start_line - 1 : end_line] = [replacement]
    return "".join(lines)


def _claude_items(builder: _Builder, facts: dict) -> None:
    instructions = _facts_section(facts, "instructions")
    projects = instructions.get("projects")
    if not isinstance(projects, dict):
        return
    for raw_root, project in sorted(projects.items()):
        if not isinstance(project, dict):
            continue
        root = Path(raw_root)
        files = project.get("files")
        if not isinstance(files, list):
            continue
        for file_view in files:
            if not isinstance(file_view, dict) or file_view.get("kind") != "claude_md":
                continue
            rel = file_view.get("rel")
            if not isinstance(rel, str):
                continue
            path = root / rel
            text = read_text(path)
            if text is None:
                continue
            for section in md_sections(text):
                if section.bytes <= 1500:
                    continue
                lines = text.splitlines(keepends=True)
                section_text = "".join(lines[section.start_line - 1 : section.end_line])
                body = "".join(lines[section.start_line : section.end_line]).lstrip("\r\n")
                guide = _guide_dir(root) / f"{_slug(section.title)}.md"
                link = Path(os.path.relpath(guide, path.parent)).as_posix()
                replacement = (
                    f"## {section.title}\n\n"
                    f"Подробности — [{section.title}]({link}).\n"
                )
                after = _replace_section(text, section.start_line, section.end_line, replacement)
                guide_text = f"# {section.title}\n\n{body}"
                blocked = None
                summary = f"Перенести раздел «{section.title}» в гайд"
                found = _classes(section_text.encode("utf-8"))
                found.extend(_classes((after + guide_text).encode("utf-8")))
                found = sorted(set(found))
                if section.in_team_block:
                    blocked = "team_context"
                elif found:
                    blocked = "secret"
                    summary = f"Раздел заблокирован; классы: {', '.join(found)}"
                elif guide.exists():
                    blocked = "target_exists"
                related = [
                    {
                        "path": str(guide),
                        "before_sha1": EMPTY_SHA1,
                        "after_sha1": sha1_bytes(guide_text.encode("utf-8")),
                        "created": True,
                        "content": guide_text,
                    }
                ]
                builder.add(
                    kind="claude_md_section_to_guide",
                    path=path,
                    before=text,
                    after=after,
                    selected=False,
                    blocked=blocked,
                    summary=summary,
                    root=root,
                    edit={
                        "type": "replace_section",
                        "title": section.title,
                        "replacement": replacement,
                    },
                    related=related if blocked is None else None,
                )


def _number_after(line: str, line_no: int) -> int:
    match = re.match(r"\s*(\d+)[.)]", line)
    return int(match.group(1)) + 1 if match else line_no + 1


def _resolved_path(raw: str, root: Path, home: Path) -> Path:
    if raw.startswith("~/"):
        return home / raw[2:]
    path = Path(raw)
    return path if path.is_absolute() else root / path


def _step_item(
    builder: _Builder,
    *,
    kind: str,
    path: Path,
    root: Path,
    canon: str | None,
    journals: list[dict],
    writes: list[dict],
) -> None:
    journal_write = next(
        (
            item
            for item in writes
            if isinstance(item, dict)
            and item.get("writes_journal") is True
            and item.get("confidence") == "verb_on_line"
        ),
        None,
    )
    if journal_write is None:
        return
    text = read_text(path)
    if text is None:
        return
    line_no = journal_write.get("line")
    if not isinstance(line_no, int) or line_no < 1:
        return
    lines = text.splitlines()
    if line_no > len(lines):
        return
    journal = next(
        (
            item.get("glob")
            for item in journals
            if isinstance(item, dict)
            and isinstance(item.get("glob"), str)
            and fnmatch.fnmatchcase(str(journal_write.get("target", "")), item["glob"])
        ),
        str(journal_write.get("target", "")),
    )
    number = _number_after(lines[line_no - 1], line_no)
    block = (
        f"{number}. Обнови канонический HANDOFF `{canon}`: текущее состояние проекта — "
        f"что сделано, где остановились, следующий шаг. Журнал `{journal}` веди как раньше."
    )
    blocked = None
    if canon is None:
        blocked = "no_canon"
    elif line_in_team_block(text, line_no):
        blocked = "team_context"
    after = insert_after_line(text, line_no, block)
    builder.add(
        kind=kind,
        path=path,
        before=text,
        after=after,
        selected=True,
        blocked=blocked,
        summary="Добавить обновление канонического HANDOFF",
        root=root,
        edit={
            "type": "insert_after",
            "anchor": lines[line_no - 1],
            "line": line_no,
            "block": block,
        },
    )


def _handoff_items(builder: _Builder, facts: dict, home: Path) -> None:
    handoff = _facts_section(facts, "handoff")
    roots = handoff.get("roots")
    if not isinstance(roots, dict):
        return
    for raw_root, view in sorted(roots.items()):
        if not isinstance(view, dict):
            continue
        root = Path(raw_root)
        canon_view = view.get("canon")
        canon = canon_view.get("path") if isinstance(canon_view, dict) else None
        journals = view.get("journals") if isinstance(view.get("journals"), list) else []
        skills = view.get("skills")
        close = skills.get("close") if isinstance(skills, dict) else None
        resolved = close.get("resolves_to") if isinstance(close, dict) else None
        if view.get("close_writes_canon") is False and isinstance(resolved, dict):
            raw_path = resolved.get("path")
            source = resolved.get("source")
            if isinstance(raw_path, str) and source != "plugin":
                _step_item(
                    builder,
                    kind="close_canon_step",
                    path=_resolved_path(raw_path, root, home),
                    root=root,
                    canon=canon if isinstance(canon, str) else None,
                    journals=journals,
                    writes=view.get("close_writes") if isinstance(view.get("close_writes"), list) else [],
                )

        codex_writes = view.get("codex_close_writes")
        if isinstance(codex_writes, list) and any(
            isinstance(item, dict)
            and item.get("writes_journal") is True
            and item.get("writes_canon") is not True
            for item in codex_writes
        ):
            _step_item(
                builder,
                kind="codex_close_canon_step",
                path=root / "AGENTS.md",
                root=root,
                canon=canon if isinstance(canon, str) else None,
                journals=journals,
                writes=codex_writes,
            )

        if not isinstance(canon, str):
            continue
        journal_globs = {
            item["glob"]
            for item in journals
            if isinstance(item, dict) and isinstance(item.get("glob"), str)
        }
        for path in _handoff_files(root):
            rel = path.relative_to(root).as_posix()
            if rel == canon or any(fnmatch.fnmatchcase(rel, glob) for glob in journal_globs):
                continue
            text = read_text(path)
            if text is None or text.startswith("> Архив. Текущее состояние — в `"):
                continue
            marker = f"> Архив. Текущее состояние — в `{canon}`.\n\n"
            builder.add(
                kind="handoff_archive_mark",
                path=path,
                before=text,
                after=marker + text,
                selected=True,
                summary="Пометить неканонический HANDOFF как архив",
                root=root,
                edit={"type": "prepend", "block": marker},
            )


def _handoff_files(root: Path) -> list[Path]:
    result = []
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS and depth < 3]
        for name in files:
            if "handoff" in name.lower() and name.lower().endswith(".md"):
                result.append(current_path / name)
    return sorted(result)


def _memory_items(builder: _Builder, facts: dict, home: Path) -> None:
    instructions = _facts_section(facts, "instructions")
    memory = instructions.get("memory")
    directories = memory.get("dirs") if isinstance(memory, dict) else None
    if not isinstance(directories, list):
        return
    for view in directories:
        if not isinstance(view, dict) or not (
            view.get("index_over_lines") is True or view.get("index_over_bytes") is True
        ):
            continue
        name = view.get("name")
        if not isinstance(name, str):
            continue
        path = home / ".claude" / "projects" / name / "memory" / "MEMORY.md"
        text = read_text(path)
        if text is None:
            continue
        after, fits = compress_memory_index(text)
        blocked = None
        summary = "Сжать индекс памяти без потери ссылок"
        found = _classes(after.encode("utf-8"))
        if not fits or links(text) != links(after):
            blocked = "cannot_fit"
        elif found:
            blocked = "secret"
            summary = f"Индекс заблокирован; классы: {', '.join(found)}"
        builder.add(
            kind="memory_index_compress",
            path=path,
            before=text,
            after=after,
            selected=True,
            blocked=blocked,
            summary=summary,
            root=Path(view["root"]) if isinstance(view.get("root"), str) else None,
            edit={"type": "full"},
        )


def _settings_data(path: Path) -> tuple[dict, str | None]:
    text = read_text(path)
    if text is None:
        return {}, None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}, text
    return (value if isinstance(value, dict) else {}), text


def _settings_classes(settings: dict) -> list[str]:
    permissions = settings.get("permissions")
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    relevant = {"env": settings.get("env"), "allow": allow}
    return _classes(json.dumps(relevant, ensure_ascii=False).encode("utf-8"))


def _override_item(
    builder: _Builder,
    *,
    path: Path,
    name: str,
    action: str,
    root: Path | None,
) -> None:
    settings, before = _settings_data(path)
    found = _settings_classes(settings)
    overrides = settings.get("skillOverrides")
    if not isinstance(overrides, dict):
        overrides = {}
        settings["skillOverrides"] = overrides
    if action == "off":
        overrides[name] = "off"
        kind = "skill_override_off"
        summary = f"Отключить неиспользуемый скилл {name}"
    else:
        overrides.pop(name, None)
        kind = "skill_override_restore"
        summary = f"Включить обязательный скилл {name}"
    after = json_text(settings)
    builder.add(
        kind=kind,
        path=path,
        before=before,
        after=after,
        selected=True,
        blocked="secret_in_settings" if found else None,
        summary=(f"Настройки заблокированы; классы: {', '.join(found)}" if found else summary),
        root=root,
        edit={"type": "json_override", "name": name, "action": action},
    )


def _project_roots_for_entry(skills: dict, name: str, source: str) -> list[Path]:
    result = []
    roots = skills.get("roots")
    if not isinstance(roots, dict):
        return result
    for raw_root, view in roots.items():
        resolved = view.get("resolved") if isinstance(view, dict) else None
        entry = resolved.get(name) if isinstance(resolved, dict) else None
        if isinstance(entry, dict) and entry.get("source") == source:
            result.append(Path(raw_root))
    return result


def _skills_items(builder: _Builder, facts: dict, home: Path) -> None:
    skills = _facts_section(facts, "skills")
    entries = skills.get("entries")
    window_days = skills.get("window_days")
    window = window_days if isinstance(window_days, int) else 30
    cutoff = date.today() - timedelta(days=window)
    planned = set()
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            source = entry.get("source")
            usage = entry.get("skill_usage")
            last_raw = usage.get("last_used_at") if isinstance(usage, dict) else None
            try:
                old_usage = last_raw is None or date.fromisoformat(last_raw) < cutoff
            except (TypeError, ValueError):
                old_usage = True
            if not (
                isinstance(name, str)
                and source in {"user", "project", "user_command", "project_command"}
                and entry.get("override_effective") is True
                and entry.get("protected") is False
                and entry.get("invocations_window") == 0
                and old_usage
            ):
                continue
            roots = (
                [None]
                if source in {"user", "user_command"}
                else _project_roots_for_entry(skills, name, source)
            )
            for root in roots:
                path = home / ".claude" / "settings.json" if root is None else root / ".claude" / "settings.json"
                key = (str(path), name, "off")
                if key in planned:
                    continue
                planned.add(key)
                _override_item(builder, path=path, name=name, action="off", root=root)

    mandatory = skills.get("mandatory")
    disabled = mandatory.get("disabled") if isinstance(mandatory, dict) else None
    if not isinstance(disabled, list):
        return
    user_overrides = skills.get("overrides_user")
    user_overrides = user_overrides if isinstance(user_overrides, dict) else {}
    roots = skills.get("roots")
    roots = roots if isinstance(roots, dict) else {}
    for name in disabled:
        if not isinstance(name, str):
            continue
        targets = []
        if name in user_overrides:
            targets.append((home / ".claude" / "settings.json", None))
        for raw_root, view in roots.items():
            override_view = view.get("overrides") if isinstance(view, dict) else None
            if not isinstance(override_view, dict):
                continue
            root = Path(raw_root)
            project = override_view.get("project")
            local = override_view.get("project_local")
            if isinstance(project, dict) and name in project:
                targets.append((root / ".claude" / "settings.json", root))
            if isinstance(local, dict) and name in local:
                targets.append((root / ".claude" / "settings.local.json", root))
        for path, root in targets:
            key = (str(path), name, "restore")
            if key in planned:
                continue
            planned.add(key)
            _override_item(builder, path=path, name=name, action="restore", root=root)


def _manual_items(facts: dict) -> list[dict]:
    result = []
    instructions = _facts_section(facts, "instructions")
    memory = instructions.get("memory")
    split = memory.get("roots_with_multiple_dirs") if isinstance(memory, dict) else None
    if isinstance(split, dict) and split:
        result.append(
            {
                "kind": "memory_reconcile",
                "summary": f"Разъехавшаяся память: корней {len(split)}",
                "why_not_me": "Требуется содержательное сведение человеком",
            }
        )

    values = _facts_section(facts, "secrets")
    context = values.get("context_files")
    if isinstance(context, list) and context:
        classes = sorted(
            {
                cls
                for item in context
                if isinstance(item, dict) and isinstance(item.get("classes"), dict)
                for cls in item["classes"]
            }
        )
        result.append(
            {
                "kind": "context_values",
                "summary": f"Совпадения в контекстных файлах: {len(context)}; классы: {', '.join(classes)}",
                "why_not_me": "Значения нужно ротировать и переносить человеку",
            }
        )
    roots = values.get("roots")
    tracked = 0
    tracked_classes = set()
    if isinstance(roots, dict):
        for root_view in roots.values():
            patterns = root_view.get("patterns") if isinstance(root_view, dict) else None
            if not isinstance(patterns, dict):
                continue
            for cls, counts in patterns.items():
                amount = counts.get("head_files") if isinstance(counts, dict) else None
                if isinstance(amount, int) and amount:
                    tracked += amount
                    tracked_classes.add(cls)
    if tracked:
        result.append(
            {
                "kind": "tracked_values",
                "summary": f"Совпадения в отслеживаемых файлах: {tracked}; классы: {', '.join(sorted(tracked_classes))}",
                "why_not_me": "Ротация и изменение истории выполняются человеком",
            }
        )

    architecture = _facts_section(facts, "architecture")
    outside = 0
    live_without_vcs = 0
    for document in architecture.values():
        rules = document.get("rule_inputs") if isinstance(document, dict) else None
        if not isinstance(rules, dict):
            continue
        a1 = rules.get("A1")
        if isinstance(a1, dict) and isinstance(a1.get("outside_git_lines"), int):
            outside += a1["outside_git_lines"]
        for rule_name in ("I1", "I2"):
            rule = rules.get(rule_name)
            if isinstance(rule, dict) and rule.get("vcs_present") is False:
                amount = rule.get("live_units")
                live_without_vcs += amount if isinstance(amount, int) else 0
    if outside or live_without_vcs:
        result.append(
            {
                "kind": "code_outside_git",
                "summary": f"Код вне git: строк {outside}, живых запусков {live_without_vcs}",
                "why_not_me": "Историю и контур запуска меняет человек",
            }
        )

    handoff = _facts_section(facts, "handoff")
    handoff_roots = handoff.get("roots")
    journal_files = 0
    if isinstance(handoff_roots, dict):
        for view in handoff_roots.values():
            journals = view.get("journals") if isinstance(view, dict) else None
            if isinstance(journals, list):
                journal_files += sum(
                    item.get("files", 0)
                    for item in journals
                    if isinstance(item, dict) and isinstance(item.get("files"), int)
                )
    if journal_files:
        result.append(
            {
                "kind": "old_journals",
                "summary": f"Журналы HANDOFF: файлов {journal_files}",
                "why_not_me": "Удаление файлов выполняет человек",
            }
        )
    return result


def _apply_edit(text: str, item: dict, artifact: str) -> str:
    edit = item.get("edit")
    if not isinstance(edit, dict):
        return artifact
    kind = edit.get("type")
    if kind == "replace_section":
        title = edit.get("title")
        replacement = edit.get("replacement")
        for section in md_sections(text):
            if section.title == title and isinstance(replacement, str):
                return _replace_section(text, section.start_line, section.end_line, replacement)
        raise ValueError("section is stale")
    if kind == "insert_after":
        anchor = edit.get("anchor")
        block = edit.get("block")
        lines = text.splitlines()
        if not isinstance(anchor, str) or not isinstance(block, str):
            raise ValueError("invalid insertion edit")
        matches = [index + 1 for index, line in enumerate(lines) if line == anchor]
        line_no = matches[0] if len(matches) == 1 else edit.get("line")
        if not isinstance(line_no, int):
            raise ValueError("insertion anchor is stale")
        return insert_after_line(text, line_no, block)
    if kind == "prepend":
        block = edit.get("block")
        if not isinstance(block, str):
            raise ValueError("invalid prepend edit")
        return block + text
    if kind == "json_override":
        value = json.loads(text) if text.strip() else {}
        if not isinstance(value, dict):
            raise ValueError("settings are not an object")
        overrides = value.get("skillOverrides")
        if not isinstance(overrides, dict):
            overrides = {}
            value["skillOverrides"] = overrides
        name = edit.get("name")
        if not isinstance(name, str):
            raise ValueError("invalid skill name")
        if edit.get("action") == "off":
            overrides[name] = "off"
        else:
            overrides.pop(name, None)
        return json_text(value)
    return artifact


def _write_plan(path: Path, plan: dict) -> None:
    write_private(path, json_text(plan))


def _render_loaded(plan_path: Path, plan: dict) -> int:
    directory = plan_path.parent
    running: dict[str, str] = {}
    diff_parts = []
    for item in sorted(plan.get("items", []), key=lambda value: value.get("id", "")):
        if not isinstance(item, dict) or item.get("blocked") is not None or item.get("selected") is not True:
            continue
        path = Path(item["path"])
        key = str(path)
        if key not in running:
            current = read_text(path)
            running[key] = current if current is not None else ""
        before = running[key]
        artifact_path = directory / "after" / item["id"]
        artifact = artifact_path.read_text(encoding="utf-8")
        after = _apply_edit(before, item, artifact)
        running[key] = after
        item["before_sha1"] = sha1_bytes(before.encode("utf-8"))
        item["after_sha1"] = sha1_bytes(after.encode("utf-8"))
        item["before_missing"] = not path.exists() and before == ""
        item["diff_stats"] = _diff_stats(before, after)
        write_private(artifact_path, after)
        diff_parts.extend(_diff_lines(before, after, path))
        for index, operation in enumerate(item.get("related", []), 1):
            related_path = Path(operation["path"])
            related_after = (directory / operation["artifact"]).read_text(encoding="utf-8")
            related_before = read_text(related_path) or ""
            diff_parts.extend(_diff_lines(related_before, related_after, related_path))

    diff_path = directory / "plan.diff"
    write_private(diff_path, "".join(diff_parts))
    code, _report = scan_file(diff_path)
    if code == 3:
        diff_path.unlink(missing_ok=True)
        plan["diff_blocked"] = True
    else:
        plan["diff_blocked"] = False
    _write_plan(plan_path, plan)
    return code


def build_plan(facts_path: Path, output_dir: Path) -> int:
    facts_path = facts_path.resolve()
    facts = _read_json(facts_path)
    host = facts.get("host")
    raw_home = host.get("home") if isinstance(host, dict) else None
    home = Path(raw_home) if isinstance(raw_home, str) else Path.home()
    secure_directory(output_dir)
    secure_directory(output_dir / "after")
    builder = _Builder(output_dir)
    _claude_items(builder, facts)
    _handoff_items(builder, facts, home)
    _memory_items(builder, facts, home)
    _skills_items(builder, facts, home)
    plan = {
        "schema": PLAN_SCHEMA,
        "created_on": date.today().isoformat(),
        "facts_path": str(facts_path),
        "home": str(home),
        "diff_blocked": False,
        "items": builder.items,
        "manual": _manual_items(facts),
    }
    plan_path = output_dir / "plan.json"
    _write_plan(plan_path, plan)
    return _render_loaded(plan_path, plan)


def render_plan(plan_path: Path) -> int:
    plan_path = plan_path.resolve()
    plan = _read_json(plan_path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("not a cleanup plan")
    return _render_loaded(plan_path, plan)
