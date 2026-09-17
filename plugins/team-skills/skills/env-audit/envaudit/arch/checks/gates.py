from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from envaudit.arch.context import ArchContext


KEY = "gates"
ORDER = 50
AGE_DAYS = 90


def _epoch(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _zones(actx: ArchContext) -> dict[str, float]:
    churn = actx.churn() or {}
    roots = actx.out.get("tree", {}).get("source_roots", [])
    prefixes = [
        item.get("path")
        for item in roots
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
    if not prefixes:
        prefixes = ["."]
    zones: dict[str, float] = {}
    for rel, (last, _) in churn.items():
        for prefix in prefixes:
            if prefix == ".":
                remainder = rel
            elif rel == prefix:
                remainder = ""
            elif rel.startswith(prefix + "/"):
                remainder = rel[len(prefix) + 1 :]
            else:
                continue
            parts = Path(remainder).parts
            zone = parts[0] if len(parts) > 1 else prefix
            if not zone or zone == ".":
                continue
            zones[zone] = max(zones.get(zone, 0.0), last)
    return zones


def _g2(actx: ArchContext) -> tuple[list[str], bool, bool]:
    if not actx.vcs:
        return [], False, False
    tree = actx.out.get("tree", {})
    first = _epoch(tree.get("repo_first_commit_at"))
    last = _epoch(tree.get("repo_last_commit_at"))
    if first is None or last is None:
        return [], False, False
    cutoff = time.time() - AGE_DAYS * 86400
    if first > cutoff:
        return [], False, False
    if last < cutoff:
        return [], True, True
    frozen = sorted(zone for zone, modified in _zones(actx).items() if modified < cutoff)
    return frozen, False, True


def _existing_paths(actx: ArchContext, value: object) -> list[str]:
    strings = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(_existing_paths(actx, item))
    elif isinstance(value, dict):
        for item in value.values():
            strings.extend(_existing_paths(actx, item))
    return [
        item
        for item in strings
        if item and not Path(item).is_absolute() and (actx.trees["primary"].path / item).exists()
    ]


def _layers_json(actx: ArchContext) -> dict | None:
    entry = next((item for item in actx.files() if item.rel == ".audit/layers.json"), None)
    if entry is None:
        return None
    data = actx.read(entry)
    if data is None:
        return None
    try:
        document = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if len(set(_existing_paths(actx, document))) < 2:
        return None
    return {"source": "audit_json", "path": entry.rel}


def _table_paths(actx: ArchContext, text: str) -> int:
    rows = []
    for line in text.splitlines():
        if line.count("|") < 2 or re.fullmatch(r"[\s|:-]+", line):
            continue
        found = False
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        for cell in cells:
            for token in re.findall(r"[A-Za-zА-Яа-я0-9_.-]+(?:/[A-Za-zА-Яа-я0-9_.-]+)*", cell):
                if (actx.trees["primary"].path / token).exists():
                    found = True
                    break
            if found:
                break
        if found:
            rows.append(line)
    return len(rows)


def _layers_markdown(actx: ArchContext) -> dict | None:
    candidates = []
    for entry in actx.files():
        name = Path(entry.rel).name
        if name == "CLAUDE.md" or (
            "architecture" in name.lower() and name.lower().endswith(".md")
        ):
            candidates.append(entry)
    for entry in sorted(candidates, key=lambda item: item.rel):
        data = actx.read(entry)
        if data is None:
            continue
        if _table_paths(actx, data.decode("utf-8", "replace")) >= 2:
            return {
                "source": "claude_md" if Path(entry.rel).name == "CLAUDE.md" else "architecture_md",
                "path": entry.rel,
            }
    return None


def run(actx: ArchContext) -> None:
    frozen, dormant, age_checks = _g2(actx)
    layers = _layers_json(actx) or _layers_markdown(actx)
    classification = actx.out.get("classification")
    if isinstance(classification, dict):
        classification["frozen_zones"] = frozen
        classification["dormant_repo"] = dormant
        classification["layers_declared"] = layers
    actx.rule_inputs["G2"] = {
        "frozen_zones": frozen,
        "dormant_repo": dormant,
        "age_checks": age_checks,
    }
    actx.rule_inputs["G3"] = {"layers_declared": layers}
    actx.out[KEY] = {
        "frozen_zones": frozen,
        "dormant_repo": dormant,
        "age_checks": age_checks,
        "layers_declared": layers,
    }
