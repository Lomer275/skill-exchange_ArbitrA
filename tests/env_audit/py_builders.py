from pathlib import Path


def make_package(root: Path, spec: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, source in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


def django_app(root: Path, name: str, models: int) -> Path:
    fields = "\n".join(f"field_{index} = {index}" for index in range(models))
    return make_package(
        root,
        {
            "manage.py": "def main():\n    return 0\n",
            "settings.py": f"INSTALLED_APPS = ['{name}']\n",
            f"{name}/__init__.py": "",
            f"{name}/models.py": fields + "\n",
            f"{name}/admin.py": f"from {name} import models\n",
            f"{name}/templatetags/__init__.py": "",
            f"{name}/templatetags/x.py": "def value():\n    return 1\n",
            f"{name}/templates/page.html": "{% load x %}\n",
        },
    )


def two_channels(root: Path) -> Path:
    return make_package(
        root,
        {
            "docker-compose.yml": (
                "services:\n"
                "  tg:\n    build: .\n    command: python tg_bot/main.py\n"
                "  max:\n    build: .\n    command: python max_bot/main.py\n"
            ),
            "tg_bot/__init__.py": "",
            "tg_bot/main.py": (
                "from aiogram import Dispatcher\n"
                "from tg_bot import handlers\n"
                "dp = Dispatcher()\n"
                "async def run():\n    await dp.start_polling()\n"
            ),
            "tg_bot/handlers.py": "def ping():\n    return 'tg'\n",
            "max_bot/__init__.py": "",
            "max_bot/main.py": (
                "from maxapi import Bot\n"
                "from max_bot import handlers\n"
                "bot = Bot()\n"
                "async def run():\n    await bot.start_polling()\n"
            ),
            "max_bot/handlers.py": "def ping():\n    return 'max'\n",
            "shared/__init__.py": "",
        },
    )


def big_module(lines: int, defs: int) -> str:
    blocks = []
    for index in range(defs):
        blocks.extend(
            [
                f"def function_{index}(value={index}):",
                "    result = value + 1",
                "    return result",
                "",
            ]
        )
    while len(blocks) < lines:
        blocks.append("pass")
    return "\n".join(blocks[:lines]) + "\n"
