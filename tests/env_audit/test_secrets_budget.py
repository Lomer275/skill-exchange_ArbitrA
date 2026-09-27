from envaudit.core.context import Context, Flags
from envaudit.sections import secrets

from .schema_check import validate


def _passing_controls():
    return {
        "tree": "pass",
        "git_head": "pass",
        "git_history": "pass",
        "configs": "pass",
        "home": "pass",
    }


def _patch_fast_blocks(monkeypatch):
    monkeypatch.setattr(
        secrets,
        "_run_controls",
        lambda _ctx, git_available=True: _passing_controls(),
    )
    monkeypatch.setattr(
        secrets,
        "_scan_context_files",
        lambda _ctx, _codex_home: ([], {"files": 0, "matches": 0}),
    )
    monkeypatch.setattr(
        secrets,
        "_scan_agent_configs",
        lambda _ctx, _codex_home: ([], {"files": 0, "matches": 0}),
    )
    monkeypatch.setattr(secrets, "_storage", lambda _ctx: {"secrets_dirs": []})
    monkeypatch.setattr(secrets, "_ssh", lambda _ctx: ([], 0))
    monkeypatch.setattr(
        secrets,
        "collect_external_access",
        lambda _home: {
            "gh_hosts": [],
            "docker_registries": [],
            "aws_profiles": 0,
            "kube_contexts": 0,
        },
    )


def test_budget_split_gives_each_part_its_share(fake_home, tmp_path, monkeypatch):
    clock = [1000.0]
    root = tmp_path / "root"
    root.mkdir()
    _patch_fast_blocks(monkeypatch)
    monkeypatch.setattr(secrets.time, "time", lambda: clock[0])
    monkeypatch.setattr(secrets, "which", lambda _name: None)
    root_deadlines = []
    home_deadlines = []
    history_budgets = []

    def scan_root(_root, ctx, _vcs):
        root_deadlines.append(ctx.section_deadline)
        clock[0] = 1040.0
        return {}

    def scan_home(_ctx, _codex_home, _timings, home_deadline):
        home_deadlines.append(home_deadline)
        clock[0] = 1075.0
        return ({"files_scanned": 1}, {}, {})

    def scan_histories(ctx, _codex_home):
        history_budgets.append(ctx.remaining_seconds())
        return {}

    monkeypatch.setattr(secrets, "_scan_root", scan_root)
    monkeypatch.setattr(secrets, "_scan_home_blocks", scan_home)
    monkeypatch.setattr(secrets, "_scan_agent_histories", scan_histories)
    ctx = Context(Flags(), fake_home, [root], 1000.0, 1200.0)
    ctx.section_deadline = 1100.0

    section = secrets.collect(ctx)

    assert root_deadlines == [1040.0]
    assert home_deadlines == [1075.0]
    assert history_budgets == [25.0]
    assert section["budget_split"] == {
        "roots_seconds": 40.0,
        "home_seconds": 35.0,
        "histories_seconds": 25.0,
    }


def test_budget_split_prioritizes_minimums_when_time_is_short(
    fake_home, tmp_path, monkeypatch
):
    clock = [1000.0]
    root = tmp_path / "root"
    root.mkdir()
    _patch_fast_blocks(monkeypatch)
    monkeypatch.setattr(secrets.time, "time", lambda: clock[0])
    monkeypatch.setattr(secrets, "which", lambda _name: None)
    root_deadlines = []
    home_deadlines = []
    history_budgets = []

    def scan_root(_root, ctx, _vcs):
        root_deadlines.append(ctx.section_deadline)
        clock[0] = 1010.0
        return {}

    def scan_home(_ctx, _codex_home, _timings, home_deadline):
        home_deadlines.append(home_deadline)
        clock[0] = 1040.0
        return ({"files_scanned": 1}, {}, {})

    def scan_histories(ctx, _codex_home):
        history_budgets.append(ctx.remaining_seconds())
        return {}

    monkeypatch.setattr(secrets, "_scan_root", scan_root)
    monkeypatch.setattr(secrets, "_scan_home_blocks", scan_home)
    monkeypatch.setattr(secrets, "_scan_agent_histories", scan_histories)
    ctx = Context(Flags(), fake_home, [root], 1000.0, 1200.0)
    ctx.section_deadline = 1045.0

    section = secrets.collect(ctx)

    assert root_deadlines == [1010.0]
    assert home_deadlines == [1040.0]
    assert history_budgets == [5.0]
    assert section["budget_split"] == {
        "roots_seconds": 10.0,
        "home_seconds": 30.0,
        "histories_seconds": 5.0,
    }


