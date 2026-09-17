import json
from pathlib import Path
import time

from envaudit.arch import context as context_module
from envaudit.arch.context import ArchContext, TreeView
from envaudit.core.context import Context, Flags

from .arch_builders import isolated_runtime
from .fixtures.arch_perf_tree import build_arch_perf_tree


FIXTURES = Path(__file__).with_name("fixtures")


def test_architecture_matches_pre_optimization_fixture(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = build_arch_perf_tree(tmp_path / "project")
    expected = json.loads(
        (FIXTURES / "arch_perf_expected.json").read_text(encoding="utf-8")
    )

    started = time.monotonic()
    result = run_collect("--only", "architecture", "--root", root)
    elapsed = time.monotonic() - started

    assert result.rc == 0, result.stdout
    actual = result.data["sections"]["architecture"][str(root.resolve())]
    actual.pop("timings_s", None)
    assert actual == expected
    assert elapsed < 5


def test_arch_context_read_uses_size_limited_lru(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    (root / "a.txt").write_bytes(b"aaaa")
    (root / "b.txt").write_bytes(b"bbbb")
    ctx = Context(
        flags=Flags(max_text_mb=1),
        home=tmp_path,
        roots=[root],
        started_at=time.time(),
        deadline=time.time() + 60,
    )
    actx = ArchContext(ctx, root, False, {}, {})
    actx.trees["primary"] = TreeView("primary", "filesystem", root, None, "test")
    entries = {entry.rel: entry for entry in actx.files()}
    original = context_module.read_limited
    calls = []

    def counted(entry, limit):
        calls.append(entry.rel)
        return original(entry, limit)

    monkeypatch.setattr(context_module, "READ_CACHE_LIMIT", 6)
    monkeypatch.setattr(context_module, "read_limited", counted)

    assert actx.read(entries["a.txt"]) == b"aaaa"
    assert actx.read(entries["a.txt"]) == b"aaaa"
    assert actx.read(entries["b.txt"]) == b"bbbb"
    assert actx.read(entries["a.txt"]) == b"aaaa"
    assert calls == ["a.txt", "b.txt", "a.txt"]
