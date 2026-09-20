import time
from types import SimpleNamespace

from envaudit.core.budget import run_sections
from envaudit.core.context import Context, Flags
from envaudit.core.output import build_document
from envaudit.sections import architecture


def _context(tmp_path, *, budget_seconds=1, roots=None):
    started = time.time()
    return Context(
        flags=Flags(budget_seconds=budget_seconds),
        home=tmp_path,
        roots=list(roots or [tmp_path]),
        started_at=started,
        deadline=started + budget_seconds,
    )


def _module(name, order, collect):
    return SimpleNamespace(NAME=name, ORDER=order, collect=collect)


def test_section_durations_reported(tmp_path):
    modules = [
        _module("first", 10, lambda ctx: (time.sleep(0.001), {})[1]),
        _module("second", 20, lambda ctx: (time.sleep(0.001), {})[1]),
    ]
    ctx = _context(tmp_path)

    sections, durations = run_sections(ctx, modules)
    document = build_document(ctx, {}, sections, durations, [], {})

    assert set(document["collector"]["section_durations"]) == {
        "first",
        "second",
    }
    assert all(
        value > 0
        for value in document["collector"]["section_durations"].values()
    )
    assert "index_build_seconds" in document["collector"]
    assert document["collector"]["budget_seconds"] == 1
    assert document["collector"]["budget_spent_seconds"] > 0


def test_late_section_not_starved(tmp_path):
    def slow(_ctx):
        time.sleep(1)
        return {"finished": True}

    ctx = _context(tmp_path, budget_seconds=0.2)
    modules = [
        _module("secrets", 10, slow),
        _module("late", 20, lambda _ctx: {"collected": True}),
    ]

    sections, _ = run_sections(ctx, modules)

    assert sections["secrets"] is None
    assert sections["late"] == {"collected": True}
    assert {
        "section": "secrets",
        "reason": "budget",
        "details": None,
    } in ctx.skipped
    assert "secrets" in sections and "late" in sections


def test_arch_root_budget_within_section_cap(tmp_path, monkeypatch):
    roots = [tmp_path / name for name in ("one", "two", "three")]
    for root in roots:
        root.mkdir()
    ctx = _context(tmp_path, budget_seconds=0.3, roots=roots)
    observed_timeouts = []
    run_with_timeout = architecture._run_with_timeout

    def observe_timeout(function, actx, timeout):
        observed_timeouts.append(timeout)
        return run_with_timeout(function, actx, timeout)

    monkeypatch.setattr(architecture, "_run_with_timeout", observe_timeout)
    monkeypatch.setattr(architecture, "discover_checks", lambda: [])
    monkeypatch.setattr(
        architecture,
        "is_git_repo",
        lambda _root: (time.sleep(1), False)[1],
    )

    sections, _ = run_sections(ctx, [architecture])

    assert sections["architecture"]
    assert set(sections["architecture"]) == {
        str(root.resolve()) for root in roots
    }
    assert observed_timeouts
    assert observed_timeouts[0] <= 0.1


def test_cheap_roots_donate_time(tmp_path, monkeypatch):
    cheap_roots = [tmp_path / f"cheap-{index}" for index in range(4)]
    expensive = tmp_path / "expensive"
    for root in [*cheap_roots, expensive]:
        root.mkdir()
    for index in range(20):
        (expensive / f"file-{index}.py").write_text("pass\n", encoding="utf-8")

    visited = []

    def first_check(actx):
        visited.append(actx.root)
        actx.out["first_check_finished"] = True

    checks = [SimpleNamespace(KEY="first", ORDER=1, run=first_check)]
    monkeypatch.setattr(architecture, "discover_checks", lambda: checks)
    monkeypatch.setattr(architecture, "is_git_repo", lambda _root: False)
    roots = [expensive, *reversed(cheap_roots)]
    ctx = _context(tmp_path, budget_seconds=16, roots=roots)

    sections, _ = run_sections(ctx, [architecture])

    result = sections["architecture"]
    expensive_result = result[str(expensive.resolve())]
    assert visited[-1] == expensive
    assert expensive_result["root_budget_seconds"] > 16 / len(roots)
    assert expensive_result["first_check_finished"] is True
    assert list(result) == [
        str(root.resolve()) for root in sorted(roots, key=lambda item: item.name)
    ]


def test_min_root_reserve_respected(tmp_path, monkeypatch):
    roots = [tmp_path / f"root-{index}" for index in range(4)]
    for root in roots:
        root.mkdir()
    monkeypatch.setattr(architecture, "discover_checks", lambda: [])
    monkeypatch.setattr(architecture, "is_git_repo", lambda _root: False)
    ctx = _context(tmp_path, budget_seconds=12.5, roots=roots)

    sections, _ = run_sections(ctx, [architecture])

    result = sections["architecture"]
    assert set(result) == {str(root.resolve()) for root in roots}
    assert all(
        document["root_budget_seconds"] >= 3
        for document in result.values()
    )
