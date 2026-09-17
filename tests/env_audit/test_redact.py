import json
import time

from envaudit.core.context import Context, Flags
from envaudit.core.output import finalize
from envaudit.core.redact import REDACTED, scan_file, self_check

from .canaries import CANARY_CLASSES, canary, fragments


def _context(tmp_path):
    started = time.time()
    return Context(Flags(), tmp_path, [tmp_path], started, started + 300)


def test_self_check_redacts_value_and_key():
    value = canary("openai_key", seed=3)
    clean, pointers = self_check({"a": value, value: 1, "b": "ok"})
    assert clean == {"a": REDACTED, "<redacted:1>": 1, "b": "ok"}
    assert len(pointers) == 2


def test_finalize_code_3_and_error(tmp_path):
    ctx = _context(tmp_path)
    value = canary("github_token", seed=5)
    doc = {"errors": [], "exit_code": 0, "sections": {"x": {"value": value}}}
    clean, code = finalize(doc, ctx)
    assert code == 3
    assert clean["sections"]["x"]["value"] == REDACTED
    assert {"section": "x", "kind": "self_check_redaction"} in clean["errors"]


def test_output_has_no_fragments(tmp_path):
    ctx = _context(tmp_path)
    value = canary("anthropic_key", seed=6)
    doc = {"errors": [], "exit_code": 0, "sections": {"x": {"value": value}}}
    clean, _ = finalize(doc, ctx)
    serialized = json.dumps(clean)
    assert all(fragment not in serialized for fragment in fragments(value))


def test_scan_file_clean(tmp_path):
    path = tmp_path / "clean.txt"
    path.write_text("ordinary content", encoding="utf-8")
    code, report = scan_file(path)
    assert code == 0
    assert report["matches"] == []


def test_scan_file_canary(tmp_path):
    classes = [name for name in CANARY_CLASSES if name != "generic_assignment"]
    values = [canary(name, seed=index + 10) for index, name in enumerate(classes)]
    path = tmp_path / "probe.txt"
    path.write_text("\n".join(values), encoding="utf-8")
    code, report = scan_file(path)
    assert code == 3
    assert {(item["class"], item["line"]) for item in report["matches"]} == {
        (name, index + 1) for index, name in enumerate(classes)
    }
    serialized = json.dumps(report)
    assert all(
        fragment not in serialized
        for value in values
        for fragment in fragments(value)
    )
