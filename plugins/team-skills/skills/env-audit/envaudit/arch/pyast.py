import ast
from contextvars import ContextVar, Token
import io
from pathlib import Path
import sys
import tokenize
import warnings

from .context import ArchContext


_CACHE: ContextVar[dict[str, object] | None] = ContextVar(
    "arch_parse_cache", default=None
)


def _set_cache(cache: dict[str, object]) -> Token:
    return _CACHE.set(cache)


def _reset_cache(token: Token) -> None:
    _CACHE.reset(token)


def parse(data: bytes, rel: str) -> ast.Module | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(data, filename=rel)
    except (SyntaxError, ValueError, UnicodeDecodeError) as error:
        cache = _CACHE.get()
        if cache is not None:
            errors = cache.setdefault("parse_errors", [])
            if isinstance(errors, list):
                errors.append(
                    {
                        "path": rel,
                        "kind": type(error).__name__,
                        "line": getattr(error, "lineno", None),
                    }
                )
        return None


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.result: list[tuple[str, int, bool]] = []
        self.type_checking = 0
        self.function = 0

    def visit_If(self, node: ast.If) -> None:
        name = _call_name(node.test)
        is_type_checking = name in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}
        if is_type_checking:
            self.type_checking += 1
        for child in node.body:
            self.visit(child)
        if is_type_checking:
            self.type_checking -= 1
        for child in node.orelse:
            self.visit(child)

    def _visit_function(self, node: ast.AST) -> None:
        self.function += 1
        self.generic_visit(node)
        self.function -= 1

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function
    visit_Lambda = _visit_function

    def visit_Import(self, node: ast.Import) -> None:
        guarded = bool(self.type_checking or self.function)
        for alias in node.names:
            self.result.append((alias.name, node.lineno, guarded))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        guarded = bool(self.type_checking or self.function)
        prefix = "." * node.level
        self.result.append((prefix + (node.module or ""), node.lineno, guarded))


def imports(tree: ast.Module) -> list[tuple[str, int, bool]]:
    visitor = _ImportVisitor()
    visitor.visit(tree)
    return visitor.result


def has_main_guard(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        values = [test.left, *test.comparators]
        has_name = any(
            isinstance(value, ast.Name) and value.id == "__name__"
            for value in values
        )
        has_main = any(
            isinstance(value, ast.Constant) and value.value == "__main__"
            for value in values
        )
        if has_name and has_main and isinstance(test.ops[0], ast.Eq):
            return True
    return False


def calls_named(tree: ast.Module, names: set[str]) -> list[tuple[str, int]]:
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name in names:
            result.append((name, node.lineno))
        elif name and name.rsplit(".", 1)[-1] in names:
            result.append((name, node.lineno))
    return sorted(result, key=lambda item: (item[1], item[0]))


def _line_count(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def sloc(data: bytes, *, python: bool) -> tuple[int, int, int]:
    lines = _line_count(data)
    decoded = data.decode("utf-8", "replace")
    physical = decoded.splitlines()
    non_comment = {
        number
        for number, line in enumerate(physical, 1)
        if line.strip() and not line.lstrip().startswith("#")
    }
    logical = len(non_comment)
    if not python:
        return lines, logical, logical

    multiline_strings: set[int] = set()
    try:
        for token in tokenize.tokenize(io.BytesIO(data).readline):
            if token.type == tokenize.STRING and token.start[0] != token.end[0]:
                multiline_strings.update(range(token.start[0], token.end[0] + 1))
    except (IndentationError, SyntaxError, tokenize.TokenError):
        pass
    return lines, logical, len(non_comment - multiline_strings)


def local_modules(
    actx: ArchContext, tree_id: str = "primary"
) -> set[str]:
    result = set()
    for entry in actx.code_files(tree_id, exts=frozenset({".py"})):
        parts = Path(entry.rel).parts
        if not parts:
            continue
        first = parts[0]
        if len(parts) == 1:
            result.add(Path(first).stem)
        else:
            result.add(first)
    return result


def third_party_imports(tree: ast.Module, local: set[str]) -> set[str]:
    result = set()
    for module, _, _ in imports(tree):
        if not module or module.startswith("."):
            continue
        top = module.split(".", 1)[0]
        if top not in sys.stdlib_module_names and top not in local:
            result.add(top)
    return result
