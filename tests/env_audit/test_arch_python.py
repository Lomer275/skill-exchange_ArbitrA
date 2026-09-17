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


def _duplicate_source() -> str:
    return "\n".join(
        [
            "def normalize(value):",
            "    value = value.strip()",
            "    value = value.lower()",
            "    value = value.replace('-', '_')",
            "    parts = value.split('_')",
            "    parts = [part for part in parts if part]",
            "    return '_'.join(parts)",
            "",
        ]
    )


def test_python_section_deterministic(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "python-deterministic",
        {
            "docker-compose.yml": (
                "services:\n"
                "  tg:\n    build: .\n    command: python tg_bot/main.py\n"
                "  max:\n    build: .\n    command: python max_bot/main.py\n"
            ),
            "requirements.txt": "requests==2.0\n",
            "shared/__init__.py": "",
            "shared/client.py": (
                "import requests\n"
                "def fetch(value):\n"
                "    return requests.get(value)\n"
            ),
            "tg_bot/__init__.py": "",
            "tg_bot/main.py": (
                "from aiogram import Dispatcher\n"
                "from tg_bot import auth, payments\n"
                "dp = Dispatcher()\n"
                "async def run():\n    await dp.start_polling()\n"
            ),
            "tg_bot/auth.py": (
                "from max_bot import bridge\n"
                "from shared import client\n"
                "def handle(value):\n    return client.fetch(value)\n"
            ),
            "tg_bot/payments.py": (
                "from shared import client\n"
                "def handle(value):\n    return client.fetch(value)\n"
            ),
            "max_bot/__init__.py": "",
            "max_bot/main.py": (
                "from maxapi import Bot\n"
                "from max_bot import auth, payments\n"
                "bot = Bot()\n"
                "async def run():\n    await bot.start_polling()\n"
            ),
            "max_bot/auth.py": (
                "from shared import client\n"
                "def handle(value):\n    return client.fetch(value)\n"
            ),
            "max_bot/payments.py": (
                "from shared import client\n"
                "def handle(value):\n    return client.fetch(value)\n"
            ),
            "max_bot/bridge.py": "import maxapi\nVALUE = 1\n",
            "orphan_a.py": _duplicate_source(),
            "orphan_b.py": _duplicate_source(),
        },
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
        python_section = result.data["sections"]["architecture"][str(root.resolve())][
            "python"
        ]
        python_section.pop("timings_s", None)
        assert python_section["interface_to_client_edges"]
        assert python_section["channels"]["cross_channel_edges"]
        assert python_section["duplicates"]["function_hash_groups"]
        assert python_section["orphans"]
        sections.append(
            json.dumps(
                python_section,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    assert sections[0] == sections[1]


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
