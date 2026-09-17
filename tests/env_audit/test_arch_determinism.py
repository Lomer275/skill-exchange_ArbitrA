import json
from pathlib import Path

from .arch_builders import architecture_determinism_tree, isolated_runtime
from .schema_check import validate


TIME_FIELDS = {
    "last_commit_at",
    "newest_change_days",
    "newest_mtime_days",
    "repo_first_commit_at",
    "repo_last_commit_at",
    "timings_s",
}


def _without_time_fields(value):
    if isinstance(value, dict):
        return {
            key: _without_time_fields(item)
            for key, item in value.items()
            if key not in TIME_FIELDS
        }
    if isinstance(value, list):
        return [_without_time_fields(item) for item in value]
    return value


def _serialized_architecture(data: dict) -> bytes:
    architecture = _without_time_fields(data["sections"]["architecture"])
    return json.dumps(
        architecture,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _assert_rich_fixture(architecture: dict, root: Path) -> None:
    arch = architecture[str(root.resolve())]
    assert arch["tree"]["vcs"]["present"] is True
    assert arch["runtime"]["live_units"]
    assert [item["name"] for item in arch["runtime"]["live_units"]] == sorted(
        item["name"] for item in arch["runtime"]["live_units"]
    )
    assert arch["classification"]["type"] == "application"
    assert arch["size"]["by_language"]["python"]["files"] > 200
    assert arch["gates"]["layers_declared"]
    assert arch["ops"]["live_closure"]
    assert arch["schema_db"]["migration_dirs"]
    assert arch["python"]["duplicates"]["truncated"] is True
    assert arch["python"]["duplicates"]["callseq_pairs"]
    assert arch["python"]["interface_to_client_edges"]
    assert arch["python"]["orphans"]
    assert arch["docs"]["agent_files"]
    assert arch["docs"]["missing_paths"]
    assert arch["hygiene"]["backups"]
    assert arch["hygiene"]["broken_names"]
    assert arch["scripts_collection"]
    assert arch["php"]["files_top"]
    assert arch["js"]["files"]
    assert arch["csharp"]["projects"]


def test_architecture_section_deterministic(
    tmp_path: Path, isolated_runtime: Path, run_collect
) -> None:
    root = architecture_determinism_tree(
        tmp_path / "architecture-determinism", isolated_runtime
    )

    sections = []
    for seed in ("0", "1"):
        result = run_collect(
            "--only",
            "architecture",
            "--root",
            root,
            env_extra={"PYTHONHASHSEED": seed},
        )
        assert result.rc == 0, result.stdout
        validate(result.data)
        architecture = result.data["sections"]["architecture"]
        _assert_rich_fixture(architecture, root)
        sections.append(_serialized_architecture(result.data))

    assert sections[0] == sections[1]
