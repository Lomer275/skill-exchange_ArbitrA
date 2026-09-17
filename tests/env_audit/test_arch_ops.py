from pathlib import Path
import subprocess

from .arch_builders import (
    ir2_like,
    isolated_runtime,
    make_bare,
    make_repo,
    write_crontab_stub,
    write_systemctl_stub,
)
from .schema_check import validate


def _arch(result, root: Path) -> dict:
    assert result.rc == 0, result.stdout
    return result.data["sections"]["architecture"][str(root.resolve())]


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)


def _cron(root: Path, entry: str, extra: str = "") -> str:
    suffix = f" {extra}" if extra else ""
    return f"*/5 * * * * cd {root} && python3 {entry}{suffix}"


def test_a1_outside_git_lines(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    remote = make_bare(tmp_path / "origin.git")
    root = make_repo(
        tmp_path / "repo",
        {
            ".gitignore": "bx/local_cfg.py\n",
            "bx/__init__.py": "",
            "bx/poll.py": "from bx import new_mod, local_cfg\nVALUE = 1\n",
        },
        remote=remote,
    )
    (root / "bx" / "new_mod.py").write_text(
        "\n".join(f"VALUE_{index} = {index}" for index in range(120)) + "\n",
        encoding="utf-8",
    )
    (root / "bx" / "local_cfg.py").write_text(
        "\n".join(f"LOCAL_{index} = {index}" for index in range(10)) + "\n",
        encoding="utf-8",
    )
    with (root / "bx" / "poll.py").open("a", encoding="utf-8") as stream:
        stream.write("\n".join(f"ADDED_{index} = {index}" for index in range(6)) + "\n")
    line = _cron(root, "bx/poll.py")
    write_crontab_stub(isolated_runtime, [line])

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)
    closure = arch["ops"]["live_closure"][0]

    assert closure["outside_git_lines"] == 120
    assert closure["ignored_lines"] == 10
    assert closure["uncommitted_add"] == 6
    assert line not in result.stdout


