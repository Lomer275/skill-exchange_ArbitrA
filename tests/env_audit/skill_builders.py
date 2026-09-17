import json
from pathlib import Path


def write_skill(
    base: Path,
    name: str,
    *,
    description: str = "English description",
    when_to_use: str | None = None,
) -> Path:
    path = base / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"name: {name}", f"description: {description}"]
    if when_to_use is not None:
        lines.append(f"when_to_use: {when_to_use}")
    lines.extend(("---", "Body must not affect the index."))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_command(
    base: Path,
    name: str,
    *,
    description: str = "English command",
) -> Path:
    path = base / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nCommand body.\n",
        encoding="utf-8",
    )
    return path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def install_plugin(
    home: Path,
    install_path: Path,
    key: str,
    names: list[str],
    *,
    version: str = "1.3.0",
    enabled: bool = True,
) -> None:
    for name in names:
        write_skill(install_path / "skills", name)
    installed_path = home / ".claude" / "plugins" / "installed_plugins.json"
    try:
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        installed = {"plugins": {}}
    installed.setdefault("plugins", {})[key] = [
        {"installPath": str(install_path), "version": version, "scope": "user"}
    ]
    write_json(installed_path, installed)

    settings_path = home / ".claude" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings = {}
    settings.setdefault("enabledPlugins", {})[key] = enabled
    write_json(settings_path, settings)


def write_settings(home: Path, value: dict) -> None:
    path = home / ".claude" / "settings.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {}
    current.update(value)
    write_json(path, current)


def write_memory(home: Path, name: str, *, cards: int = 1, index: str = "index\n") -> Path:
    memory = home / ".claude" / "projects" / name / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    for number in range(cards):
        (memory / f"card-{number}.md").write_text("card\n", encoding="utf-8")
    (memory / "MEMORY.md").write_text(index, encoding="utf-8")
    return memory
