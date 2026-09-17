from __future__ import annotations

import ast
from collections import defaultdict
from difflib import SequenceMatcher
import hashlib
from pathlib import Path

from envaudit.arch.context import ArchContext
from envaudit.core.runner import git

from .graph import Graph


PAIR_LIMIT = 20_000
CONVENTION_NAMES = {"apps.py", "admin.py", "urls.py", "models.py"}


def _lines(item_data: bytes) -> list[str]:
    return [
        line
        for raw in item_data.decode("utf-8", "replace").splitlines()
        for line in [raw.strip()]
        if line and not line.startswith("#")
    ]


def _excluded(path: str, sloc: int) -> str | None:
    name = Path(path).name
    if name == "__init__.py":
        return "package_init"
    if sloc < 20:
        return "short"
    if name in CONVENTION_NAMES:
        return "django_convention"
    if "migrations" in (part.casefold() for part in Path(path).parts):
        return "migration"
    return None


def _function_records(graph: Graph) -> list[dict]:
    output = []
    for item in graph.modules.values():
        if not item.prod or item.tree is None:
            continue
        for node in ast.walk(item.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            length = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
            body_length = (
                getattr(node.body[-1], "end_lineno", node.body[-1].lineno)
                - node.body[0].lineno
                + 1
                if node.body
                else 0
            )
            if body_length <= 5:
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]), annotate_fields=False)
            digest = hashlib.sha1(body.encode("utf-8")).hexdigest()
            calls = []
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)
            output.append(
                {
                    "path": item.path,
                    "name": node.name,
                    "line": node.lineno,
                    "lines": length,
                    "body_lines": body_length,
                    "digest": digest,
                    "calls": calls,
                }
            )
    return output


def _same_basename(
    graph: Graph, orphans: dict[str, dict], budget: list[int]
) -> tuple[list[dict], bool]:
    groups: dict[str, list] = defaultdict(list)
    for item in graph.modules.values():
        if item.prod:
            groups[Path(item.path).name].append(item)
    output = []
    truncated = False
    for basename, items in sorted(groups.items()):
        if len(items) < 2:
            continue
        for left_index, left in enumerate(items):
            for right in items[left_index + 1 :]:
                if budget[0] >= PAIR_LIMIT:
                    truncated = True
                    break
                budget[0] += 1
                left_reason = _excluded(left.path, left.sloc)
                right_reason = _excluded(right.path, right.sloc)
                excluded_reason = left_reason or right_reason
                record = {
                    "left": left.path,
                    "right": right.path,
                    "ratio": None,
                    "excluded_reason": excluded_reason,
                }
                if excluded_reason is not None:
                    output.append(record)
                    continue
                left_lines = _lines(left.data)
                right_lines = _lines(right.data)
                length_ratio = min(len(left_lines), len(right_lines)) / max(len(left_lines), len(right_lines), 1)
                if length_ratio < 0.8:
                    continue
                matcher = SequenceMatcher(None, left_lines, right_lines, autojunk=False)
                if matcher.quick_ratio() < 0.8:
                    continue
                record["ratio"] = round(matcher.ratio(), 6)
                if record["ratio"] >= 0.7:
                    output.append(record)
            if truncated:
                break
        if truncated:
            break
    return output, truncated