def test_a1_ahead_verified(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    remote = make_bare(tmp_path / "origin.git")
    root = make_repo(
        tmp_path / "repo",
        {
            "bx/__init__.py": "",
            "bx/poll.py": "from bx import helper\n",
            "bx/helper.py": "VALUE = 1\n",
        },
        remote=remote,
    )
    (root / "bx" / "helper.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit(root, "local closure change")
    write_crontab_stub(isolated_runtime, [_cron(root, "bx/poll.py")])

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    closure = arch["ops"]["live_closure"][0]

    assert closure["ahead_closure"] == 1
    assert closure["ahead_verified"] is True


def test_a1_ahead_outside_closure_ignored(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    remote = make_bare(tmp_path / "origin.git")
    root = make_repo(
        tmp_path / "repo",
        {"bx/poll.py": "VALUE = 1\n", "docs/readme.md": "one\n"},
        remote=remote,
    )
    (root / "docs" / "readme.md").write_text("two\n", encoding="utf-8")
    _commit(root, "docs only")
    write_crontab_stub(isolated_runtime, [_cron(root, "bx/poll.py")])

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["ops"]["live_closure"][0]["ahead_closure"] == 0


def test_a1_unresolved_entry(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = make_repo(tmp_path / "repo", {"x": "app.py\n", "app.py": "VALUE = 1\n"})
    write_crontab_stub(
        isolated_runtime,
        [f'*/5 * * * * cd {root} && bash -c "$(cat x)"'],
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["rule_inputs"]["A1"]["measured"] is False


def test_a2_local_branch_plus20(tmp_path: Path, run_collect) -> None:
    remote = make_bare(tmp_path / "origin.git")
    root = make_repo(
        tmp_path / "repo",
        {"app.py": "\n".join(f"BASE_{index} = {index}" for index in range(10)) + "\n"},
        remote=remote,
    )
    _git(root, "switch", "-c", "large-local")
    (root / "app.py").write_text(
        "\n".join(f"VALUE_{index} = {index}" for index in range(20)) + "\n",
        encoding="utf-8",
    )
    _commit(root, "grow code")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert any(
        item.get("name") == "large-local"
        for item in arch["rule_inputs"]["A2"]["branches"]
    )


def test_a2_deploy_dir_drift(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = make_repo(
        tmp_path / "repo",
        {
            "app.py": "ONE = 1\nTWO = 2\nTHREE = 3\n",
            "deploy/sample.service": (
                "[Service]\nWorkingDirectory=/srv/sample\n"
                "ExecStart=/usr/bin/python3 -m app\n"
            ),
        },
    )
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "app.py").write_text(
        "ONE = 10\nTWO = 20\nTHREE = 30\n", encoding="utf-8"
    )
    write_systemctl_stub(
        isolated_runtime,
        {
            "sample.timer": "[Timer]\nOnCalendar=hourly\n",
            "sample.service": (
                f"[Service]\nWorkingDirectory={deploy}\n"
                "/usr/bin/true\nExecStart=/usr/bin/python3 -m app\n"
            ),
        },
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    facts = arch["runtime"]["deploy_dirs"][0]

    assert facts["files_drift"] == 1
    assert facts["lines_drift"] == 3
    assert facts["drift_matches_commit"] is False


def test_a2_unmatched_deploy_dirs_hidden(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = make_repo(tmp_path / "repo", {"app.py": "VALUE = 1\n"})
    deploy = tmp_path / "unrelated"
    deploy.mkdir()
    write_systemctl_stub(
        isolated_runtime,
        {
            "unrelated.timer": "[Timer]\nOnCalendar=hourly\n",
            "unrelated.service": (
                f"[Service]\nWorkingDirectory={deploy}\n"
                "ExecStart=/usr/bin/python3 -m unrelated\n"
            ),
        },
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    inputs = arch["rule_inputs"]["A2"]

    assert arch["runtime"]["deploy_dirs"] == []
    assert inputs["deploy_dirs"] == []
    assert inputs["deploy_dirs_unmatched_count"] == 1


def test_a3_shared_lock_and_refusals(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = tmp_path / "locks"
    (root / "logs").mkdir(parents=True)
    (root / "poll.py").write_text(
        "from pathlib import Path\n"
        "import fcntl\n"
        "DEFAULT_LOCK_PATH = Path(__file__).with_name('poll.lock')\n"
        "def _single_instance_lock(lock_path=DEFAULT_LOCK_PATH):\n"
        "    handle = open(lock_path, 'w')\n"
        "    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n",
        encoding="utf-8",
    )
    (root / "logs" / "poll-tasks.log").write_text(
        "processed=1\n" * 5 + "already running\n" * 5,
        encoding="utf-8",
    )
    first = _cron(root, "poll.py", "--mode tasks >> logs/poll-tasks.log")
    second = _cron(root, "poll.py", "--mode chats >> logs/poll-tasks.log")
    write_crontab_stub(isolated_runtime, [first, second])

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)

    assert arch["ops"]["shared_locks"][0]["distinct_args"] == 2
    assert arch["ops"]["log_lock_refusals"][0]["share"] == 0.5
    assert "--mode tasks" not in result.stdout
    assert "--mode chats" not in result.stdout


def test_a3_lock_via_wrapper_param(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = tmp_path / "wrapper-lock"
    root.mkdir()
    (root / "poll.py").write_text(
        "from contextlib import contextmanager\n"
        "from pathlib import Path\n"
        "from typing import Iterator\n"
        "import fcntl\n"
        "DEFAULT_LOCK_PATH = Path(__file__).with_name('poll.lock')\n"
        "@contextmanager\n"
        "def _single_instance_lock(path: Path) -> Iterator[None]:\n"
        "    with path.open('w') as lock_file:\n"
        "        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "        yield\n"
        "with _single_instance_lock(DEFAULT_LOCK_PATH):\n"
        "    pass\n",
        encoding="utf-8",
    )
    first = _cron(root, "poll.py", "--mode tasks")
    second = _cron(root, "poll.py", "--mode chats")
    write_crontab_stub(isolated_runtime, [first, second])

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    locks = arch["ops"]["shared_locks"]

    assert len(locks) == 1
    assert locks[0]["defined_at"] == "poll.py:5"
    assert locks[0]["distinct_args"] == 2


def test_a3_share_from_success_and_refusal_lines(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = tmp_path / "log-share"
    (root / "logs").mkdir(parents=True)
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "logs" / "poll-tasks.log").write_text(
        "dialogs_seen=1 tasks_seen=2\n" * 220
        + "BX inbox poller is already running; no-op\n" * 180,
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    metrics = arch["ops"]["log_lock_refusals"][0]

    assert metrics["runs"] == 400
    assert metrics["refusals"] == 180
    assert metrics["successes"] == 220
    assert metrics["share"] == 0.45


def test_i1_i2_no_vcs_live(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = tmp_path / "ir2"
    ir2_like(root, py_files=3)
    (root / ".git" / "info").mkdir(parents=True)
    (root / ".git" / "info" / "exclude").write_text("*.tmp\n", encoding="utf-8")
    (root / "n8n").mkdir()
    (root / "n8n" / "run.py").write_text(
        "disk.file.delete(item)\ncrm.lead.delete(item)\n", encoding="utf-8"
    )
    (root / "n8n" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "n8n" / "other.php").write_text("<?php echo 1;\n", encoding="utf-8")
    for prefix in (root, root / "backup"):
        target = prefix / "local" / "modules" / "x"
        target.mkdir(parents=True)
        (target / "run.php").write_text("<?php echo 1;\n", encoding="utf-8")
    write_crontab_stub(isolated_runtime, [_cron(root, "n8n/run.py")])

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    i1 = arch["rule_inputs"]["I1"]
    i2 = arch["rule_inputs"]["I2"]

    assert i1["vcs_present"] is False
    assert i1["deployed_code_dirs"]
    assert i2["destructive_calls"] == 2
    assert i2["recent_files"] >= 3


def test_i3_copies_by_hash(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "copies"
    values = ["a", "bb", "ccc", "dddd", "a", "bb"]
    for index, value in enumerate(values):
        path = root / f"mirror_{index}" / "local" / "components" / "crm_cash_receipt"
        path.mkdir(parents=True)
        (path / "controller.php").write_text(
            f"<?php echo '{value}';\n", encoding="utf-8"
        )
    hint = root / "99_дубли"
    hint.mkdir()
    (hint / "unique.php").write_text("<?php echo 'unique';\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    copies = arch["scripts_collection"]["copies_by_relpath"]
    item = next(value for value in copies if value["relpath"].endswith("controller.php"))

    assert item["copies"] == 6
    assert item["distinct_hashes"] == 4
    assert any("99_дубли" in path for path in arch["rule_inputs"]["I3"]["hint_dirs"])
    assert all("99_дубли" not in value["relpath"] for value in copies)


def test_i_rules_not_applicable_with_vcs(tmp_path: Path, run_collect) -> None:
    root = make_repo(tmp_path / "repo", {"app.py": "VALUE = 1\n"})

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["rule_inputs"]["I1"]["applicable"] is False
    assert arch["rule_inputs"]["I2"]["applicable"] is False
    assert arch["rule_inputs"]["I3"]["applicable"] is False


def test_ops_uses_isolated_runtime_stubs(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = make_repo(tmp_path / "repo", {"app.py": "VALUE = 1\n"})
    line = "*/5 * * * * cd /home/x/p && python3 run.py"
    write_crontab_stub(isolated_runtime, [line])
    write_systemctl_stub(
        isolated_runtime,
        {
            "outside.timer": "[Timer]\nOnCalendar=hourly\n",
            "outside.service": (
                "[Service]\n"
                "ExecStart=/usr/bin/python3 /home/x/p/run.py\n"
            ),
        },
    )

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)

    assert arch["rule_inputs"]["A1"]["live_units"] == 0
    assert line not in result.stdout


def test_schema_valid(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "schema"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = run_collect("--only", "architecture", "--root", root)

    validate(result.data)
