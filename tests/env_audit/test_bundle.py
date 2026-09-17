from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .conftest import SKILL_DIR


def _without_times(doc):
    result = deepcopy(doc)
    result["collector"].pop("started_at")
    result["collector"].pop("duration_s")
    result["collector"].pop("section_durations_s")
    return result


def test_bundle_runs_from_stdin(run_collect, fake_home, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    direct = run_collect("--root", root)
    bundle = subprocess.run(
        [sys.executable, str(SKILL_DIR / "collect.py"), "--bundle"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env.pop("CODEX_HOME", None)
    bundled = subprocess.run(
        [sys.executable, "-", "--root", str(root)],
        input=bundle,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert bundled.returncode == 0
    assert _without_times(json.loads(bundled.stdout)) == _without_times(direct.data)


def test_bundle_reads_data(tmp_path):
    skill_copy = tmp_path / "env-audit"
    shutil.copytree(SKILL_DIR, skill_copy)
    probe = skill_copy / "envaudit" / "data" / "probe.txt"
    probe.write_text("bundled resource", encoding="utf-8")
    bundle = subprocess.run(
        [sys.executable, str(skill_copy / "collect.py"), "--bundle"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    original_tail = "from envaudit.core.cli import main\nsys.exit(main(sys.argv[1:]))\n"
    replacement = (
        "from envaudit.core.resources import read_data\n"
        "print(read_data('probe.txt'))\n"
    )
    assert original_tail in bundle
    probe_bundle = bundle.replace(original_tail, replacement)
    result = subprocess.run(
        [sys.executable, "-"],
        input=probe_bundle,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "bundled resource\n"