def _function_groups(records: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[record["digest"]].append(record)
    output = []
    for _, items in sorted(groups.items(), key=lambda pair: min((item["path"], item["line"]) for item in pair[1])):
        paths = {item["path"] for item in items}
        if len(items) < 2 or len(paths) < 2:
            continue
        output.append(
            {
                "hash_id": len(output) + 1,
                "copies": [
                    {"path": item["path"], "name": item["name"], "line": item["line"]}
                    for item in sorted(items, key=lambda item: (item["path"], item["line"]))
                ],
            }
        )
    return output


def _callseq(records: list[dict], budget: list[int]) -> tuple[list[dict], bool]:
    eligible = [record for record in records if record["lines"] > 15 and record["calls"]]
    by_call: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(eligible):
        for called in set(record["calls"]):
            by_call[called].append(index)
    candidates = set()
    candidate_truncated = False
    for indexes in by_call.values():
        for offset, left in enumerate(indexes):
            for right in indexes[offset + 1 :]:
                if eligible[left]["path"] != eligible[right]["path"]:
                    candidates.add((min(left, right), max(left, right)))
                    if len(candidates) >= max(0, PAIR_LIMIT - budget[0]):
                        candidate_truncated = True
                        break
            if candidate_truncated:
                break
        if candidate_truncated:
            break
    output = []
    truncated = candidate_truncated
    for left_index, right_index in sorted(candidates):
        if budget[0] >= PAIR_LIMIT:
            truncated = True
            break
        budget[0] += 1
        left = eligible[left_index]
        right = eligible[right_index]
        left_set = set(left["calls"])
        right_set = set(right["calls"])
        jaccard = len(left_set & right_set) / max(len(left_set | right_set), 1)
        if jaccard < 0.5:
            continue
        matcher = SequenceMatcher(None, left["calls"], right["calls"], autojunk=False)
        if matcher.quick_ratio() < 0.6:
            continue
        ratio = matcher.ratio()
        if ratio >= 0.7 and min(left["lines"], right["lines"]) > 40:
            output.append(
                {
                    "left": {"path": left["path"], "name": left["name"], "line": left["line"]},
                    "right": {"path": right["path"], "name": right["name"], "line": right["line"]},
                    "jaccard": round(jaccard, 6),
                    "ratio": round(ratio, 6),
                }
            )
    return output, truncated


def _fingerprints(path: Path) -> set[str]:
    output = set()
    try:
        paths = sorted(path.rglob("*.py"))
    except OSError:
        return output
    for source in paths:
        if any(part in {".git", ".venv", "venv", "node_modules", "build", "dist"} for part in source.parts):
            continue
        try:
            tree = ast.parse(source.read_bytes())
        except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body_length = (
                getattr(node.body[-1], "end_lineno", node.body[-1].lineno)
                - node.body[0].lineno
                + 1
                if node.body
                else 0
            )
            if body_length <= 5:
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]), annotate_fields=False)
            output.add(hashlib.sha1(body.encode("utf-8")).hexdigest())
    return output


def _sibling(actx: ArchContext, own: set[str]) -> dict | None:
    value = actx.ctx.flags.sibling
    if not value:
        actx.skip("python", "no_sibling")
        return None
    path = Path(value).expanduser().resolve()
    sibling_values = _fingerprints(path)
    roots_left = git(actx.root, "rev-list", "--max-parents=0", "HEAD").stdout.splitlines()
    roots_right = git(path, "rev-list", "--max-parents=0", "HEAD").stdout.splitlines()
    union = own | sibling_values
    return {
        "common_root": bool(set(roots_left) & set(roots_right)),
        "jaccard": round(len(own & sibling_values) / len(union), 6) if union else 0.0,
    }


def analyse(actx: ArchContext, graph: Graph, orphans: dict[str, dict]) -> tuple[dict, dict]:
    budget = [0]
    same, truncated = _same_basename(graph, orphans, budget)
    records = _function_records(graph)
    groups = _function_groups(records)
    callseq, callseq_truncated = _callseq(records, budget)
    own = {record["digest"] for record in records}
    output = {
        "same_basename_pairs": same,
        "function_hash_groups": groups,
        "callseq_pairs": callseq,
        "sibling": _sibling(actx, own),
        "truncated": truncated or callseq_truncated,
    }
    rule = {
        "same_basename_shadowed": sum(
            item.get("ratio") is not None
            and item["ratio"] >= 0.9
            and (item["left"] in orphans or item["right"] in orphans)
            for item in same
        ),
        "function_hash_groups_x3": sum(len(item["copies"]) >= 3 for item in groups),
        "callseq_pairs": len(callseq),
        "comparisons": budget[0],
        "truncated": output["truncated"],
    }
    return output, rule
