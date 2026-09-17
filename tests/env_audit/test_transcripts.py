import json

from envaudit.core.transcripts import (
    WHITELIST_PATHS,
    _codex_line,
    project_line,
    skill_usage,
)

from .canaries import canary, fragments
from .transcript_builders import (
    assistant_line,
    attachment_line,
    iso,
    tool_use,
    user_line,
    write_claude_json,
    write_session,
    write_settings,
)


class TrackingDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._path = ""
        self._accessed: set[str] | None = None

    def bind(self, path: str, accessed: set[str]) -> None:
        self._path = path
        self._accessed = accessed
        for key, value in dict.items(self):
            child = f"{path}.{key}" if path else str(key)
            if isinstance(value, TrackingDict):
                value.bind(child, accessed)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, TrackingDict):
                        item.bind(f"{child}[]", accessed)

    def _record(self, key: object) -> None:
        if self._accessed is not None:
            child = f"{self._path}.{key}" if self._path else str(key)
            self._accessed.add(child)

    def get(self, key, default=None):
        self._record(key)
        return dict.get(self, key, default)

    def __contains__(self, key):
        self._record(key)
        return dict.__contains__(self, key)


def _tracked(value: dict) -> tuple[TrackingDict, set[str]]:
    obj = json.loads(json.dumps(value), object_hook=TrackingDict)
    accessed: set[str] = set()
    obj.bind("", accessed)
    return obj, accessed


def _run_tokens(run_collect, fake_home):
    return run_collect("--root", fake_home / "projects", "--only", "tokens")


def test_whitelist_only():
    ts = iso(1)
    claude_lines = [
        {
            **user_line(ts, text="ordinary text"),
            "parentUuid": "parent",
            "unrelated": "ignored",
        },
        {
            **assistant_line(
                ts,
                msg_id="m1",
                req_id="r1",
                tool_uses=[
                    {
                        **tool_use(
                            "Edit",
                            id="tu1",
                            file_path="src/a.py",
                            skill="team-skills:impl",
                            extra_input={"command": "ignored"},
                        ),
                        "text": "ignored",
                    }
                ],
            ),
            "toolUseResult": {"content": "ignored"},
        },
        user_line(ts, text="result text", tool_result=True),
        attachment_line(
            ts,
            type="skill_listing",
            content="listing",
            rendered=["rendered"],
            skill_count=2,
            skills=["a", "b"],
            files=["policy", "memory"],
        ),
    ]
    accessed: set[str] = set()
    for line_no, line in enumerate(claude_lines, 1):
        obj, current = _tracked(line)
        project_line(
            obj,
            project_dir="project",
            session="session",
            is_subagent_file=False,
            line_no=line_no,
        )
        accessed.update(current)

    codex_lines = [
        {
            "type": "session_meta",
            "payload": {
                "id": "c1",
                "timestamp": ts,
                "source": "cli",
                "cwd": "ignored",
                "thread_source": "subagent",
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 1,
                        "cached_input_tokens": 2,
                        "cache_write_input_tokens": 3,
                        "output_tokens": 4,
                        "reasoning_output_tokens": 5,
                        "total_tokens": 15,
                        "extra": "ignored",
                    }
                },
                "ignored": "value",
            },
        },
    ]
    for line in codex_lines:
        obj, current = _tracked(line)
        _codex_line(obj)
        accessed.update(current)

    assert accessed <= set(WHITELIST_PATHS)


def test_canaries_not_in_output(fake_home, run_collect):
    values = [canary("openai_key", seed) for seed in range(5)]
    ts = iso(1)
    write_session(
        fake_home,
        "/p",
        "main",
        [
            user_line(ts, text=values[0]),
            user_line(ts, text=values[1], command="loop"),
            assistant_line(
                ts,
                msg_id="m1",
                req_id="r1",
                tool_uses=[
                    tool_use(
                        "Bash", id="t1", extra_input={"command": f"echo {values[2]}"}
                    )
                ],
            ),
            attachment_line(ts, type="skill_listing", content=values[3]),
        ],
    )
    write_session(
        fake_home,
        "/p",
        "agent",
        [user_line(ts, text=values[4])],
        subagent_of="main",
    )

    result = _run_tokens(run_collect, fake_home)
    assert result.rc == 0
    for value in values:
        for fragment in fragments(value):
            assert fragment not in result.stdout


