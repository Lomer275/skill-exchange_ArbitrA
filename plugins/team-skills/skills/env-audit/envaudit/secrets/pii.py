import json
import re


INN_KEYS = frozenset({"inn", "инн"})
FIO_KEYS = frozenset({"name", "fio", "contact_name", "фио"})
FIO_RE = re.compile(r"^[А-ЯЁа-яё-]+(?:\s+[А-ЯЁа-яё-]+){2}$")


def valid_inn12(s: str) -> bool:
    if len(s) != 12 or not s.isascii() or not s.isdigit():
        return False
    if s == "123456789012":
        return False
    digits = [int(item) for item in s]
    first = (7 * digits[0] + 2 * digits[1] + 4 * digits[2] + 10 * digits[3]
             + 3 * digits[4] + 5 * digits[5] + 9 * digits[6] + 4 * digits[7]
             + 6 * digits[8] + 8 * digits[9]) % 11 % 10
    second = (3 * digits[0] + 7 * digits[1] + 2 * digits[2] + 4 * digits[3]
              + 10 * digits[4] + 3 * digits[5] + 5 * digits[6] + 9 * digits[7]
              + 4 * digits[8] + 6 * digits[9] + 8 * digits[10]) % 11 % 10
    return digits[10] == first and digits[11] == second


def _record_flags(value: dict) -> tuple[bool, bool]:
    has_inn = False
    has_fio = False
    for key, item in value.items():
        folded = str(key).casefold()
        if folded in INN_KEYS and valid_inn12(str(item)):
            has_inn = True
        if folded in FIO_KEYS and isinstance(item, str) and FIO_RE.fullmatch(item.strip()):
            has_fio = True
    return has_inn, has_fio


def scan_json_bytes(data: bytes) -> tuple[int, int]:
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0, 0
    if isinstance(document, dict) and "nodes" in document and "connections" in document:
        return 0, 0

    inn_records = 0
    fio_records = 0

    def visit(value: object) -> None:
        nonlocal inn_records, fio_records
        if isinstance(value, dict):
            has_inn, has_fio = _record_flags(value)
            inn_records += int(has_inn)
            fio_records += int(has_fio)
            for item in value.values():
                if isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(document)
    return inn_records, fio_records
