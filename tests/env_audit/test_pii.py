import json

from envaudit.secrets.pii import scan_json_bytes, valid_inn12


def _valid_inn(prefix: str = "7707083899") -> str:
    for suffix in range(100):
        candidate = prefix + f"{suffix:02d}"
        if valid_inn12(candidate):
            return candidate
    raise AssertionError("valid INN not found")


def test_valid_inn12():
    value = _valid_inn()
    invalid = value[:-1] + str((int(value[-1]) + 1) % 10)
    assert valid_inn12(value) is True
    assert valid_inn12(invalid) is False
    assert valid_inn12("123456789012") is False


def test_json_inn_and_fio():
    value = _valid_inn()
    document = [
        {"inn": value, "fio": "Иванов Иван Иванович"},
        {"inn": value, "fio": "Петров Пётр Петрович"},
    ]
    assert scan_json_bytes(json.dumps(document, ensure_ascii=False).encode()) == (2, 2)


def test_n8n_export_skipped():
    document = {
        "nodes": [{"name": "Иванов Иван Иванович"}],
        "connections": {},
    }
    assert scan_json_bytes(json.dumps(document, ensure_ascii=False).encode()) == (0, 0)


def test_csv_lowercase_cyrillic_inn_header(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "people.csv").write_text(
        f"инн,фио\n{_valid_inn()},Иванов Иван Иванович\n",
        encoding="utf-8",
    )
    section = run_collect("--root", root, "--only", "secrets").data["sections"]["secrets"]
    assert section["roots"][str(root)]["pii_files"] == [
        {
            "path": "people.csv",
            "tracked": None,
            "records_with_valid_inn12": 1,
            "records_with_fio": 1,
        }
    ]
