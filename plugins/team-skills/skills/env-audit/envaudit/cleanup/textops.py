from dataclasses import dataclass
import re

from envaudit.core.constants import MEMORY_INDEX_MAX_BYTES


TEAM_BEGIN = "BEGIN team-context"
TEAM_END = "END team-context"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


@dataclass(frozen=True)
class Section:
    title: str
    start_line: int
    end_line: int
    bytes: int
    in_team_block: bool


def _team_lines(lines: list[str]) -> set[int]:
    result = set()
    depth = 0
    for number, line in enumerate(lines, 1):
        if TEAM_BEGIN in line:
            depth += 1
        if depth:
            result.add(number)
        if TEAM_END in line and depth:
            depth -= 1
    return result


def line_in_team_block(text: str, line_no: int) -> bool:
    return line_no in _team_lines(text.splitlines())


def md_sections(text: str, level: int = 2) -> list[Section]:
    lines = text.splitlines(keepends=True)
    managed = _team_lines([line.rstrip("\r\n") for line in lines])
    starts = []
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line.rstrip("\r\n"))
        if match is not None and len(match.group(1)) == level:
            starts.append((index, match.group(2).strip()))

    result = []
    for position, (start, title) in enumerate(starts):
        end = len(lines)
        for index in range(start + 1, len(lines)):
            match = _HEADING_RE.match(lines[index].rstrip("\r\n"))
            if match is not None and len(match.group(1)) <= level:
                end = index
                for marker_index in range(index - 1, start, -1):
                    marker_line = lines[marker_index].strip()
                    if TEAM_BEGIN in marker_line:
                        end = marker_index
                        break
                    if marker_line and marker_line != "<!-- -->":
                        break
                break
        section_text = "".join(lines[start:end])
        start_line = start + 1
        end_line = max(start_line, end)
        result.append(
            Section(
                title=title,
                start_line=start_line,
                end_line=end_line,
                bytes=len(section_text.encode("utf-8")),
                in_team_block=any(number in managed for number in range(start_line, end_line + 1)),
            )
        )
    return result


def insert_after_line(text: str, line_no: int, block: str) -> str:
    lines = text.splitlines(keepends=True)
    if line_no < 0 or line_no > len(lines):
        raise ValueError("line number is outside the text")
    addition = block
    if addition and not addition.endswith(("\n", "\r")):
        addition += "\n"
    if line_no == 0:
        return addition + text
    if lines and not lines[line_no - 1].endswith(("\n", "\r")):
        lines[line_no - 1] += "\n"
    lines.insert(line_no, addition)
    return "".join(lines)


def links(text: str) -> set[str]:
    return {match.group(2).strip() for match in _LINK_RE.finditer(text)}


def _compact_link_lines(text: str, hook_chars: int) -> list[str]:
    compact = []
    seen_targets = set()
    for line in text.splitlines():
        matches = list(_LINK_RE.finditer(line))
        if not matches:
            stripped = line.strip()
            if stripped:
                compact.append(stripped[:hook_chars])
            continue
        hook = _LINK_RE.sub("", line).strip(" \t-*·—:;")[:hook_chars].strip()
        pieces = []
        for match in matches:
            target = match.group(2).strip()
            if target in seen_targets:
                continue
            seen_targets.add(target)
            label = match.group(1).strip()[:hook_chars] or str(len(seen_targets))
            pieces.append(f"[{label}]({target})")
        if pieces:
            prefix = f"{hook}: " if hook else ""
            compact.append("- " + prefix + " · ".join(pieces))
    return compact


def _pack(lines: list[str], maximum: int) -> list[str]:
    if len(lines) <= maximum:
        return lines
    chunk_size = (len(lines) + maximum - 1) // maximum
    return [
        "- " + " · ".join(line.lstrip("- ") for line in lines[index : index + chunk_size])
        for index in range(0, len(lines), chunk_size)
    ]


def compress_memory_index(
    text: str,
    *,
    max_lines: int = 200,
    max_bytes: int = MEMORY_INDEX_MAX_BYTES,
    hook_chars: int = 80,
) -> tuple[str, bool]:
    if len(text.splitlines()) <= max_lines and len(text.encode("utf-8")) <= max_bytes:
        return text, True

    original_links = links(text)
    compact = _pack(_compact_link_lines(text, hook_chars), max_lines)
    candidate = "\n".join(compact) + ("\n" if compact else "")
    if links(candidate) == original_links and len(candidate.encode("utf-8")) <= max_bytes:
        return candidate, True

    minimal = [f"[{index}]({target})" for index, target in enumerate(sorted(original_links), 1)]
    minimal = _pack(minimal, max_lines)
    candidate = "\n".join(minimal) + ("\n" if minimal else "")
    fits = (
        links(candidate) == original_links
        and len(candidate.splitlines()) <= max_lines
        and len(candidate.encode("utf-8")) <= max_bytes
    )
    return candidate, fits
