from pathlib import Path

from .patterns import find


REDACTED = "<redacted>"
MAX_SCAN_BYTES = 64 * 1024 * 1024


def _pointer_part(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def self_check(doc: object) -> tuple[object, list[str]]:
    pointers: list[str] = []
    redacted_keys = 0

    def visit(value: object, pointer: str) -> object:
        nonlocal redacted_keys
        if isinstance(value, str):
            if find(value.encode("utf-8"), self_check_only=True):
                pointers.append(pointer or "/")
                return REDACTED
            return value
        if isinstance(value, list):
            return [
                visit(item, f"{pointer}/{index}")
                for index, item in enumerate(value)
            ]
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                clean_key = key
                if isinstance(key, str) and find(
                    key.encode("utf-8"), self_check_only=True
                ):
                    redacted_keys += 1
                    clean_key = f"<redacted:{redacted_keys}>"
                    key_pointer = f"{pointer}/{_pointer_part(clean_key)}"
                    pointers.append(key_pointer)
                item_pointer = f"{pointer}/{_pointer_part(clean_key)}"
                clean[clean_key] = visit(item, item_pointer)
            return clean
        return value

    return visit(doc, ""), pointers


def scan_file(path: Path) -> tuple[int, dict]:
    size = path.stat().st_size
    report: dict = {"file": str(path), "size": size, "matches": []}
    if size > MAX_SCAN_BYTES:
        report["too_large"] = True
        return 0, report
    data = path.read_bytes()
    report["matches"] = [
        {"class": match.cls, "line": match.line}
        for match in find(data, self_check_only=True)
    ]
    return (3 if report["matches"] else 0), report
