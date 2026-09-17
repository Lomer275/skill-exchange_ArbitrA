from copy import deepcopy
import json
from pathlib import Path

import jsonschema

from .conftest import SKILL_DIR


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_properties(target: dict, addition: dict) -> None:
    target.setdefault("properties", {}).update(addition.get("properties", {}))
    if "required" in addition:
        required = target.setdefault("required", [])
        for name in addition["required"]:
            if name not in required:
                required.append(name)
    for key, value in addition.items():
        if key not in {"properties", "required"}:
            target.setdefault(key, deepcopy(value))


def load_schema() -> dict:
    schema = _read(SKILL_DIR / "facts.schema.json")
    sections = schema["properties"]["sections"]
    section_properties = sections.setdefault("properties", {})
    for path in sorted((SKILL_DIR / "schema" / "sections").glob("*.schema.json")):
        name = path.name.removesuffix(".schema.json")
        section_properties[name] = _read(path)
    sections["additionalProperties"] = False

    grouped: dict[str, list[tuple[str, dict]]] = {}
    for path in sorted((SKILL_DIR / "schema" / "arch").glob("*.schema.json")):
        stem = path.name.removesuffix(".schema.json")
        key, _, part = stem.partition(".")
        grouped.setdefault(key, []).append((part, _read(path)))
    if grouped:
        architecture = section_properties["architecture"]
        architecture_properties = architecture.setdefault("properties", {})
        for key, fragments in grouped.items():
            base = next((doc for part, doc in fragments if not part), None)
            combined = deepcopy(base) if base is not None else {"type": "object"}
            for part, fragment in fragments:
                if part:
                    _merge_properties(combined, fragment)
            architecture_properties[key] = combined

    return schema


def validate(doc: dict) -> None:
    schema = load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(doc)
