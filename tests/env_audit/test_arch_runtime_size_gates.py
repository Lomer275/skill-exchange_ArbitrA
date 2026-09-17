from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from envaudit.arch.pyast import parse, sloc

from .arch_builders import isolated_runtime, make_repo, write_systemctl_stub
from .schema_check import validate


def _arch(result, root: Path) -> dict:
    assert result.rc == 0, result.stdout
    validate(result.data)
    return result.data["sections"]["architecture"][str(root.resolve())]


def _date(days_ago: int) -> str:
    value = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "")


def test_sloc_definitions(tmp_path: Path, run_collect) -> None:
    source = (
        "# comment\n"
        "\n"
        '"""first\n'
        "second\n"
        "third\n"
        "fourth\n"
        'fifth"""\n'
        "value = 1"
    )
    assert sloc(source.encode(), python=True) == (8, 6, 1)
    root = tmp_path / "sloc"
    root.mkdir()
    (root / "module.py").write_text(source, encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    metric = arch["size"]["by_language"]["python"]

    assert metric["lines"] == 8
    assert metric["sloc"] == 6
    assert metric["prod_sloc"] == 1


def test_parse_suppresses_syntax_warning(recwarn, capsys) -> None:
    tree = parse(b'pattern = "\\s"\n', "invalid_escape.py")

    assert tree is not None
    assert not recwarn
    assert "SyntaxWarning" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("line_count", "expected"),
    [(1400, "S"), (1600, "M"), (12000, "L")],
)
def test_size_tier(
    tmp_path: Path, run_collect, line_count: int, expected: str
) -> None:
    root = tmp_path / expected
    root.mkdir()
    (root / "app.py").write_text(
        "\n".join(f"value_{index} = {index}" for index in range(line_count)) + "\n",
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text(
        'FROM python:3\nCMD ["python", "app.py"]\n', encoding="utf-8"
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["classification"]["size_tier"] == expected
    assert arch["rule_inputs"]["G1"]["size_tier"] == expected


def test_frozen_and_dormant(tmp_path: Path, run_collect) -> None:
    active = make_repo(
        tmp_path / "active",
        {},
        commits=[
            {
                "files": {
                    "pyproject.toml": "[project]\nname = 'sample'\n",
                    "legacy/old.py": "OLD = 1\n",
                },
                "date": _date(200),
                "message": "old zone",
            },
            {
                "files": {"app/new.py": "NEW = 1\n"},
                "date": _date(5),
                "message": "active zone",
            },
        ],
    )
    dormant = make_repo(
        tmp_path / "dormant",
        {},
        commits=[
            {
                "files": {
                    "pyproject.toml": "[project]\nname = 'sample'\n",
                    "app.py": "VALUE = 1\n",
                },
                "date": _date(120),
                "message": "old repository",
            }
        ],
    )

    active_arch = _arch(run_collect("--only", "architecture", "--root", active), active)
    dormant_arch = _arch(run_collect("--only", "architecture", "--root", dormant), dormant)

    assert active_arch["rule_inputs"]["G2"]["frozen_zones"] == ["legacy"]
    assert dormant_arch["rule_inputs"]["G2"]["dormant_repo"] is True


def test_young_repo_no_age_checks(tmp_path: Path, run_collect) -> None:
    root = make_repo(
        tmp_path / "young",
        {},
        commits=[
            {
                "files": {"pyproject.toml": "[project]\n", "app.py": "VALUE = 1\n"},
                "date": _date(30),
                "message": "young",
            }
        ],
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["rule_inputs"]["G2"]["age_checks"] is False


def test_layers_declared(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "layers"
    (root / "app").mkdir(parents=True)
    (root / "domain").mkdir()
    (root / "infra").mkdir()
    (root / "SUP-architecture.md").write_text(
        "| Layer | Path |\n"
        "|---|---|\n"
        "| Application | `app` |\n"
        "| Domain | `domain` |\n"
        "| Infrastructure | `infra` |\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["rule_inputs"]["G3"]["layers_declared"]["source"] == "architecture_md"


def test_ci_mentions_host_bool_only(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "ci"
    workflow = root / ".github" / "workflows"
    workflow.mkdir(parents=True)
    address = "203.0.113." + "5"
    (workflow / "deploy.yml").write_text(
        "jobs:\n  deploy:\n    steps:\n      - run: ssh root@" + address + " true\n",
        encoding="utf-8",
    )

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)

    assert arch["runtime"]["ci"]["mentions_host"] is True
    assert address not in result.stdout


def test_runtime_ignores_real_host_units(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "isolated"
    root.mkdir()

    result = run_collect(
        "--only",
        "architecture",
        "--root",
        root,
        env_extra={"HOME": str(Path.home())},
    )
    arch = _arch(result, root)

    assert arch["runtime"]["live_units"] == []


def test_systemd_specifier_home(
    fake_home: Path,
    isolated_runtime: Path,
    run_collect,
) -> None:
    root = fake_home / "proj"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_systemctl_stub(
        isolated_runtime,
        {
            "sample.timer": "[Timer]\nOnCalendar=hourly\n",
            "sample.service": (
                "[Service]\n"
                "ExecStart=/usr/bin/python3 %h/proj/app.py\n"
            ),
        },
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    unit = next(
        item
        for item in arch["runtime"]["live_units"]
        if item["source"] == "user_unit"
    )

    assert unit["intersects_root"] is True
    assert unit["entry"] == "app.py"
    assert unit["entry_parse"] == "resolved"


def test_python_m_entry_resolution(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "entry-resolution"
    (root / "a").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "app").mkdir()
    (root / "deploy").mkdir()
    (root / "a" / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg" / "__main__.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (root / "app" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "Dockerfile.module").write_text(
        'FROM python:3\nCMD ["python3.10", "-m", "a.b"]\n',
        encoding="utf-8",
    )
    (root / "Dockerfile.package").write_text(
        'FROM python:3\nENTRYPOINT ["python", "-m", "pkg"]\n',
        encoding="utf-8",
    )
    (root / "docker-compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    build: .\n"
        "    command: gunicorn app.main:app\n",
        encoding="utf-8",
    )
    (root / "deploy" / "module.service").write_text(
        "[Service]\n"
        f"WorkingDirectory={root}\n"
        "ExecStart=/usr/bin/python3.10 -m a.b\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    anchors = arch["runtime"]["anchors"]

    module = next(item for item in anchors if item["file"] == "Dockerfile.module")
    package = next(item for item in anchors if item["file"] == "Dockerfile.package")
    compose = next(
        item for item in anchors if item["kind"] == "compose_services"
    )
    unit = next(item for item in anchors if item["kind"] == "repo_unit")
    assert module["entry"] == "a/b.py"
    assert package["entry"] == "pkg/__main__.py"
    assert compose["entry"] == "app/main.py"
    assert unit["entry"] == "a/b.py"


def test_schema_valid(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "schema"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = run_collect("--only", "architecture", "--root", root)

    validate(result.data)
