from dataclasses import dataclass, field

from envaudit.core import patterns


GENERIC_MARKERS = (b"key", b"token", b"secret", b"password")
GENERIC_CLASS = next(
    item for item in patterns.CLASSES if item.name == "generic_assignment"
)
SPECIFIC_MARKERS = tuple(
    marker
    for item in patterns.CLASSES
    if item.self_check
    for marker in item.prefilter
)


@dataclass
class ClassStats:
    files: int = 0
    matches: int = 0
    distinct: int = 0
    fake_filtered: int = 0
    test_fixture_files: int = 0
    user_ids: set[int] = field(default_factory=set)
    paths_sample: list[str] = field(default_factory=list)


class Counter:
    """Count secret classes without retaining values after serialization."""

    def __init__(self) -> None:
        self._stats = {item.name: ClassStats() for item in patterns.CLASSES}
        self._values: dict[str, set[bytes]] = {
            item.name: set() for item in patterns.CLASSES
        }
        self._files: dict[str, set[str]] = {
            item.name: set() for item in patterns.CLASSES
        }
        self._fixture_files: dict[str, set[str]] = {
            item.name: set() for item in patterns.CLASSES
        }
        self._production_values: dict[str, set[bytes]] = {
            item.name: set() for item in patterns.CLASSES
        }
        self._fixture_values: dict[str, dict[str, set[bytes]]] = {
            item.name: {} for item in patterns.CLASSES
        }

    def add(
        self,
        cls: str,
        value: bytes,
        *,
        path_rel: str,
        is_fixture: bool,
    ) -> None:
        self._add(
            cls,
            value,
            path_rel=path_rel,
            is_fixture=is_fixture,
            fake=patterns.is_fake(value),
        )

    def _add(
        self,
        cls: str,
        value: bytes,
        *,
        path_rel: str,
        is_fixture: bool,
        fake: bool,
    ) -> None:
        stats = self._stats[cls]
        if fake:
            stats.fake_filtered += 1
            return
        stats.matches += 1
        self._values[cls].add(value)
        user_id = patterns.webhook_user_id(value)
        if user_id is not None:
            stats.user_ids.add(user_id)
        if path_rel not in stats.paths_sample and len(stats.paths_sample) < 10:
            stats.paths_sample.append(path_rel)
        if is_fixture:
            self._fixture_values[cls].setdefault(path_rel, set()).add(value)
        else:
            self._files[cls].add(path_rel)
            self._production_values[cls].add(value)

    def as_dict(self) -> dict[str, dict]:
        result = {}
        for secret_class in patterns.CLASSES:
            cls = secret_class.name
            stats = self._stats[cls]
            fixture_only = set()
            regular = set(self._files[cls])
            for path, values in self._fixture_values[cls].items():
                if values & self._production_values[cls]:
                    regular.add(path)
                else:
                    fixture_only.add(path)
            stats.files = len(regular)
            stats.test_fixture_files = len(fixture_only)
            stats.distinct = len(self._values[cls])
            result[cls] = {
                "files": stats.files,
                "matches": stats.matches,
                "distinct": stats.distinct,
                "fake_filtered": stats.fake_filtered,
                "test_fixture_files": stats.test_fixture_files,
                "user_ids": sorted(stats.user_ids),
                "paths_sample": list(stats.paths_sample),
            }
        return result


def scan_bytes(
    data: bytes,
    counter: Counter,
    *,
    path_rel: str,
    is_fixture: bool,
    include_generic: bool,
) -> int:
    return _scan_bytes_many(
        data,
        (counter,),
        path_rel=path_rel,
        is_fixture=is_fixture,
        include_generic=include_generic,
    )


def _scan_bytes_many(
    data: bytes,
    counters: tuple[Counter, ...],
    *,
    path_rel: str,
    is_fixture: bool,
    include_generic: bool,
) -> int:
    accepted = 0
    specific_candidate = any(marker in data for marker in SPECIFIC_MARKERS)
    matches: list[tuple[str, int, int]] = []
    if specific_candidate:
        matches.extend(
            (match.cls, match.start, match.end)
            for match in patterns.find(data, self_check_only=True)
        )

    if include_generic and (b"=" in data or b":" in data):
        lowered = data.lower()
        if any(marker in lowered for marker in GENERIC_MARKERS):
            matches.extend(
                ("generic_assignment", match.start(), match.end())
                for match in GENERIC_CLASS.regex.finditer(data)
            )

    for cls, start, end in matches:
        value = data[start:end]
        fake = patterns.is_fake(value)
        for counter in counters:
            counter._add(
                cls,
                value,
                path_rel=path_rel,
                is_fixture=is_fixture,
                fake=fake,
            )
        if not fake and cls != "generic_assignment":
            accepted += 1
    return accepted


def is_fixture_path(rel: str) -> bool:
    parts = tuple(part.casefold() for part in rel.replace("\\", "/").split("/"))
    name = parts[-1] if parts else ""
    return (
        "tests" in parts
        or "test" in parts[:-1]
        or "fixtures" in parts
        or name == "conftest.py"
    )
