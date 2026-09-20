from pathlib import Path

from .arch_builders import isolated_runtime, make_repo
from .py_builders import make_package, two_channels
from .schema_check import validate


def _arch(run_collect, root: Path) -> dict:
    result = run_collect("--only", "architecture", "--root", root)
    assert result.rc == 0, result.stdout
    validate(result.data)
    return result.data["sections"]["architecture"][str(root.resolve())]


def test_layers_computed_not_by_name(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "layers",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "main.py"]\n',
            "requirements.txt": "requests==2.0\n",
            "main.py": "import core.money\nimport utils.calc\n",
            "core/__init__.py": "",
            "core/money.py": "import requests\ndef rate():\n    return requests.get('https://example.invalid')\n",
            "utils/__init__.py": "",
            "utils/calc.py": "import math\ndef total(value):\n    return math.ceil(value)\n",
        },
    )
    arch = _arch(run_collect, root)
    assignment = arch["python"]["layers"]["assignment"]
    assert assignment["core/money.py"] == "adapters"
    assert assignment["utils/calc.py"] == "core"


def test_io_list_source_reported(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "io-list",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "main.py"]\n',
            "requirements.txt": "aiohttp==3.0\n",
            "main.py": "import aiohttp\n",
        },
    )
    arch = _arch(run_collect, root)
    libs = arch["python"]["framework_libs"]
    assert libs["io_list_source"] == "manifest+builtin"
    assert libs["io_list_size"] > 0


def test_a16_per_edge_sdk(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "cross-channel",
        {
            "docker-compose.yml": (
                "services:\n"
                "  tg:\n    build: .\n    command: python tg_bot/main.py\n"
                "  max:\n    build: .\n    command: python max_bot/main.py\n"
            ),
            "tg_bot/__init__.py": "",
            "tg_bot/main.py": (
                "from aiogram import Dispatcher\n"
                "from max_bot.services import x\n"
                "from max_bot.services import y\n"
                "dp = Dispatcher()\n"
                "async def run():\n    await dp.start_polling()\n"
            ),
            "max_bot/__init__.py": "",
            "max_bot/main.py": (
                "from maxapi import Bot\n"
                "bot = Bot()\n"
                "async def run():\n    await bot.start_polling()\n"
            ),
            "max_bot/services/__init__.py": "",
            "max_bot/services/x.py": "import maxapi\nVALUE = 1\n",
            "max_bot/services/y.py": "VALUE = 1\n",
        },
    )
    arch = _arch(run_collect, root)
    assert len(arch["python"]["channels"]["cross_channel_edges"]) == 2
    assert arch["rule_inputs"]["A16"]["edges_without_target_sdk"] == 1
    assert arch["rule_inputs"]["A16"]["targets_without_sdk"] == [
        "max_bot/services/y.py"
    ]
    assert "sdk_imports_in_targets" not in arch["rule_inputs"]["A16"]


def test_channels_prod_only(tmp_path: Path, run_collect) -> None:
    root = two_channels(tmp_path / "prod-only")
    tests = {
        "tests/__init__.py": "",
        "tests/test_shared.py": "from max_bot import handlers\n",
        "tg_bot/tests/__init__.py": "",
        "tg_bot/tests/test_cross.py": "from max_bot import handlers\n",
    }
    for rel, source in tests.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    channels = _arch(run_collect, root)["python"]["channels"]
    assert channels["cross_channel_edges"] == []
    assert channels["shared_to_channel_edges"] == []
    assert channels["importers_by_package"] == {"max_bot": [], "tg_bot": []}


def test_a17_diverged_pair(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "diverged",
        {
            "docker-compose.yml": (
                "services:\n"
                "  tg:\n    build: .\n    command: python tg_bot/main.py\n"
                "  max:\n    build: .\n    command: python max_bot/main.py\n"
            ),
            "requirements.txt": "requests==2.0\n",
            "shared/__init__.py": "",
            "shared/bitrix.py": "import requests\ndef get(kind):\n    return requests.get(kind)\n",
            "tg_bot/__init__.py": "",
            "tg_bot/main.py": (
                "from aiogram import Dispatcher\nfrom tg_bot import handlers\n"
                "dp = Dispatcher()\nasync def run():\n    await dp.start_polling()\n"
            ),
            "tg_bot/handlers.py": (
                "from shared import bitrix\n"
                "def get_contact_deals(contact):\n"
                "    deals = bitrix.get(contact)\n"
                "    return [item for item in deals if item]\n"
            ),
            "max_bot/__init__.py": "",
            "max_bot/main.py": (
                "from maxapi import Bot\nfrom max_bot import handlers\n"
                "bot = Bot()\nasync def run():\n    await bot.start_polling()\n"
            ),
            "max_bot/handlers.py": (
                "from shared import bitrix\n"
                "def get_contact_deals(contact):\n"
                "    deals = bitrix.get(contact)\n"
                "    filtered = [item for item in deals if item.get('stage') == 'priority']\n"
                "    filtered.sort(key=lambda item: item.get('created', ''))\n"
                "    return filtered\n"
            ),
        },
    )
    arch = _arch(run_collect, root)
    pair = next(
        item
        for item in arch["python"]["channels"]["same_name_pairs"]
        if item["name"] == "get_contact_deals"
    )
    assert pair["ratio"] < 0.95
    assert pair["both_call_client"] is True


def test_a17_runtime_target_gitignored(tmp_path: Path, run_collect) -> None:
    root = make_repo(
        tmp_path / "ignored-tool",
        {
            ".gitignore": "app/management/commands/x.py\n",
            "docker-compose.yml": (
                "services:\n  worker:\n    build: .\n"
                "    command: python app/management/commands/x.py\n"
            ),
            "app/__init__.py": "",
        },
    )
    target = root / "app" / "management" / "commands" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    arch = _arch(run_collect, root)
    assert arch["python"]["runtime_to_tools_edges"][0]["ignored"] is True


def test_single_channel_null(tmp_path: Path, run_collect) -> None:
    root = make_package(
        tmp_path / "single-channel",
        {
            "Dockerfile": 'FROM python:3\nCMD ["python", "tg_bot/main.py"]\n',
            "tg_bot/__init__.py": "",
            "tg_bot/main.py": (
                "from aiogram import Dispatcher\n"
                "dp = Dispatcher()\n"
                "async def run():\n    await dp.start_polling()\n"
            ),
        },
    )
    arch = _arch(run_collect, root)
    assert arch["python"]["channels"] is None
