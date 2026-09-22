import json
import os
from pathlib import Path
import subprocess
import sys

from .canaries import canary
from .conftest import SKILL_DIR


def _run_without_pwd(fake_home: Path, *args: object) -> subprocess.CompletedProcess[str]:
    collect = SKILL_DIR / "collect.py"
    argv = [str(collect), *(str(arg) for arg in args)]
    wrapper = (
        "import runpy, sys\n"
        "sys.modules['pwd'] = None\n"
        f"sys.argv = {argv!r}\n"
        f"runpy.run_path({str(collect)!r}, run_name='__main__')\n"
    )
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env.pop("CODEX_HOME", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", wrapper],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_scan_file_without_pwd(fake_home, tmp_path):
    clean = tmp_path / "clean.txt"
    clean.write_text("без секретов\n", encoding="utf-8")
    webhook = tmp_path / "webhook.txt"
    webhook.write_text(canary("bitrix_webhook", 465) + "\n", encoding="utf-8")

    clean_result = _run_without_pwd(fake_home, "--scan-file", clean)
    webhook_result = _run_without_pwd(fake_home, "--scan-file", webhook)

    assert clean_result.returncode == 0
    assert json.loads(clean_result.stdout)["matches"] == []
    assert webhook_result.returncode == 3
    assert json.loads(webhook_result.stdout)["matches"] == [
        {"class": "bitrix_webhook", "line": 1}
    ]
    assert clean_result.stderr == webhook_result.stderr == ""


def test_full_collection_without_pwd_exits_5(fake_home):
    result = _run_without_pwd(fake_home)

    assert result.returncode == 5
    assert result.stdout == ""
    assert result.stderr == (
        "Сборщик рассчитан на Linux/WSL. На Windows аудит идёт вручную по "
        "references/windows.md\n"
    )
    assert "Traceback" not in result.stderr


def test_help_without_pwd_lists_exit_code_5(fake_home):
    result = _run_without_pwd(fake_home, "--help")

    assert result.returncode == 0
    assert "2 — ошибка аргументов, корень не найден или результат нельзя записать" in result.stdout
    assert "5 — полный сбор недоступен на Windows или без модуля pwd" in result.stdout
    assert result.stderr == ""
