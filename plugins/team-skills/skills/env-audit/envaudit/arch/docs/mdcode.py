import ast
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext

from . import Document, markdown_documents


DEFINITION = re.compile(
    r"(?m)^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(|"
    r"^\s*(?:(?:export|default|async|public|protected|private|static|final)\s+)*"
    r"function\s+([A-Za-z_$][\w$]*)\s*\("
)


@dataclass(frozen=True)
class Definition:
    name: str
    body: str


def _fenced_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    result = []
    current = []
    in_fence = False
    for line in lines:
        if re.match(r"^\s*```", line):
            if in_fence:
                result.append("\n".join(current))
                current = []
                in_fence = False
            else:
                in_fence = True
            continue
        if in_fence:
            current.append(line)
    return result


def _python_definitions(text: str) -> list[Definition]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    lines = text.splitlines()
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        result.append(
            Definition(node.name, "\n".join(lines[node.lineno - 1 : end]))
        )
    return result


def _brace_end(text: str, start: int) -> int | None:
    opening = text.find("{", start)
    if opening < 0:
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(text)):
        character = text[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _function_definitions(text: str) -> list[Definition]:
    result = []
    pattern = re.compile(
        r"(?m)^\s*(?:(?:export|default|async|public|protected|private|static|final)\s+)*"
        r"function\s+([A-Za-z_$][\w$]*)\s*\("
    )
    for match in pattern.finditer(text):
        end = _brace_end(text, match.end())
        if end is not None:
            result.append(Definition(match.group(1), text[match.start() : end]))
    return result


def _definitions(text: str) -> list[Definition]:
    python = _python_definitions(text)
    functions = _function_definitions(text)
    by_value = {(item.name, item.body): item for item in [*python, *functions]}
    return list(by_value.values())


def _normalized(body: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line.strip())
        for line in body.splitlines()
        if line.strip()
    ]


def _code_definitions(actx: ArchContext) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for entry in actx.code_files(
        exts=frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".php"})
    ):
        data = actx.read(entry)
        if data is None:
            continue
        text = data.decode("utf-8", "replace")
        if Path(entry.rel).suffix.lower() == ".py":
            parsed = pyast.parse(data, entry.rel)
            if parsed is None:
                continue
            lines = text.splitlines()
            definitions = []
            for node in ast.walk(parsed):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end = getattr(node, "end_lineno", node.lineno)
                    definitions.append(
                        Definition(
                            node.name,
                            "\n".join(lines[node.lineno - 1 : end]),
                        )
                    )
        else:
            definitions = _function_definitions(text)
        for definition in definitions:
            result.setdefault(definition.name, []).append(
                (entry.rel, definition.body)
            )
    return result


def _excluded(rel: str) -> bool:
    lowered = [part.lower() for part in Path(rel).parts]
    return ".superpowers" in lowered or any(
        left == "docs" and right == "superpowers"
        for left, right in zip(lowered, lowered[1:])
    )


def collect(actx: ArchContext) -> list[dict]:
    candidates: list[tuple[Document, list[Definition], int]] = []
    for document in markdown_documents(actx):
        if _excluded(document.rel):
            continue
        blocks = _fenced_blocks(document.text)
        count = sum(len(DEFINITION.findall(block)) for block in blocks)
        if count < 10:
            continue
        definitions = [item for block in blocks for item in _definitions(block)]
        candidates.append((document, definitions, count))
    if not candidates:
        return []
    code = _code_definitions(actx)
    result = []
    for document, definitions, total in candidates:
        for definition in definitions:
            matches = code.get(definition.name, [])
            if not matches:
                continue
            scored = [
                (
                    SequenceMatcher(
                        None,
                        _normalized(definition.body),
                        _normalized(body),
                        autojunk=False,
                    ).ratio(),
                    rel,
                )
                for rel, body in matches
            ]
            ratio, code_path = max(scored, key=lambda item: (item[0], item[1]))
            if ratio >= 1.0:
                continue
            result.append(
                {
                    "md": document.rel,
                    "definitions_in_md": total,
                    "function": definition.name,
                    "code_path": code_path,
                    "ratio": round(ratio, 6),
                }
            )
    return sorted(
        result,
        key=lambda item: (item["md"], item["function"], item["code_path"]),
    )
