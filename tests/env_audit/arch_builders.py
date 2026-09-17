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


def write_systemctl_stub(bin_dir: Path, units: dict[str, str]) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    data = bin_dir / "systemctl-units.json"
    data.write_text(json.dumps(units), encoding="utf-8")
    executable = bin_dir / "systemctl"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "units = json.loads(Path(__file__).with_name('systemctl-units.json').read_text())\n"
        "if 'list-timers' in sys.argv:\n"
        "    for name in sorted(key for key in units if key.endswith('.timer')):\n"
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
