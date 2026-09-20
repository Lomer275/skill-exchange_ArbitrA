from pathlib import Path

from envaudit.arch.py.graph import iterative_tarjan

from .arch_builders import isolated_runtime
from .py_builders import make_package
from .schema_check import validate


def _arch(run_collect, root: Path) -> dict:
    result = run_collect("--only", "architecture", "--root", root)
    assert result.rc == 0, result.stdout
    validate(result.data)
    return result.data["sections"]["architecture"][str(root.resolve())]


def test_lazy_and_type_checking_edges(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "lazy",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "a.py"]\n',
            "a.py": "def load():\n    import b\n    return b.VALUE\n",
            "b.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import a\nVALUE = 1\n",
            "types_mod.py": "class Thing:\n    pass\n",
            "c.py": "from types_mod import Thing\ndef use(value: Thing):\n    return 1\n",
        },
    )
    arch = _arch(run_collect, root)
    assert arch["python"]["scc"]["module_level"] == []
    assert arch["python"]["scc"]["with_lazy"] == []
    assert arch["python"]["edges"]["annotation_only"] == 1


def test_cross_package_scc(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "cycle",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "p1/x.py"]\n',
            "p1/__init__.py": "",
            "p1/x.py": "import p2.y\n",
            "p2/__init__.py": "",
            "p2/y.py": "import p1.x\n",
        },
    )
    arch = _arch(run_collect, root)
    assert arch["rule_inputs"]["A10"]["cross_package_module_scc"] == 1


def test_flat_cycle_is_not_cross_package(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "flat-cycle",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "x.py"]\n',
            "x.py": "import y\n",
            "y.py": "import x\n",
        },
    )
    arch = _arch(run_collect, root)
    assert arch["rule_inputs"]["A10"]["cross_package_module_scc"] == 0
    assert arch["rule_inputs"]["A10"]["in_package_module_scc"] == 1


def test_init_reexport_and_package_node(tmp_path: Path, run_collect) -> None:
    files = {
        "Dockerfile": 'FROM python:3\nCMD ["python", "run.py"]\n',
        "pkg/__init__.py": "from .impl import exported\n",
        "pkg/impl.py": "def exported():\n    return 1\n",
    }
    files.update({f"caller_{index}.py": "import pkg\n" for index in range(5)})
    root = make_package(tmp_path / "reexport", files)
    arch = _arch(run_collect, root)
    fan_in = {item["path"]: item["fan_in"] for item in arch["python"]["fan_in_top"]}
    assert fan_in["pkg/impl.py"] == 5
    assert "pkg/__init__.py" not in fan_in
    assert arch["python"]["scc"]["module_level"] == []


def test_iterative_tarjan_deep_chain() -> None:
    graph = {f"m{index}": {f"m{index + 1}"} for index in range(2999)}
    graph["m2999"] = {"m0"}
    components = iterative_tarjan(graph)
    assert len(components) == 1
    assert len(components[0]) == 3000


def test_test_prefix_outside_tests_is_production(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "test-prefix",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "main.py"]\n',
            "main.py": "import Handler.test_flag\n",
            "Handler/__init__.py": "",
            "Handler/test_flag.py": "VALUE = 1\n",
        },
    )
    arch = _arch(run_collect, root)
    fan_in = {item["path"]: item["fan_in"] for item in arch["python"]["fan_in_top"]}
    assert fan_in["Handler/test_flag.py"] == 1
    assert arch["python"]["tests"]["files"] == 0


def test_newer_python_syntax_is_reported(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "new-syntax",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "main.py"]\n',
            "main.py": "VALUE = 1\n",
            "newer.py": "type Alias = int\n",
        },
    )
    arch = _arch(run_collect, root)
    assert {
        (item["path"], item["kind"])
        for item in arch["python"]["parse_errors"]
    } == {("newer.py", "SyntaxError")}
