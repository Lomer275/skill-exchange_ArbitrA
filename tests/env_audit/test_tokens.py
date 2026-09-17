from .schema_check import validate
from .transcript_builders import (
    assistant_line,
    iso,
    tool_use,
    user_line,
    write_codex_session,
    write_session,
)


def _run_tokens(run_collect, fake_home):
    result = run_collect("--root", fake_home / "projects", "--only", "tokens")
    assert result.data is not None
    return result


def test_by_source_segments(fake_home, run_collect):
    ts = iso(1)
    write_session(
        fake_home,
        "/p",
        "sources",
        [
            user_line(ts, text="human", origin="human"),
            assistant_line(ts, msg_id="m1", req_id="r1", usage=(0, 0, 0, 10)),
            user_line(ts, command="loop", origin="human"),
            assistant_line(ts, msg_id="m2", req_id="r2", usage=(0, 0, 0, 20)),
            user_line(ts, text="background", origin="task-notification"),
            assistant_line(ts, msg_id="m3", req_id="r3", usage=(0, 0, 0, 30)),
            user_line(ts, text="<<autonomous-loop refire", origin="task-notification"),
            assistant_line(ts, msg_id="m4", req_id="r4", usage=(0, 0, 0, 40)),
        ],
    )
    result = _run_tokens(run_collect, fake_home)
    claude = result.data["sections"]["tokens"]["claude"]
    assert claude["by_source"]["human"]["cache_read"] == 10
    assert claude["by_source"]["loop"]["cache_read"] == 60
    assert claude["by_source"]["task-notification"]["cache_read"] == 30
    assert claude["loop_invocations"]["human"] == 1
    assert claude["loop_refires"] == 1


def test_tool_result_does_not_switch_segment(fake_home, run_collect):
    ts = iso(1)
    write_session(
        fake_home,
        "/p",
        "tool-result",
        [
            user_line(ts, command="loop"),
            user_line(ts, text="tool output", tool_result=True, origin=None),
            assistant_line(ts, msg_id="m1", req_id="r1", usage=(0, 0, 0, 5)),
        ],
    )
    result = _run_tokens(run_collect, fake_home)
    by_source = result.data["sections"]["tokens"]["claude"]["by_source"]
    assert by_source["loop"]["cache_read"] == 5


def test_codex_last_max_total(fake_home, run_collect):
    write_codex_session(fake_home, "c1", iso(1), [100, 250, 250])
    result = _run_tokens(run_collect, fake_home)
    totals = result.data["sections"]["tokens"]["codex"]["totals"]
    assert totals["30"]["total"] == 250


def test_codex_period_by_last_activity(fake_home, run_collect):
    write_codex_session(
        fake_home,
        "active",
        iso(20),
        [100],
        last_activity=iso(2),
    )
    result = _run_tokens(run_collect, fake_home)
    codex = result.data["sections"]["tokens"]["codex"]
    assert codex["sessions"]["14"] == 1
    assert codex["totals"]["14"]["total"] == 100


def test_codex_subagent_separate(fake_home, run_collect):
    write_codex_session(fake_home, "main", iso(1), [10])
    write_codex_session(fake_home, "agent", iso(1), [20], subagent=True)
    result = _run_tokens(run_collect, fake_home)
    codex = result.data["sections"]["tokens"]["codex"]
    assert codex["sessions"]["30"] == 1
    assert codex["subagent_sessions"]["30"] == 1


def test_codex_absent(fake_home, run_collect):
    result = _run_tokens(run_collect, fake_home)
    assert result.rc == 0
    assert result.data["sections"]["tokens"]["codex"]["present"] is False


def test_codex_share_edits(fake_home, run_collect):
    recent = iso(1)
    old = iso(20)
    write_session(
        fake_home,
        "/p",
        "edits",
        [
            assistant_line(
                recent,
                msg_id="m1",
                req_id="r1",
                tool_uses=[tool_use("Edit", id="a", file_path="src/a.py")],
            ),
            assistant_line(
                recent,
                msg_id="m2",
                req_id="r2",
                tool_uses=[tool_use("Edit", id="a", file_path="src/a.py")],
            ),
            assistant_line(
                recent,
                msg_id="m3",
                req_id="r3",
                tool_uses=[
                    tool_use("Edit", id="b", file_path="src/b.py"),
                    tool_use("Write", id="c", file_path="notes/n.md"),
                ],
            ),
            user_line(recent, command="team-skills:impl"),
            assistant_line(
                recent,
                msg_id="m4",
                req_id="r4",
                tool_uses=[tool_use("Skill", id="d", skill="codex:rescue")],
            ),
            assistant_line(
                old,
                msg_id="m5",
                req_id="r5",
                tool_uses=[tool_use("Edit", id="e", file_path="src/z.py")],
            ),
        ],
    )
    result = _run_tokens(run_collect, fake_home)
    share = result.data["sections"]["tokens"]["codex_share_14"]
    assert share["claude_code_edits"] == 2
    assert share["claude_other_edits"] == 1
    assert share["codex_skill_invocations"] == {
        "team-skills:impl": 1,
        "codex:rescue": 1,
    }


def test_origin_less_turn_inferred_human(fake_home, run_collect):
    ts = iso(1)
    turn = user_line(ts, origin=None)
    turn["message"]["content"] = [{"type": "text", "text": "hello"}]
    write_session(
        fake_home,
        "/p",
        "origin-less",
        [
            turn,
            assistant_line(ts, msg_id="m1", req_id="r1", usage=(0, 0, 0, 9)),
        ],
    )
    result = _run_tokens(run_collect, fake_home)
    claude = result.data["sections"]["tokens"]["claude"]
    assert claude["by_source"]["human"]["cache_read"] == 9
    assert claude["inferred_human_turns"] == 1


def test_compact_summary_keeps_segment(fake_home, run_collect):
    ts = iso(1)
    write_session(
        fake_home,
        "/p",
        "compact",
        [
            user_line(ts, text="<task-notification>done", origin=None),
            user_line(ts, text="This session is being continued…", origin=None, compact=True),
            assistant_line(ts, msg_id="m1", req_id="r1", usage=(0, 0, 0, 11)),
        ],
    )
    result = _run_tokens(run_collect, fake_home)
    claude = result.data["sections"]["tokens"]["claude"]
    assert claude["by_source"]["task-notification"]["cache_read"] == 11
    assert claude["inferred_human_turns"] == 0


def test_schema_valid(fake_home, run_collect):
    ts = iso(1)
    write_session(
        fake_home,
        "/p",
        "schema",
        [
            user_line(ts, text="human"),
            assistant_line(ts, msg_id="m1", req_id="r1", usage=(1, 2, 3, 4)),
        ],
    )
    write_codex_session(fake_home, "schema", ts, [10, 20])
    result = _run_tokens(run_collect, fake_home)
    assert result.rc == 0
    validate(result.data)
