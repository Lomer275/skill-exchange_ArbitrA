import os
from pathlib import Path

from .arch_builders import isolated_runtime, ir2_like, write_crontab_stub
from .schema_check import validate


def _collect(run_collect, root: Path, bin_dir: Path | None = None) -> tuple[dict, object]:
    env = None
    if bin_dir is not None:
        env = {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
    result = run_collect(
        "--only", "architecture", "--root", root, env_extra=env
    )
    assert result.rc == 0, result.stdout
    validate(result.data)
    arch = result.data["sections"]["architecture"][str(root.resolve())]
    return arch, result


def test_integration_scripts(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "scripts"
    ir2_like(root, py_files=40)
    scripts = sorted(root.glob("*.py"))
    bin_dir = tmp_path / "bin"
    write_crontab_stub(
        bin_dir,
        [
            f"0 1 * * * cd {root} && python3 {scripts[0].name}",
            f"0 2 * * * cd {root} && python3 {scripts[1].name}",
        ],
    )

    arch, _ = _collect(run_collect, root, bin_dir)

    assert arch["classification"]["type"] == "integration-scripts"
    step = next(item for item in arch["classification"]["decision_trace"] if item["step"] == 2)
    assert step["matched"] is True
    assert not any(item["step"] == 3 for item in arch["classification"]["decision_trace"])


def test_cron_agent(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "agent-project"
    package = root / "agent"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "common.py").write_text("VALUE = 1\n", encoding="utf-8")
    for name in ("x", "y", "a", "b", "c"):
        (package / f"{name}.py").write_text(
            "from agent import common\n"
            "def main():\n"
            "    return common.VALUE\n",
            encoding="utf-8",
        )
    bin_dir = tmp_path / "bin"
    write_crontab_stub(
        bin_dir,
        [
            f"0 1 * * * cd {root} && python3 -m agent.x",
            f"0 2 * * * cd {root} && python3 -m agent.y",
        ],
    )

    arch, _ = _collect(run_collect, root, bin_dir)

    assert arch["classification"]["type"] == "application"
    assert arch["classification"]["subtype"] == "cron-agent"


def test_service_compose_commands(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "service"
    root.mkdir()
    (root / "manage.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (root / "settings.py").write_text("INSTALLED_APPS = []\n", encoding="utf-8")
    services = "\n".join(
        f"  worker{i}:\n    build: .\n    command: python manage.py task{i}"
        for i in range(3)
    )
    (root / "docker-compose.yml").write_text(
        "services:\n" + services + "\n", encoding="utf-8"
    )

    arch, _ = _collect(run_collect, root)

    assert arch["classification"]["type"] == "application"
    assert arch["classification"]["subtype"] == "service"
    assert len(arch["classification"]["groups"]) == 1


def test_multi_app(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "bots"
    root.mkdir()
    compose = ["services:"]
    for index in (1, 2):
        directory = root / f"bot{index}"
        directory.mkdir()
        (directory / "Dockerfile").write_text(
            "FROM python:3\nCMD [\"python\", \"main.py\"]\n",
            encoding="utf-8",
        )
        (directory / "main.py").write_text(
            "from aiogram import Dispatcher\n"
            "dp = Dispatcher()\n"
            "async def run():\n"
            "    await dp.start_polling()\n",
            encoding="utf-8",
        )
        compose.extend(
            [
                f"  bot{index}:",
                f"    build: ./bot{index}",
                "    command: python main.py",
            ]
        )
    (root / "docker-compose.yml").write_text("\n".join(compose) + "\n", encoding="utf-8")

    arch, _ = _collect(run_collect, root)

    assert arch["classification"]["subtype"] == "multi-app"
    assert len(arch["classification"]["groups"]) == 2
    assert sum(group["edges_to_other_groups"] for group in arch["classification"]["groups"]) == 0


def test_client_server(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "client-server"
    root.mkdir()
    (root / "api.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "app.run()\n",
        encoding="utf-8",
    )
    (root / "Client.csproj").write_text(
        "<Project><PropertyGroup><UseWPF>true</UseWPF></PropertyGroup></Project>",
        encoding="utf-8",
    )

    arch, _ = _collect(run_collect, root)

    assert arch["classification"]["subtype"] == "client-server"


def test_import_without_start_not_anchor(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "maxapi-import"
    root.mkdir()
    (root / "handler.py").write_text(
        "from maxapi import Bot\n"
        "bot = Bot()\n",
        encoding="utf-8",
    )

    arch, _ = _collect(run_collect, root)

    assert not any(
        anchor["kind"] == "web_app"
        for anchor in arch["runtime"]["anchors"]
    )


def test_django_settings_not_anchor(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "django"
    root.mkdir()
    (root / "manage.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (root / "settings.py").write_text(
        "INSTALLED_APPS = []\n", encoding="utf-8"
    )

    arch, _ = _collect(run_collect, root)

    web_anchors = [
        anchor
        for anchor in arch["runtime"]["anchors"]
        if anchor["kind"] == "web_app"
    ]
    assert [anchor["file"] for anchor in web_anchors] == ["manage.py"]


def test_code_anchor_does_not_create_group(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "service-with-tool"
    tools = root / "tools"
    tools.mkdir(parents=True)
    (root / "docker-compose.yml").write_text(
        "services:\n"
        "  app:\n"
        "    build: .\n"
        "    command: python run.py\n",
        encoding="utf-8",
    )
    (root / "run.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (tools / "server.py").write_text(
        "class Server:\n"
        "    def serve_forever(self):\n"
        "        return None\n"
        "Server().serve_forever()\n",
        encoding="utf-8",
    )

    arch, _ = _collect(run_collect, root)

    assert len(arch["classification"]["groups"]) == 1
    assert arch["classification"]["unattached_code_anchors"] == [
        "tools/server.py"
    ]


def test_plugin_in_host(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "plugin"
    target = root / "local" / "modules" / "x" / "install"
    target.mkdir(parents=True)
    (target / "index.php").write_text(
        "<?php RegisterModuleDependences('a', 'b', 'c', 'd');",
        encoding="utf-8",
    )

    arch, _ = _collect(run_collect, root)

    assert arch["classification"]["subtype"] == "plugin-in-host"


def test_docs_and_mixed(tmp_path: Path, run_collect) -> None:
    docs = tmp_path / "docs-only"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    for index in range(3):
        (mixed / f"module_{index}.py").write_text(f"VALUE = {index}\n", encoding="utf-8")

    docs_arch, _ = _collect(run_collect, docs)
    mixed_arch, _ = _collect(run_collect, mixed)

    assert docs_arch["classification"]["type"] == "docs"
    assert docs_arch["classification"]["calibrated"] is False
    assert mixed_arch["classification"]["type"] == "mixed"
    assert mixed_arch["classification"]["calibrated"] is False


def test_subproject_excluded(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "parent"
    nested = root / "deploy" / "data-platform"
    nested.mkdir(parents=True)
    (root / "docker-compose.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    (nested / "docker-compose.yml").write_text(
        "services:\n  data:\n    build: .\n    command: python worker.py\n",
        encoding="utf-8",
    )
    (nested / "worker.py").write_text("print('worker')\n", encoding="utf-8")
    (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")

    arch, _ = _collect(run_collect, root)

    assert "deploy/data-platform" in arch["classification"]["subprojects"]
    assert all(
        "deploy/data-platform" not in anchor
        for group in arch["classification"]["groups"]
        for anchor in group["anchors"]
    )


def test_components_without_root_container(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "components"
    server = root / "server"
    client = root / "client" / "App"
    server.mkdir(parents=True)
    client.mkdir(parents=True)
    (server / "Dockerfile").write_text(
        "FROM python:3\nCMD gunicorn app:app\n", encoding="utf-8"
    )
    (server / "docker-compose.yml").write_text(
        "services:\n  api:\n    build: .\n", encoding="utf-8"
    )
    (client / "App.csproj").write_text(
        "<Project><PropertyGroup><UseWPF>true</UseWPF></PropertyGroup></Project>",
        encoding="utf-8",
    )

    arch, _ = _collect(run_collect, root)

    assert arch["classification"]["type"] == "application"
    assert arch["classification"]["subtype"] == "client-server"
    assert arch["classification"]["subprojects"] == []


def test_two_dockerfiles_same_context_multi_app(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "two-images"
    demo = root / "demo_bot"
    demo.mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3\nCMD ["python", "bot.py"]\n', encoding="utf-8"
    )
    (root / "Dockerfile.demo").write_text(
        'FROM python:3\nCMD ["python", "demo_bot/bot.py"]\n', encoding="utf-8"
    )
    bot_source = (
        "from aiogram import Dispatcher\n"
        "dp = Dispatcher()\n"
        "async def run():\n"
        "    await dp.start_polling()\n"
    )
    (root / "bot.py").write_text(bot_source, encoding="utf-8")
    (demo / "bot.py").write_text(bot_source, encoding="utf-8")

    arch, _ = _collect(run_collect, root)

    assert arch["classification"]["type"] == "application"
    assert arch["classification"]["subtype"] == "multi-app"
    assert len(arch["classification"]["groups"]) == 2
    assert sum(
        group["edges_to_other_groups"]
        for group in arch["classification"]["groups"]
    ) == 0


def test_module_entry_multi_app(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "module-entry"
    demo = root / "demo_bot"
    demo.mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3\nCMD ["python", "bot.py"]\n', encoding="utf-8"
    )
    (root / "Dockerfile.demo").write_text(
        'FROM python:3\nCMD ["python", "-m", "demo_bot.bot"]\n',
        encoding="utf-8",
    )
    (root / "docker-compose.demo.yml").write_text(
        "services:\n"
        "  demo:\n"
        "    build: {context: ., dockerfile: Dockerfile.demo}\n",
        encoding="utf-8",
    )
    (root / "bot.py").write_text(
        "import config\n"
        "import handlers\n"
        "import middlewares\n"
        "from aiogram import Dispatcher\n"
        "dp = Dispatcher()\n"
        "async def run():\n"
        "    await dp.start_polling()\n",
        encoding="utf-8",
    )
    for name in ("config", "handlers", "middlewares"):
        (root / f"{name}.py").write_text("VALUE = 1\n", encoding="utf-8")
    (demo / "__init__.py").write_text("", encoding="utf-8")
    (demo / "bot.py").write_text(
        "import demo_bot.config\n"
        "import demo_bot.handlers\n"
        "import demo_bot.middlewares\n"
        "from aiogram import Dispatcher\n"
        "dp = Dispatcher()\n"
        "async def run():\n"
        "    await dp.start_polling()\n",
        encoding="utf-8",
    )
    for name in ("config", "handlers", "middlewares"):
        (demo / f"{name}.py").write_text("VALUE = 1\n", encoding="utf-8")

    arch, _ = _collect(run_collect, root)

    assert arch["classification"]["type"] == "application"
    assert arch["classification"]["subtype"] == "multi-app"
    assert len(arch["classification"]["groups"]) == 2
    assert sum(
        group["edges_to_other_groups"]
        for group in arch["classification"]["groups"]
    ) == 0
    demo_anchor = next(
        anchor
        for anchor in arch["runtime"]["anchors"]
        if anchor["kind"] == "dockerfile_cmd"
        and anchor["file"] == "Dockerfile.demo"
    )
    assert demo_anchor["entry"] == "demo_bot/bot.py"
    assert all(
        any(anchor.startswith("dockerfile_cmd:") for anchor in group["anchors"])
        and any(anchor.startswith("web_app:") for anchor in group["anchors"])
        for group in arch["classification"]["groups"]
    )


def test_test_server_not_anchor(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "service-with-test-server"
    tests = root / "tests"
    tests.mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3\nCMD ["python", "sentinel.py"]\n', encoding="utf-8"
    )
    (root / "sentinel.py").write_text("def run():\n    return 0\n", encoding="utf-8")
    (tests / "conftest.py").write_text(
        "from http.server import ThreadingHTTPServer\n"
        "server = ThreadingHTTPServer(('localhost', 0), object)\n",
        encoding="utf-8",
    )

    arch, _ = _collect(run_collect, root)

    assert arch["classification"]["type"] == "application"
    assert arch["classification"]["subtype"] == "service"
    assert len(arch["classification"]["groups"]) == 1
