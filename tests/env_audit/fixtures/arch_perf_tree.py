import json
from pathlib import Path


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_arch_perf_tree(root: Path) -> Path:
    """Build a small deterministic tree covering the optimized architecture paths."""
    root.mkdir(parents=True, exist_ok=True)

    for index in range(20):
        month = index % 12 + 1
        day = index % 28 + 1
        body = [
            f"def task_{index}():",
            f"    return {index}",
            "",
            "if __name__ == '__main__':",
            f"    task_{index}()",
        ]
        if index == 0:
            body = [
                "import importlib",
                "",
                "def task_0():",
                "    return importlib.import_module('json')",
                "",
                "if __name__ == '__main__':",
                "    task_0()",
            ]
        _write(
            root,
            f"jobs/task_2026{month:02d}{day:02d}_{index:03d}.py",
            "\n".join(body) + "\n",
        )

    shared_god = "<?php\nfunction shared_work() {}\n" + "$value += 1;\n" * 820
    _write(root, "local/a/hub.php", shared_god)
    _write(root, "local/b/hub.php", shared_god)
    _write(
        root,
        "local/c/unique.php",
        "<?php\nfunction unique_work() {}\n" + "$unique += 2;\n" * 830,
    )
    _write(
        root,
        "web/widget.php",
        "<main>template</main>\n"
        "<?php\n"
        "$ignored = 'function fake() {';\n"
        "// function commented() {}\n"
        "$document = <<<HTML\nfunction heredoc_fake() {}\nHTML;\n"
        "class Handler { public function execute() { return 1; } }\n"
        "function standalone() { CCrmDeal::GetList(); curl_init(); }\n"
        "?>\n"
        "<footer>template</footer>\n",
    )

    workflow = {
        "nodes": [
            {
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "https://example.invalid/hook"},
            }
        ],
        "connections": {},
        "padding": "x" * 4096,
    }
    _write(root, "workflows/export.json", json.dumps(workflow, sort_keys=True))
    _write(root, "data/ordinary.json", json.dumps({"payload": "x" * 70000}))

    _write(root, "alembic.ini", "[alembic]\nscript_location = migrations\n")
    _write(
        root,
        "migrations/versions/0001_base.py",
        "revision = 'r1'\ndown_revision = None\n",
    )
    _write(
        root,
        "migrations/versions/0002_next.py",
        "revision: str = 'r2'\ndown_revision = 'r1'\n",
    )
    _write(
        root,
        "db/startup.py",
        "async def lifespan(app):\n"
        "    initialize()\n"
        "    yield\n\n"
        "def initialize():\n"
        "    try:\n"
        "        Base.metadata.create_all(bind=engine)\n"
        "    except Exception:\n"
        "        pass\n",
    )
    _write(
        root,
        "db/models.py",
        "class Account(Base):\n"
        "    __tablename__ = 'account'\n\n"
        "class Event(models.Model):\n"
        "    pass\n",
    )
    _write(
        root,
        "db/schema.sql",
        "CREATE TABLE account (id INTEGER);\n"
        "create table audit_event (id INTEGER);\n",
    )
    _write(
        root,
        ".github/workflows/migrate.yml",
        "steps:\n  - run: alembic upgrade head\n  - run: alembic check\n",
    )
    _write(root, "CLAUDE.md", "shared instruction\nclaude only\n")
    _write(root, "AGENTS.md", "shared instruction\nagents only\n")
    return root


def build_profile_tree(root: Path) -> Path:
    """Build the large synthetic tree described by the S55 performance brief."""
    root.mkdir(parents=True, exist_ok=True)
    php_template = (
        "<section>template</section>\n<?php\n"
        "$text = 'function ignored() {{}}';\n"
        "$doc = <<<TXT\nfunction ignored_too() {{}}\nTXT;\n"
        "function real_{index}() {{ return {index}; }}\n?>\n"
    )
    for index in range(2000):
        target = (
            400 * 1024
            if index % 100 == 99
            else 5 * 1024 + (index % 16) * 1024
        )
        content = php_template.format(index=index)
        content += ("$value += 1;\n" * ((target - len(content)) // 13 + 1))
        _write(root, f"php/module_{index:04d}.php", content[:target])

    workflow = json.dumps(
        {
            "nodes": [
                {
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "https://example.invalid/hook"},
                }
            ],
            "connections": {},
        },
        sort_keys=True,
    )
    for index in range(5000):
        target = (
            2 * 1024 * 1024
            if index % 250 == 249
            else 5 * 1024 + (index % 32) * 4 * 1024
        )
        if index < 1000:
            content = workflow[:-1] + ', "padding": "' + "x" * max(0, target - len(workflow) - 16) + '"}'
        else:
            content = json.dumps({"payload": "x" * max(0, target - 20)})
        _write(root, f"json/export_{index:04d}.json", content)

    for index in range(500):
        month = index % 12 + 1
        day = index % 28 + 1
        loader = (
            "import importlib\n"
            "VALUE = importlib.import_module('json')\n"
            if index % 25 == 0
            else f"VALUE = {index}\n"
        )
        _write(
            root,
            f"jobs/task_2026{month:02d}{day:02d}_{index:04d}.py",
            loader + "if __name__ == '__main__':\n    print(VALUE)\n",
        )

    _write(root, "alembic.ini", "[alembic]\nscript_location = migrations\n")
    for index in range(100):
        previous = "None" if index == 0 else repr(f"r{index - 1}")
        _write(
            root,
            f"migrations/versions/{index:04d}_revision.py",
            f"revision = 'r{index}'\ndown_revision = {previous}\n",
        )
    for index in range(50):
        _write(
            root,
            f"sql/schema_{index:03d}.sql",
            f"CREATE TABLE table_{index} (id INTEGER);\n",
        )
    return root
