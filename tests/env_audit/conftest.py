from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SKILL_DIR = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "team-skills"
    / "skills"
    / "env-audit"
)
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL_DIR))


@dataclass
class CollectResult:
    rc: int
    data: dict | None
    stdout: str


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / "projects").mkdir(parents=True)
    (home / ".claude").mkdir()
    return home


@pytest.fixture
def run_collect(fake_home: Path) -> Callable[..., CollectResult]:
    def invoke(*args: object, env_extra: dict[str, str] | None = None) -> CollectResult:
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("CODEX_HOME", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if env_extra:
            env.update(env_extra)
        completed = subprocess.run(
            [sys.executable, str(SKILL_DIR / "collect.py"), *(str(arg) for arg in args)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        stdout = completed.stdout
        data = json.loads(stdout) if stdout.strip() else None
        return CollectResult(completed.returncode, data, stdout)

    return invoke