def test_dedup_three_lines_once(fake_home, run_collect):
    line = assistant_line(
        iso(1), msg_id="same", req_id="same-request", usage=(1, 1, 0, 100)
    )
    write_session(fake_home, "/p", "s1", [line, line, line])
    result = _run_tokens(run_collect, fake_home)
    claude = result.data["sections"]["tokens"]["claude"]
    assert claude["periods"]["30"]["total"]["cache_read"] == 100
    assert claude["duplicates_dropped"] == 2


def test_command_name_real_format():
    loop = project_line(
        user_line(iso(1), command="loop"),
        project_dir="project",
        session="session",
        is_subagent_file=False,
        line_no=1,
    )
    impl = project_line(
        user_line(iso(1), command="team-skills:impl"),
        project_dir="project",
        session="session",
        is_subagent_file=False,
        line_no=2,
    )
    ordinary = project_line(
        user_line(iso(1), text="echo <command-name> in ordinary text"),
        project_dir="project",
        session="session",
        is_subagent_file=False,
        line_no=3,
    )

    assert loop is not None and loop.command_name == "loop"
    assert impl is not None and impl.command_name == "team-skills:impl"
    assert ordinary is not None and ordinary.command_name is None


def test_subagent_usage_separate(fake_home, run_collect):
    write_session(
        fake_home,
        "/p",
        "main",
        [assistant_line(iso(1), msg_id="main", req_id="r1", usage=(0, 0, 0, 10))],
    )
    write_session(
        fake_home,
        "/p",
        "agent",
        [assistant_line(iso(1), msg_id="agent", req_id="r2", usage=(0, 0, 0, 7))],
        subagent_of="main",
    )
    result = _run_tokens(run_collect, fake_home)
    period = result.data["sections"]["tokens"]["claude"]["periods"]["30"]
    assert period["total"]["cache_read"] == 10
    assert period["subagents_total"]["cache_read"] == 7


def test_window_from_settings(fake_home, run_collect):
    write_settings(fake_home, {"cleanupPeriodDays": 7})
    result = _run_tokens(run_collect, fake_home)
    section = result.data["sections"]["tokens"]
    assert section["window_days"] == 7
    assert section["claude"]["periods"] == {"14": None, "30": None}
    skips = [item for item in result.data["skipped"] if item["section"] == "tokens"]
    assert [item["reason"] for item in skips] == ["not_applicable", "not_applicable"]


def test_old_records_ignored(fake_home, run_collect):
    write_session(
        fake_home,
        "/p",
        "old",
        [assistant_line(iso(40), msg_id="old", req_id="old", usage=(1, 2, 3, 4))],
    )
    result = _run_tokens(run_collect, fake_home)
    period = result.data["sections"]["tokens"]["claude"]["periods"]["30"]
    assert period["messages"] == 0
    assert period["total"] == {
        "input": 0,
        "output": 0,
        "cache_creation": 0,
        "cache_read": 0,
    }


def test_bad_json_counted(fake_home, run_collect):
    path = write_session(fake_home, "/p", "broken", [])
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{broken\n")
    result = _run_tokens(run_collect, fake_home)
    assert result.rc == 0
    assert result.data["sections"]["tokens"]["claude"]["bad_lines"] == 1


def test_skill_usage_reader(fake_home):
    write_claude_json(
        fake_home,
        {"skillUsage": {"x": {"usageCount": 3, "lastUsedAt": 1_750_000_000_000}}},
    )
    assert skill_usage(fake_home) == {
        "x": {"usage_count": 3, "last_used_at": 1_750_000_000.0}
    }
