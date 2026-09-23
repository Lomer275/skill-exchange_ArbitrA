import time

import jsonschema
import pytest

from envaudit.core.budget import run_sections
from envaudit.core.context import Context, Flags
from envaudit.sections import architecture, secrets

from .schema_check import load_schema


def _passing_controls():
    return {
        "tree": "pass",
        "git_head": "not_checked",
        "git_history": "not_checked",
        "configs": "pass",
        "home": "pass",
    }


def _section_schema(name: str) -> dict:
    return load_schema()["properties"]["sections"]["properties"][name]


def test_secrets_hard_timeout_keeps_completed_blocks(
    fake_home, tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
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
    monkeypatch.setattr(secrets, "which", lambda _name: None)
    monkeypatch.setattr(
        secrets,
        "_scan_root",
        lambda _root, _ctx, _vcs: (time.sleep(1), {})[1],
    )
    started = time.time()
    ctx = Context(
        Flags(budget_seconds=1),
        fake_home,
        [root],
        started,
        started + 0.2,
    )

    sections, _ = run_sections(ctx, [secrets])

    partial = sections["secrets"]
    assert partial is not None
    assert partial["truncated"] is True
    assert "external_access" in partial
    assert "roots" not in partial
    assert {
        "section": "secrets",
        "reason": "budget",
        "details": None,
    } in ctx.skipped
    jsonschema.Draft202012Validator(_section_schema("secrets")).validate(partial)


def test_architecture_publishes_after_each_root(tmp_path, monkeypatch):
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()
    monkeypatch.setattr(architecture, "discover_checks", lambda: [])
    monkeypatch.setattr(architecture, "is_git_repo", lambda _root: False)
    started = time.time()
    ctx = Context(Flags(), tmp_path, roots, started, started + 30)

    result = architecture.collect(ctx)

    assert ctx.partial_sections["architecture"] == result
    partial = dict(result)
    partial["truncated"] = True
    jsonschema.Draft202012Validator(_section_schema("architecture")).validate(
        partial
    )


def test_full_secrets_schema_still_requires_all_blocks():
    partial = {
        "truncated": True,
        "lower_bound": True,
        "timings_s": {"positive_controls": 0.0},
        "positive_controls": _passing_controls(),
        "generic_assignment_scope": [
            "context_files",
            "agent_configs",
            "shell_history",
            "config_dir",
        ],
    }
    validator = jsonschema.Draft202012Validator(_section_schema("secrets"))

    validator.validate(partial)
    full_without_blocks = dict(partial)
    full_without_blocks.pop("truncated")
    with pytest.raises(jsonschema.exceptions.ValidationError):
        validator.validate(full_without_blocks)
