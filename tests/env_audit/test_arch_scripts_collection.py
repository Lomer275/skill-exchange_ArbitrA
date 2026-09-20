from pathlib import Path
from types import SimpleNamespace

from envaudit.arch.checks import scripts_collection

from .arch_builders import (
    ir2_like,
    isolated_runtime,
    write_crontab_stub,
    write_systemctl_stub,
)


def _arch(result, root: Path) -> dict:
    assert result.rc == 0, result.stdout
    return result.data["sections"]["architecture"][str(root.resolve())]


def _scripts_root(path: Path) -> Path:
    ir2_like(path, py_files=20)
    return path


def test_i5_god_deployed_dedup(tmp_path: Path, run_collect) -> None:
    root = _scripts_root(tmp_path / "project")
    hub = "<?php\nfunction work() {}\n" + "$value += 1;\n" * 900
    for rel in ("local/a/hub.php", "local/b/hub.php"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(hub, encoding="utf-8")
    mobile = root / "local" / "data" / "mobile_ranges.php"
    mobile.parent.mkdir(parents=True)
    line = "'79000000000' => 'region',\n"
    mobile.write_text("<?php\n" + line * ((13 * 1024 * 1024) // len(line) + 1), encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    gods = arch["scripts_collection"]["god_files_deployed"]

    assert len(gods) == 1
    assert gods[0]["path"] == "local/a/hub.php"
    assert gods[0]["copies"] == 2


def test_i6_parents_resolution(tmp_path: Path, run_collect) -> None:
    root = _scripts_root(tmp_path / "project")
    loader = root / "jobs" / "deep" / "load.py"
    target = root / "jobs" / "lib" / "x.py"
    loader.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    loader.write_text(
        "from importlib.util import spec_from_file_location\n"
        "from pathlib import Path\n"
        "spec_from_file_location('x', Path(__file__).parents[1] / 'lib' / 'x.py')\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    assert arch["scripts_collection"]["loaders"]["targets_missing"] == []

    loader.write_text(
        "from importlib.util import spec_from_file_location\n"
        "from pathlib import Path\n"
        "spec_from_file_location('x', Path(__file__).parents[2] / 'lib' / 'x.py')\n",
        encoding="utf-8",
    )
    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    assert len(arch["scripts_collection"]["loaders"]["targets_missing"]) == 1


def test_i6_stdlib_import_not_target(tmp_path: Path, run_collect) -> None:
    root = _scripts_root(tmp_path / "project")
    (root / "load.py").write_text(
        "import importlib\n"
        "importlib.import_module('sys')\n"
        "__import__('sys')\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    loaders = arch["scripts_collection"]["loaders"]

    assert loaders["targets_total"] == 0
    assert loaders["targets_missing"] == []


def test_i6_fan_in_top(tmp_path: Path, run_collect) -> None:
    root = _scripts_root(tmp_path / "project")
    lib = root / "lib"
    lib.mkdir()
    (lib / "common.py").write_text("VALUE = 1\n", encoding="utf-8")
    (lib / "other.py").write_text("VALUE = 2\n", encoding="utf-8")
    for index in range(3):
        (root / f"load_common_{index}.py").write_text(
            "from importlib.util import spec_from_file_location\n"
            "from pathlib import Path\n"
            "spec_from_file_location('common', Path(__file__).parent / 'lib' / 'common.py')\n",
            encoding="utf-8",
        )
    (root / "load_other.py").write_text(
        "from importlib.util import spec_from_file_location\n"
        "from pathlib import Path\n"
        "spec_from_file_location('other', Path(__file__).parent / 'lib' / 'other.py')\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["scripts_collection"]["loaders"]["fan_in_top"] == [
        {"target": "lib/common.py", "loaders": 3, "live_loaders": 0}
    ]


def test_i7_helpers_three_copies(
    tmp_path: Path,
    isolated_runtime: Path,
    run_collect,
) -> None:
    root = _scripts_root(tmp_path / "project")
    live = []
    for index in range(3):
        name = f"helper_{index}.py"
        (root / name).write_text(
            "def _bitrix_call(value):\n"
            "    return value + 1\n",
            encoding="utf-8",
        )
        live.append(f"*/5 * * * * cd {root} && python3 {name}")
    for index in range(5):
        (root / f"helper_20260{index + 1}01.py").write_text(
            "def _bitrix_call(value):\n"
            "    return value + 1\n"
            "if __name__ == '__main__':\n"
            "    _bitrix_call(1)\n",
            encoding="utf-8",
        )
    live.append("*/5 * * * * cd /home/x/p && python3 run.py")
    write_crontab_stub(isolated_runtime, live)
    write_systemctl_stub(
        isolated_runtime,
        {
            "external.timer": "[Timer]\nOnCalendar=*:0/5\n",
            "external.service": "[Service]\nExecStart=/usr/bin/python3 /home/x/p/run.py\n",
        },
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    groups = arch["scripts_collection"]["infra_helper_defs"]["groups"]

    assert groups == [{"name": "_bitrix_call", "copies": 3}]


def test_i8_flat_dir(tmp_path: Path, run_collect) -> None:
    root = _scripts_root(tmp_path / "project")
    flat = root / "runs"
    flat.mkdir()
    for index in range(1200):
        (flat / f"{index:04d}.json").write_text("{}\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    item = arch["scripts_collection"]["flat_dirs"][0]

    assert item["direct_files"] == 1200
    assert item["has_code_files"] is False


def test_i12_self_nested(tmp_path: Path, run_collect) -> None:
    root = _scripts_root(tmp_path / "project")
    path = root / "Финансовый учет" / "Финансовый учет" / "a.py"
    path.parent.mkdir(parents=True)
    path.write_text("VALUE = 1\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["scripts_collection"]["self_nested_paths"] == [
        "Финансовый учет/Финансовый учет"
    ]


def test_i15_overlap(tmp_path: Path, run_collect) -> None:
    root = _scripts_root(tmp_path / "project")
    common = [f"shared instruction {index}" for index in range(20)]
    (root / "CLAUDE.md").write_text("\n".join([*common, "claude only"]) + "\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("\n".join([*common, "agents only"]) + "\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["scripts_collection"]["instruction_overlap"] == 20


def test_applicable_only_scripts(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "service"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "Dockerfile").write_text(
        'FROM python:3\nCMD ["python", "app.py"]\n', encoding="utf-8"
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["classification"]["type"] == "application"
    assert arch["classification"]["subtype"] == "service"
    assert arch["rule_inputs"]["I5"] == {"applicable": False}


def test_extends_t456_dict() -> None:
    actx = SimpleNamespace(
        out={
            "classification": {"type": "application"},
            "scripts_collection": {"copies_by_relpath": [{"relpath": "x.py"}]},
        },
        rule_inputs={},
        error=lambda *_args: None,
    )

    scripts_collection.run(actx)

    assert actx.out["scripts_collection"]["copies_by_relpath"] == [
        {"relpath": "x.py"}
    ]
