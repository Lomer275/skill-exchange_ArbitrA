from collections.abc import Callable
from pathlib import Path
import re


def _compile(pattern: str) -> re.Pattern[str] | None:
    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]
    directory = pattern.endswith("/")
    if directory:
        pattern = pattern.rstrip("/")
    if not pattern or any(item in pattern for item in ("[", "]", "\\")):
        return None

    pieces = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                while index + 1 < len(pattern) and pattern[index + 1] == "*":
                    index += 1
                if index + 1 < len(pattern) and pattern[index + 1] == "/":
                    pieces.append("(?:.*/)?")
                    index += 1
                else:
                    pieces.append(".*")
            else:
                pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(char))
        index += 1

    body = "".join(pieces)
    if anchored or "/" in pattern:
        prefix = "^"
    else:
        prefix = r"(?:^|.*/)"
    suffix = r"(?:/.*)?$"
    return re.compile(prefix + body + suffix)


def load_matcher(context_dir: Path) -> Callable[[str], bool] | None:
    path = context_dir / ".dockerignore"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None if path.exists() else lambda rel: False
    except UnicodeError:
        return None

    rules: list[tuple[bool, re.Pattern[str]]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        compiled = _compile(line)
        if compiled is None:
            return None
        rules.append((not negated, compiled))

    def excluded(rel: str) -> bool:
        candidate = rel.replace("\\", "/")
        while candidate.startswith("./"):
            candidate = candidate[2:]
        candidate = candidate.lstrip("/")
        result = False
        for value, regex in rules:
            if regex.match(candidate):
                result = value
        return result

    return excluded
