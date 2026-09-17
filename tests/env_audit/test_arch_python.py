import json
from pathlib import Path

from envaudit.arch.py.dups import PAIR_LIMIT

from .py_builders import make_package


def _callseq_source(group_call: str) -> str:
    body = [
        "def candidate(value):",
        "    value = shared_call(value)",
        f"    value = {group_call}(value)",
    ]
    body.extend(f"    value += {index}" for index in range(40))
    body.append("    return value")
    return "\n".join(body) + "\n"


def test_callseq_deterministic_under_truncation(tmp_path: Path, run_collect) -> None:
    module_count = 202
    assert module_count * (module_count - 1) // 2 > PAIR_LIMIT
    files = {"Dockerfile": 'FROM python:3\nCMD ["python", "module_000.py"]\n'}
    files.update(
        {
            f"module_{index:03d}.py": _callseq_source(
                "group_zero" if index < 101 else "group_one"
            )
            for index in range(module_count)
        }
    )
    root = make_package(tmp_path / "callseq-truncation", files)

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
        duplicates = result.data["sections"]["architecture"][str(root.resolve())][
            "python"
        ]["duplicates"]
        assert duplicates["truncated"] is True
        sections.append(
            json.dumps(
                duplicates["callseq_pairs"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    assert sections[0] == sections[1]
