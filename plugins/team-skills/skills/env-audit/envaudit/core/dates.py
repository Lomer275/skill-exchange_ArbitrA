from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import re


@dataclass(frozen=True)
class DateInfo:
    date: str | None
    source: str | None
    trust: str | None


def _iso(year: str, month: str, day: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def status_date(path: Path, head_text: str | None = None) -> DateInfo:
    for match in re.finditer(r"(20\d\d)[-_.](\d\d)[-_.](\d\d)", path.name):
        parsed = _iso(*match.groups())
        if parsed:
            return DateInfo(parsed, "name", "high")

    if head_text:
        for line in head_text.splitlines()[:50]:
            if not line.startswith("#"):
                continue
            match = re.search(r"(20\d\d)-(\d\d)-(\d\d)", line)
            if match:
                parsed = _iso(*match.groups())
                if parsed:
                    return DateInfo(parsed, "header", "medium")
            match = re.search(r"(\d\d)\.(\d\d)\.(20\d\d)", line)
            if match:
                day, month, year = match.groups()
                parsed = _iso(year, month, day)
                if parsed:
                    return DateInfo(parsed, "header", "medium")

    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return DateInfo(None, None, None)
    return DateInfo(modified.date().isoformat(), "mtime", "low")
