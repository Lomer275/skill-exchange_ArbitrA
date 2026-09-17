import json
from pathlib import Path
import re

import jsonschema

from .schema_check import validate
import pytest

from envaudit.arch.php_lexer import strip_php

from .arch_builders import isolated_runtime, make_repo
from .canaries import canary, fragments
from .conftest import SKILL_DIR


def _arch(result, root: Path) -> dict:
    assert result.rc == 0, result.stdout
    return result.data["sections"]["architecture"][str(root.resolve())]


def test_php_lexer_mixed_html_js(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    root.mkdir()
    data = (
        b"<main>html</main>\n"
        b"<?php $x = 'function x('; // function y(\n"
        b"$doc = <<<TXT\nfunction z(\nTXT;\n?>\n"
        b"<script>function w(){}</script>\n"
        b"<?php function real() {} ?>\n"
    )
    (root / "widget.php").write_bytes(data)

    stripped = strip_php(data)
    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert len(stripped) == len(data)
    assert stripped.count(b"\n") == data.count(b"\n")
    assert len(re.findall(rb"\bfunction\s+[A-Za-z_]\w*\s*\(", stripped)) == 1
    assert arch["php"]["files_top"][0]["functions"] == 1


def test_php_top_and_host_markers(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    root.mkdir()
    lines = ["<?php"]
    lines.extend(f"function work_{index}() {{}}" for index in range(50))
    lines.extend("CCrmDeal::GetList();" for _ in range(3))
    lines.extend("curl_init();" for _ in range(14))
    lines.extend("$value += 1;" for _ in range(1532 - len(lines)))
    (root / "service.php").write_text("\n".join(lines) + "\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    top = arch["php"]["files_top"][0]

    assert top["lines"] == 1532
    assert top["functions"] == 50
    assert top["host_markers"] == 3
    assert top["curl_calls"] == 14
    assert arch["rule_inputs"]["A11"]["php"]["candidates"] == ["service.php"]


def test_js_n8n_hosts_only(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    root.mkdir()
    probe = canary("bitrix_webhook", seed=459)
    workflow = {
        "nodes": [
            {
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {
                    "url": f"https://bitrix.example.org{probe}/crm.deal.get?x=1"
                },
            }
        ],
        "connections": {},
    }
    (root / "workflow.json").write_text(json.dumps(workflow), encoding="utf-8")

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)

    assert arch["js"]["n8n_workflows"][0]["url_hosts"] == [
        "bitrix.example.org"
    ]
    assert all(item not in result.stdout for item in fragments(probe))


def _class_source(revision: int) -> str:
    lines = [
        "public class MainViewModel",
        "{",
        (
            "    public MainViewModel(IServiceA a, IServiceB b, IServiceC c, "
            "IServiceD d, IServiceE e, IServiceF f, IServiceG g, string title, "
            "CancellationToken cancellation)"
        ),
        "    {",
        "    }",
        f"    // revision {revision}",
    ]
    lines.extend("    public int Value => 1;" for _ in range(923 - len(lines)))
    lines.append("}")
    assert len(lines) == 924
    return "\n".join(lines) + "\n"


def test_csharp_ctor_params_and_g(tmp_path: Path, run_collect) -> None:
    commits = [
        {"files": {"MainViewModel.cs": _class_source(index)}, "message": f"class-{index}"}
        for index in range(10)
    ]
    commits.extend(
        {
            "files": {f"notes/note_{index}.txt": f"note {index}\n"},
            "message": f"other-{index}",
        }
        for index in range(7)
    )
    root = make_repo(tmp_path / "project", {}, commits=commits)

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    top = arch["csharp"]["classes_top"][0]
    item = arch["rule_inputs"]["A11"]["csharp_g"][0]

    assert top["class"] == "MainViewModel"
    assert top["lines"] == 924
    assert top["ctor_params_nonprimitive"] == 7
    assert item["class"] == "MainViewModel"
    assert item["churn_share"] == pytest.approx(10 / 17, abs=0.01)


def test_blind_spots_majority(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cs_lines = ["public class Main {", *["public int Value => 1;" for _ in range(71)], "}"]
    (root / "Main.cs").write_text("\n".join(cs_lines) + "\n", encoding="utf-8")
    (root / "worker.py").write_text(
        "\n".join(f"value_{index} = {index}" for index in range(27)) + "\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert any(
        item["language"] == "csharp"
        and item["what"] == "majority_language_metrics_only"
        and item["share_of_code"] == pytest.approx(0.73, abs=0.01)
        for item in arch["blind_spots"]
    )


def test_no_graph_fields(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "index.php").write_text("<?php function main() {}\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert "require_edges" not in arch["php"]
    assert "call_edges" not in arch["php"]


def test_schema_valid(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "index.php").write_text("<?php function main() {}\n", encoding="utf-8")
    (root / "index.js").write_text("export const value = 1;\n", encoding="utf-8")
    (root / "Main.cs").write_text("public class Main {}\n", encoding="utf-8")

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)
    for name in ("php", "js", "csharp"):
        schema = json.loads(
            (SKILL_DIR / "schema" / "arch" / f"{name}.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(arch[name])
    validate(result.data)
