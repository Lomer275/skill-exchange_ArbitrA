from dataclasses import dataclass
import re

from .canon import PATH_TOKEN, normalize_target


WRITE_VERBS = r"(?i)\b(write|update|create|append|save|record|запиш\w*|обнов\w*|созда\w*|допиш\w*|сохран\w*|пишет|внеси\w*|добав\w*)\b"

_VERB_RE = re.compile(WRITE_VERBS)
_PATH_RE = re.compile(PATH_TOKEN, re.IGNORECASE)
_EXTRA_RE = re.compile(
    r"[\w./{}<>*\-]*(?:handoffs/|projects-state(?:/[\w./{}<>*\-]*)?|memory/[\w./{}<>*\-]+|(?:[\w-]+-)?CHANGELOG(?:\.md)?)",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^(\s*)(?:[-+*]|\d+[.)])\s+")


@dataclass(frozen=True)
class WriteTarget:
    target: str
    kind: str
    line: int
    confidence: str


def _list_item(lines: list[str], index: int) -> list[str] | None:
    current = index
    start = None
    indent = None
    while current >= 0:
        match = _LIST_RE.match(lines[current])
        if match is not None:
            indent = len(match.group(1))
            for between in range(current + 1, index + 1):
                line = lines[between]
                if not line.strip():
                    continue
                if _HEADING_RE.match(line) or _LIST_RE.match(line):
                    return None
                leading = len(line) - len(line.lstrip())
                if leading <= indent:
                    return None
            start = current
            break
        if lines[current].strip() and (
            _HEADING_RE.match(lines[current]) or not lines[current][0].isspace()
        ):
            return None
        current -= 1
    if start is None or indent is None:
        return None
    end = index + 1
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            end += 1
            continue
        if _HEADING_RE.match(line) or _LIST_RE.match(line):
            break
        leading = len(line) - len(line.lstrip())
        if leading <= indent:
            break
        end += 1
    return lines[start:end]


def _kind(target: str) -> str:
    upper = target.upper()
    if "CHANGELOG" in upper:
        return "CHANGELOG"
    if "HANDOFF" in upper or "HANDOFFS/" in upper:
        return "HANDOFF"
    return "OTHER"


def write_targets(text: str) -> list[WriteTarget]:
    lines = text.splitlines()
    result = []
    seen = set()
    for index, line in enumerate(lines):
        matches = list(_PATH_RE.finditer(line)) + list(_EXTRA_RE.finditer(line))
        matches.sort(key=lambda match: (match.start(), -(match.end() - match.start())))
        item = _list_item(lines, index)
        intent = bool(_VERB_RE.search(line)) or bool(
            item and _VERB_RE.search("\n".join(item))
        )
        occupied = []
        for match in matches:
            span = match.span()
            if any(span[0] >= start and span[1] <= end for start, end in occupied):
                continue
            target = normalize_target(match.group(0)).rstrip(".")
            if not target:
                continue
            key = (index + 1, target)
            if key in seen:
                continue
            occupied.append(span)
            seen.add(key)
            result.append(
                WriteTarget(
                    target=target,
                    kind=_kind(target),
                    line=index + 1,
                    confidence="verb_on_line" if intent else "mention_only",
                )
            )
    return result


def agents_md_close_section(text: str) -> str | None:
    lines = text.splitlines(keepends=True)
    start = None
    level = None
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line.rstrip("\r\n"))
        if match is not None and re.search(r"(?<![\w-])/close(?![\w-])", match.group(2)):
            start = index
            level = len(match.group(1))
            break
    if start is None or level is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = _HEADING_RE.match(lines[index].rstrip("\r\n"))
        if match is not None and len(match.group(1)) <= level:
            end = index
            break
    return "".join(lines[start:end])
