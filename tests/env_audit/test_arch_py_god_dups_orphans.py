from pathlib import Path
import subprocess

import pytest

from .arch_builders import isolated_runtime, make_bare, make_repo
from .py_builders import big_module, django_app, make_package
from .schema_check import validate


def _arch(run_collect, root: Path) -> dict:
    result = run_collect("--only", "architecture", "--root", root)
    assert result.rc == 0, result.stdout
    validate(result.data)
    return result.data["sections"]["architecture"][str(root.resolve())]


def test_god_candidate_and_exclusions(tmp_path: Path, run_collect) -> None:
    assignments = "\n".join(f"VALUE_{index} = {index}" for index in range(1200)) + "\n"
    prompt = 'PROMPT = """' + "\n".join("prompt" for _ in range(1900)) + '"""\n'
    prompt += "\n".join(f"value_{index} = {index}" for index in range(100)) + "\n"
    root = make_package(
        tmp_path / "god",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "app.py"]\n',
            "app.py": big_module(900, 20),
            "settings.py": big_module(1200, 20),
            "registry.py": assignments,
            "prompts.py": prompt,
        },
    )
    arch = _arch(run_collect, root)
    assert arch["rule_inputs"]["A11"]["candidates"] == ["app.py"]


def test_god_signal_b_growth(tmp_path: Path, run_collect) -> None:
    root = make_repo(
        tmp_path / "growth",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "app.py"]\n',
            "app.py": big_module(1532, 25),
        },
    )
    subprocess.run(["git", "-C", str(root), "checkout", "-b", "alt"], check=True, capture_output=True)
    (root / "app.py").write_text(big_module(2391, 25), encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "grow"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "checkout", "main"], check=True, capture_output=True)
    arch = _arch(run_collect, root)
    signal = arch["rule_inputs"]["A11"]["signals"]["app.py"]
    assert signal["growth_vs_alt"] == pytest.approx(0.56, abs=0.01)
    assert signal["test_importers"] == 0
    assert signal["in_dispatcher_closure"] is True


def test_dup_basename_orphan_shadowed(tmp_path: Path, run_collect) -> None:
    shared = "\n".join(["def load(value):", *[f"    value += {index}" for index in range(24)], "    return value", ""])
    changed = shared.replace("value += 20", "value += 200")
    root = make_package(
        tmp_path / "basename",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "main.py"]\n',
            "main.py": "import tg_bot.redis_storage\n",
            "tg_bot/__init__.py": "",
            "tg_bot/redis_storage.py": shared,
            "max_bot/__init__.py": "",
            "max_bot/services/__init__.py": "",
            "max_bot/services/redis_storage.py": changed,
        },
    )
    arch = _arch(run_collect, root)
    pair = next(item for item in arch["python"]["duplicates"]["same_basename_pairs"] if item["ratio"] is not None)
    assert pair["ratio"] >= 0.9
    orphan = next(item for item in arch["python"]["orphans"] if item["path"] == "max_bot/services/redis_storage.py")
    assert orphan["class"] == "orphan"


def test_dup_function_hash_x4(tmp_path: Path, run_collect) -> None:
    function = (
        "def _normalize_now(value):\n"
        "    value = value.strip()\n"
        "    value = value.lower()\n"
        "    value = value.replace('-', '_')\n"
        "    parts = value.split('_')\n"
        "    parts = [part for part in parts if part]\n"
        "    return '_'.join(parts)\n"
    )
    files = {"Dockerfile": 'FROM python:3\nCMD ["python", "a.py"]\n'}
    files.update({f"{name}.py": function for name in "abcd"})
    arch = _arch(run_collect, make_package(tmp_path / "function-dups", files))
    assert any(len(item["copies"]) == 4 for item in arch["python"]["duplicates"]["function_hash_groups"])


def test_orphan_django_autodiscovery_not_orphan(tmp_path: Path, run_collect) -> None:
    root = django_app(tmp_path / "django", "shop", 3)
    arch = _arch(run_collect, root)
    paths = {item["path"] for item in arch["python"]["orphans"]}
    assert "shop/admin.py" not in paths
    assert "shop/templatetags/x.py" not in paths


def test_main_guard_script_not_orphan(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "main-guard",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "main.py"]\n',
            "main.py": "VALUE = 1\n",
            "scripts/quality_run.py": (
                "def main():\n"
                "    return 0\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            ),
        },
    )
    arch = _arch(run_collect, root)
    paths = {item["path"] for item in arch["python"]["orphans"]}
    assert "scripts/quality_run.py" not in paths


def test_orphan_used_on_local_branch(tmp_path: Path, run_collect) -> None:
    remote = make_bare(tmp_path / "remote.git")
    root = make_repo(
        tmp_path / "branches",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "main.py"]\n',
            "main.py": "VALUE = 1\n",
            "unused.py": "\n".join(f"VALUE_{index} = {index}" for index in range(60)) + "\n",
        },
        remote=remote,
    )
    subprocess.run(["git", "-C", str(root), "checkout", "-b", "feature"], check=True, capture_output=True)
    (root / "main.py").write_text("import unused\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "use module"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "checkout", "main"], check=True, capture_output=True)
    arch = _arch(run_collect, root)
    assert "unused.py" not in {item["path"] for item in arch["python"]["orphans"]}
    assert arch["rule_inputs"]["A15"]["branches_checked"] == 1
