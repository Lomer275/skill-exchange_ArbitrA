from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest


def _git(path: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def _write(root: Path, files: dict[str, str | bytes]) -> None:
    for rel, value in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            target.write_bytes(value)
        else:
            target.write_text(value, encoding="utf-8")


def _commit(path: Path, message: str, date: str | None = None) -> None:
    _git(path, "add", "-A")
    env = os.environ.copy()
    if date:
        value = date if date.endswith("Z") else date + "Z"
        env["GIT_AUTHOR_DATE"] = value
        env["GIT_COMMITTER_DATE"] = value
    _git(path, "commit", "--allow-empty", "-m", message, env=env)


def make_repo(
    path: Path,
    files: dict[str, str | bytes],
    *,
    commits: list[dict] | None = None,
    remote: Path | None = None,
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(path, "config", "user.name", "Env Audit Test")
    _git(path, "config", "user.email", "env-audit@example.invalid")
    if files:
        _write(path, files)
        _commit(path, "initial")
    for index, commit in enumerate(commits or [], 1):
        _write(path, commit.get("files", {}))
        _commit(
            path,
            str(commit.get("message", f"commit-{index}")),
            commit.get("date"),
        )
    if not files and not commits:
        _commit(path, "initial")
    if remote is not None:
        _git(path, "remote", "add", "origin", str(remote))
        _git(path, "push", "-u", "origin", "main")
        subprocess.run(
            ["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
            check=True,
            capture_output=True,
            text=True,
        )
        _git(path, "remote", "set-head", "origin", "main")
    return path


def make_bare(path: Path) -> Path:
    subprocess.run(
        ["git", "init", "--bare", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def write_crontab_stub(bin_dir: Path, lines: list[str]) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    data = bin_dir / "crontab-lines.json"
    data.write_text(json.dumps(lines), encoding="utf-8")
    executable = bin_dir / "crontab"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "from pathlib import Path\n"
        "for item in json.loads((Path(__file__).with_name('crontab-lines.json')).read_text()):\n"
        "    print(item)\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)


def write_systemctl_stub(
    bin_dir: Path, units: dict[str, str], *, unordered: bool = False
) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    data = bin_dir / "systemctl-units.json"
    data.write_text(json.dumps(units), encoding="utf-8")
    executable = bin_dir / "systemctl"
    timer_names = "set(units)" if unordered else "sorted(units)"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "units = json.loads(Path(__file__).with_name('systemctl-units.json').read_text())\n"
        "if 'list-timers' in sys.argv:\n"
        f"    for name in {timer_names}:\n"
        "        if not name.endswith('.timer'):\n"
        "            continue\n"
        "        print('- - - - ' + name)\n"
        "elif 'cat' in sys.argv:\n"
        "    name = sys.argv[-1]\n"
        "    if name not in units:\n"
        "        raise SystemExit(1)\n"
        "    print(units[name])\n"
        "else:\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)


def _callseq_source(group_call: str) -> str:
    body = [
        "def candidate(value):",
        "    value = shared_call(value)",
        f"    value = {group_call}(value)",
    ]
    body.extend(f"    value += {index}" for index in range(40))
    body.append("    return value")
    return "\n".join(body) + "\n"


def _duplicate_source() -> str:
    return (
        "def normalize(value):\n"
        "    value = value.strip()\n"
        "    value = value.lower()\n"
        "    value = value.replace('-', '_')\n"
        "    parts = value.split('_')\n"
        "    parts = [part for part in parts if part]\n"
        "    return '_'.join(parts)\n"
    )


def architecture_determinism_tree(root: Path, runtime_bin: Path) -> Path:
    files = {
        "pyproject.toml": "[project]\nname = 'determinism-fixture'\n",
        "requirements.txt": "requests==2.0\n",
        "docker-compose.yml": (
            "services:\n"
            "  tg:\n    build: .\n    command: python tg_bot/main.py\n"
            "  max:\n    build: .\n    command: python max_bot/main.py\n"
        ),
        "Dockerfile": 'FROM python:3.10\nCMD ["python", "tg_bot/main.py"]\n',
        ".github/workflows/deploy.yml": (
            "jobs:\n  deploy:\n    steps:\n"
            "      - run: python -m alembic upgrade head\n"
            "      - run: pytest\n"
        ),
        ".audit/layers.json": json.dumps(
            {
                "presentation": ["tg_bot", "max_bot"],
                "adapters": ["shared"],
            },
            sort_keys=True,
        ),
        "CLAUDE.md": (
            "# Architecture\n"
            "Use Python 3.10 and `missing_worker.py`.\n"
            "| Layer | Path |\n|---|---|\n"
            "| Interface | `tg_bot` |\n| Core | `shared` |\n"
        ),
        "AGENTS.md": "Use Python 3.11.\nRead `docs/HANDOFF.md`.\n",
        "README.md": "Run `tg_bot/main.py` and `max_bot/main.py`.\n",
        "docs/HANDOFF.md": "Status: production. Run pytest before deploy.\n",
        "docs/CHANGELOG.md": "# Changelog\n",
        "docs/SUP-architecture.md": (
            "| Layer | Path |\n|---|---|\n"
            "| Interface | `tg_bot` |\n| Core | `shared` |\n"
        ),
        "shared/__init__.py": "",
        "shared/client.py": (
            "import requests\n"
            "def fetch(value):\n"
            "    return requests.get(value)\n"
        ),
        "tg_bot/__init__.py": "",
        "tg_bot/main.py": (
            "from aiogram import Dispatcher\n"
            "from tg_bot import auth, payments\n"
            "dp = Dispatcher()\n"
            "async def run():\n    await dp.start_polling()\n"
        ),
        "tg_bot/auth.py": (
            "from max_bot import bridge\n"
            "from shared import client\n"
            "def handle(value):\n    return client.fetch(value)\n"
        ),
        "tg_bot/payments.py": (
            "from shared import client\n"
            "def handle(value):\n    return client.fetch(value)\n"
        ),
        "max_bot/__init__.py": "",
        "max_bot/main.py": (
            "from maxapi import Bot\n"
            "from max_bot import auth, payments\n"
            "bot = Bot()\n"
            "async def run():\n    await bot.start_polling()\n"
        ),
        "max_bot/auth.py": (
            "from shared import client\n"
            "def handle(value):\n    return client.fetch(value)\n"
        ),
        "max_bot/payments.py": (
            "from shared import client\n"
            "def handle(value):\n    return client.fetch(value)\n"
        ),
        "max_bot/bridge.py": "import maxapi\nVALUE = 1\n",
        "orphan_a.py": _duplicate_source(),
        "orphan_b.py": _duplicate_source(),
        "ops/poll.py": (
            "from pathlib import Path\n"
            "import fcntl\n"
            "LOCK = Path(__file__).with_name('poll.lock')\n"
            "def run():\n"
            "    handle = open(LOCK, 'w')\n"
            "    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        ),
        "logs/poll.log": "already running\n" * 5 + "processed=1\n" * 5,
        "alembic.ini": "[alembic]\nscript_location = migrations\n",
        "migrations/versions/0001_base.py": (
            "revision = 'r1'\ndown_revision = None\n"
        ),
        "migrations/versions/0002_next.py": (
            "revision = 'r2'\ndown_revision = 'r1'\n"
        ),
        "db/startup.py": (
            "async def lifespan(app):\n"
            "    initialize()\n"
            "    yield\n\n"
            "def initialize():\n"
            "    try:\n"
            "        Base.metadata.create_all(bind=engine)\n"
            "    except Exception:\n"
            "        pass\n"
        ),
        "db/models.py": (
            "class Account(Base):\n"
            "    __tablename__ = 'account'\n\n"
            "class Event(models.Model):\n"
            "    pass\n"
        ),
        "db/schema.sql": (
            "CREATE TABLE account (id INTEGER);\n"
            "CREATE TABLE audit_event (id INTEGER);\n"
        ),
        "web/widget.php": (
            "<?php\nfunction loadDeal() { CCrmDeal::GetList(); curl_init(); }\n"
        ),
        "web/app.js": "export async function load() { return import('./chunk.js'); }\n",
        "web/chunk.js": "export const value = 1;\n",
        "desktop/App.csproj": (
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
            "</Project>\n"
        ),
        "desktop/Main.cs": (
            "public class MainService {\n"
            "    public MainService(IClock clock, IClient client) {}\n"
            "}\n"
        ),
        "root-backup.bak": "backup\n",
        "stray-root.txt": "not allowlisted\n",
        "broken/file (copy).py": "VALUE = 1\n",
        "tests/test_shared.py": (
            "from shared import client\n"
            "def test_client():\n    assert client\n"
        ),
    }
    files.update(
        {
            f"callseq/module_{index:03d}.py": _callseq_source(
                "group_zero" if index < 101 else "group_one"
            )
            for index in range(202)
        }
    )
    make_repo(
        root,
        {},
        commits=[
            {
                "files": files,
                "message": "old fixture",
                "date": "2025-01-01T00:00:00",
            },
            {
                "files": {"docs/RECENT.md": "recent change\n"},
                "message": "recent fixture",
                "date": "2026-09-16T00:00:00",
            },
        ],
    )

    root_text = str(root)
    write_crontab_stub(
        runtime_bin,
        [
            f"*/5 * * * * cd {root_text} && python3 ops/poll.py --mode tasks >> logs/poll.log",
            f"*/7 * * * * cd {root_text} && python3 ops/poll.py --mode chats >> logs/poll.log",
        ],
    )
    units = {}
    for name, entry in (
        ("dev1-test-db-gc", "tg_bot/main.py"),
        ("obs-fix-loop", "max_bot/main.py"),
        ("sentinel", "ops/poll.py"),
    ):
        units[f"{name}.timer"] = "[Timer]\nOnCalendar=hourly\n"
        units[f"{name}.service"] = (
            "[Service]\n"
            f"WorkingDirectory={root_text}\n"
            f"ExecStart=/usr/bin/python3 {root_text}/{entry}\n"
        )
    write_systemctl_stub(runtime_bin, units, unordered=True)
    return root


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "runtime-bin"
    system_units = tmp_path / "system-units"
    user_units = tmp_path / "user-units"
    system_units.mkdir()
    user_units.mkdir()
    write_crontab_stub(bin_dir, [])
    write_systemctl_stub(bin_dir, {})

    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("ENVAUDIT_ETC_SYSTEMD_DIR", str(system_units))
    monkeypatch.setenv("ENVAUDIT_USER_UNIT_DIRS", str(user_units))

    from envaudit.arch.checks import runtime

    monkeypatch.setattr(runtime, "CRONTAB_CMD", ("crontab", "-l"))
    monkeypatch.setattr(runtime, "SYSTEMCTL", "systemctl")
    monkeypatch.setattr(runtime, "ETC_SYSTEMD_DIR", system_units)
    monkeypatch.setattr(runtime, "USER_UNIT_DIRS", (str(user_units),))
    return bin_dir


def ir2_like(root: Path, *, py_files: int = 40) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(py_files):
        month = index % 12 + 1
        day = index % 28 + 1
        path = root / f"task_2026{month:02d}{day:02d}_{index:03d}.py"
        path.write_text(
            "def main():\n"
            f"    return {index}\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n",
            encoding="utf-8",
        )
