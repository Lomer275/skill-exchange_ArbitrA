from pathlib import Path
import sys

from .arch_builders import (
    isolated_runtime,
    ir2_like,
    write_crontab_stub,
    write_systemctl_stub,
)
from .canaries import canary, fragments
from .py_builders import big_module, make_package
from .schema_check import validate


def _result(run_collect, root: Path, *args: object):
    result = run_collect("--only", "architecture", "--root", root, *args)
    assert result.rc == 0, result.stdout
    validate(result.data)
    arch = result.data["sections"]["architecture"][str(root.resolve())]
    return arch, result


def test_config_value_classes_no_values(tmp_path: Path, run_collect) -> None:
    sample = canary("generic_assignment", seed=457)
    probe = sample.partition("=")[2]
    root = make_package(
        tmp_path / "config-values",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "main.py"]\n',
            "main.py": "import os\nVALUE = os.getenv('EMPTY_VALUE')\n",
            ".env.example": (
                "EMPTY_VALUE=\n"
                "BOOL_VALUE=true\n"
                "PLACEHOLDER_VALUE=your-value\n"
                "PATH_VALUE=/srv/application\n"
                "NUMERIC_VALUE=123456789\n"
                "ENTROPY_VALUE=" + probe + "\n"
                "FAKE_VALUE=xxxxxxxxxxxxxxxxxxxxxxxx\n"
            ),
        },
    )
    arch, result = _result(run_collect, root)
    classes = {
        item["name"]: item["class"]
        for template in arch["python"]["config"]["templates"]
        for item in template["keys"]
    }
    assert classes == {
        "EMPTY_VALUE": "empty",
        "BOOL_VALUE": "bool",
        "PLACEHOLDER_VALUE": "placeholder",
        "PATH_VALUE": "path",
        "NUMERIC_VALUE": "numeric_id",
        "ENTROPY_VALUE": "long_high_entropy",
        "FAKE_VALUE": "fake",
    }
    assert all(part not in result.stdout for part in fragments(probe))


def test_pytest_collect_flag(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "collect",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "app.py"]\n',
            "app.py": "VALUE = 1\n",
            "tests/test_app.py": (
                "def test_one():\n    assert True\n"
                "def test_two():\n    assert True\n"
                "def test_three():\n    assert True\n"
            ),
        },
    )
    arch, _ = _result(
        run_collect,
        root,
        "--pytest-collect",
        "--pytest-python",
        sys.executable,
    )
    assert arch["python"]["tests"]["collected"] == 3
    assert not (root / ".pytest_cache").exists()


def test_pytest_collect_error_null(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "collect-error",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "app.py"]\n',
            "app.py": "VALUE = 1\n",
            "tests/test_bad.py": "def test_bad(:\n    pass\n",
        },
    )
    arch, _ = _result(
        run_collect,
        root,
        "--pytest-collect",
        "--pytest-python",
        sys.executable,
    )
    assert arch["python"]["tests"]["collected"] is None
    assert arch["python"]["tests"]["collect_errors"] >= 1


def test_size_s_metrics_only(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "small",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "app.py"]\n',
            "app.py": big_module(1100, 5),
        },
    )
    arch, _ = _result(run_collect, root)
    assert arch["classification"]["size_tier"] == "S"
    assert arch["rule_inputs"]["A11"]["metrics_only"] is True


def test_integration_scripts_not_applicable(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "scripts"
    ir2_like(root)
    arch, _ = _result(run_collect, root)
    assert arch["classification"]["type"] == "integration-scripts"
    assert arch["python"]["channels"] == {"applicable": False}
    assert arch["python"]["modules"] == 40
    assert arch["python"]["tests"]["files"] == 0


def test_schema_valid(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "schema",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "app.py"]\n',
            "app.py": "VALUE = 1\n",
        },
    )
    _, result = _result(run_collect, root)
    validate(result.data)


def test_unrelated_host_runtime_sources_do_not_change_result(
    tmp_path: Path,
    isolated_runtime: Path,
    run_collect,
) -> None:
    write_crontab_stub(
        isolated_runtime,
        ["*/5 * * * * cd /home/x/p && python3 run.py"],
    )
    write_systemctl_stub(
        isolated_runtime,
        {
            "outside.timer": "[Timer]\nOnCalendar=hourly\n",
            "outside.service": "[Service]\nExecStart=/usr/bin/python3 /home/x/p/run.py\n",
        },
    )
    root = make_package(
        tmp_path / "isolated-runtime",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "app.py"]\n',
            "app.py": "VALUE = 1\n",
        },
    )
    arch, _ = _result(run_collect, root)
    assert arch["classification"]["type"] == "application"
    assert arch["python"]["modules"] == 1
