from __future__ import annotations

import ast
from collections import Counter
import math
from pathlib import Path
import re

from envaudit.arch.context import ArchContext
from envaudit.core import patterns

from .graph import Graph


ENV_TEMPLATE = re.compile(r"(?:^|/)(?:\.env(?:\.[^/]+)?|[^/]+\.env)(?:\.(?:example|sample|template))?$", re.I)
KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLACEHOLDER = re.compile(r"example|your|placeholder|replace|changeme", re.I)


def _entropy(value: bytes) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def value_class(value: str) -> str:
    clean = value.strip().strip("'\"")
    lowered = clean.casefold()
    if not clean:
        return "empty"
    if lowered in {"true", "false", "yes", "no", "on", "off"}:
        return "bool"
    if PLACEHOLDER.search(clean):
        return "placeholder"
    encoded = clean.encode("utf-8", "replace")
    if patterns.is_fake(encoded):
        return "fake"
    if re.fullmatch(r"\d{8,}", clean):
        return "numeric_id"
    if clean.startswith(("/", "./", "../", "~/")) or re.fullmatch(r"[A-Za-z]:[\\/].+", clean):
        return "path"
    if len(encoded) >= 20 and _entropy(encoded) >= 3.5:
        return "long_high_entropy"
    return "placeholder"


def _templates(actx: ArchContext) -> tuple[list[dict], set[str]]:
    output = []
    keys = set()
    for entry in actx.files():
        name = Path(entry.rel).name.casefold()
        if not (
            ENV_TEMPLATE.search(entry.rel)
            and any(marker in name for marker in ("example", "sample", "template"))
        ):
            continue
        data = actx.read(entry)
        if data is None:
            continue
        records = []
        for raw in data.decode("utf-8", "replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name_value, value = line.split("=", 1)
            name_value = name_value.removeprefix("export ").strip()
            if not KEY.fullmatch(name_value):
                continue
            keys.add(name_value)
            records.append({"name": name_value, "class": value_class(value)})
        output.append({"path": entry.rel, "keys": records})
    output.sort(key=lambda item: item["path"])
    return output, keys


def _constant_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _code_keys(graph: Graph) -> tuple[dict[str, set[str]], list[dict], Counter[str]]:
    by_path: dict[str, set[str]] = {}
    outside = []
    numeric_names: Counter[str] = Counter()
    for item in graph.modules.values():
        if not item.prod or item.tree is None:
            continue
        found = set()
        for node in ast.walk(item.tree):
            if isinstance(node, ast.Call):
                called = None
                if isinstance(node.func, ast.Name):
                    called = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    owner = node.func.value
                    owner_name = owner.id if isinstance(owner, ast.Name) else None
                    if node.func.attr == "getenv" or (
                        node.func.attr == "get"
                        and owner_name in {"environ", "env", "cfg", "config", "settings"}
                    ):
                        called = node.func.attr
                if called in {"getenv", "get"} and node.args:
                    value = _constant_string(node.args[0])
                    if value and KEY.fullmatch(value):
                        found.add(value)
            if isinstance(node, ast.Subscript):
                value = node.value
                is_environ = (
                    isinstance(value, ast.Name) and value.id == "environ"
                ) or (
                    isinstance(value, ast.Attribute) and value.attr == "environ"
                )
                if is_environ:
                    name_value = _constant_string(node.slice)
                    if name_value and KEY.fullmatch(name_value):
                        found.add(name_value)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if not isinstance(value, ast.Constant) or not isinstance(value.value, int):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id.upper().endswith("ID") and len(str(abs(value.value))) >= 6:
                        numeric_names[target.id] += 1
        if found:
            by_path[item.path] = found
            stem = Path(item.path).stem.casefold()
            if stem not in {"config", "settings", "environment", "env"}:
                outside.append({"path": item.path, "keys": sorted(found)})
    outside.sort(key=lambda item: (item["path"], tuple(item["keys"])))
    return by_path, outside, numeric_names


def _runtime_keys(actx: ArchContext) -> set[str]:
    output = set()
    for entry in actx.files():
        name = Path(entry.rel).name
        lower = name.casefold()
        if not (
            name.startswith("Dockerfile")
            or lower.startswith("docker-compose") and lower.endswith((".yml", ".yaml"))
            or lower.endswith((".service", ".timer"))
        ):
            continue
        data = actx.read(entry)
        if data is None:
            continue
        text = data.decode("utf-8", "replace")
        for match in re.finditer(r"(?:^|\s)(?:ENV|environment:)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M):
            output.add(match.group(1))
        output.update(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", text))
    return output


def analyse(actx: ArchContext, graph: Graph) -> tuple[dict, dict]:
    templates, template_keys = _templates(actx)
    by_path, outside, numeric_names = _code_keys(graph)
    code_keys = set().union(*by_path.values()) if by_path else set()
    runtime_keys = _runtime_keys(actx)
    repeated = [
        {"name": name, "occurrences": count}
        for name, count in sorted(numeric_names.items())
        if count >= 2
    ]
    output = {
        "templates": templates,
        "code_keys": sorted(code_keys),
        "template_keys": sorted(template_keys),
        "missing_in_template": sorted(code_keys - template_keys - runtime_keys),
        "unused_template": sorted(template_keys - code_keys),
        "getenv_outside_config": outside,
        "repeated_numeric_ids": repeated,
    }
    classes = Counter(
        item["class"]
        for template in templates
        for item in template["keys"]
    )
    rule = {
        "missing_in_template": len(output["missing_in_template"]),
        "unused_template": len(output["unused_template"]),
        "getenv_outside_config": len(outside),
        "repeated_numeric_ids": len(repeated),
        "value_classes": dict(sorted(classes.items())),
    }
    return output, rule