def test_unused_budget_moves_to_home_then_histories(
    fake_home, tmp_path, monkeypatch
):
    clock = [1000.0]
    root = tmp_path / "root"
    root.mkdir()
    _patch_fast_blocks(monkeypatch)
    monkeypatch.setattr(secrets.time, "time", lambda: clock[0])
    monkeypatch.setattr(secrets, "which", lambda _name: None)
    home_deadlines = []
    history_budgets = []

    def scan_root(_root, _ctx, _vcs):
        clock[0] = 1012.0
        return {}

    def scan_home(_ctx, _codex_home, _timings, home_deadline):
        home_deadlines.append(home_deadline)
        clock[0] = 1020.0
        return ({"files_scanned": 1}, {}, {})

    def scan_histories(ctx, _codex_home):
        history_budgets.append(ctx.remaining_seconds())
        return {}

    monkeypatch.setattr(secrets, "_scan_root", scan_root)
    monkeypatch.setattr(secrets, "_scan_home_blocks", scan_home)
    monkeypatch.setattr(secrets, "_scan_agent_histories", scan_histories)
    ctx = Context(Flags(), fake_home, [root], 1000.0, 1200.0)
    ctx.section_deadline = 1100.0

    section = secrets.collect(ctx)

    assert home_deadlines == [1075.0]
    assert history_budgets == [80.0]
    assert section["budget_split"] == {
        "roots_seconds": 40.0,
        "home_seconds": 63.0,
        "histories_seconds": 80.0,
    }


def test_reserved_home_budget_scans_file(fake_home, tmp_path, monkeypatch):
    root = tmp_path / "large-root"
    root.mkdir()
    for index in range(80):
        (root / f"file-{index:03}.txt").write_text("ordinary text\n", encoding="utf-8")
    (fake_home / "probe.txt").write_text("ordinary text\n", encoding="utf-8")
    _patch_fast_blocks(monkeypatch)
    monkeypatch.setattr(secrets, "which", lambda _name: None)
    monkeypatch.setattr(secrets, "HOME_BUDGET_MIN_SECONDS", 0.03)
    monkeypatch.setattr(secrets, "ROOTS_BUDGET_MIN_SECONDS", 0.02)
    monkeypatch.setattr(secrets, "HISTORIES_BUDGET_MIN_SECONDS", 0.01)
    monkeypatch.setattr(secrets, "_scan_agent_histories", lambda _ctx, _codex_home: {})
    original_read = secrets._read_for_scan
    clock = [1000.0]
    monkeypatch.setattr(secrets.time, "time", lambda: clock[0])

    def slow_read(*args, **kwargs):
        clock[0] += 0.002
        return original_read(*args, **kwargs)

    monkeypatch.setattr(secrets, "_read_for_scan", slow_read)
    ctx = Context(Flags(), fake_home, [root], 1000.0, 1001.0)
    ctx.section_deadline = 1000.12

    section = secrets.collect(ctx)

    assert section["home"]["files_scanned"] > 0
    expected = {"section": "secrets", "reason": "budget", "details": "roots"}
    assert ctx.skipped.count(expected) == 1


def test_budget_split_passes_schema(run_collect, tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    result = run_collect("--root", root, "--only", "secrets")

    assert result.rc == 0
    split = result.data["sections"]["secrets"]["budget_split"]
    assert set(split) == {"roots_seconds", "home_seconds", "histories_seconds"}
    assert all(value >= 0 and value == round(value, 1) for value in split.values())
    validate(result.data)
