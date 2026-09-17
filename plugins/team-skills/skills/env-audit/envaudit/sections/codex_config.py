import os
from pathlib import Path
import re
import stat

from envaudit.core import runner
from envaudit.core.context import Context


NAME = "codex_config"
ORDER = 65
_KEYS = ("model", "approval_policy", "sandbox_mode", "model_reasoning_effort")
_KEY = re.compile(
    r'^\s*(model|approval_policy|sandbox_mode|model_reasoning_effort)\s*=\s*"([^"]*)"'
)
_SECTION = re.compile(r"^\s*\[([^]]+)]")
_NETWORK = re.compile(r"^\s*network_access\s*=\s*(true|false)\b", re.IGNORECASE)


def _display(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _empty_values() -> dict[str, str | None]:
    return {key: None for key in _KEYS}


def _parse_config(text: str) -> tuple[dict, dict, bool | None]:
    top = _empty_values()
    profiles: dict[str, dict] = {}
    current: tuple[str, str | None] = ("top", None)
    network_access = None
    for line in text.splitlines():
        section = _SECTION.match(line)
        if section:
            name = section.group(1)
            if name.startswith("profiles.") and len(name) > len("profiles."):
                profile = name[len("profiles."):]
                profiles.setdefault(profile, _empty_values())
                current = ("profile", profile)
            elif name == "sandbox_workspace_write":
                current = ("sandbox", None)
            else:
                current = ("other", None)
            continue
        if current[0] == "sandbox":
            match = _NETWORK.match(line)
            if match:
                network_access = match.group(1).lower() == "true"
            continue
        match = _KEY.match(line)
        if not match:
            continue
        key, value = match.groups()
        if current[0] == "top":
            top[key] = value
        elif current[0] == "profile" and current[1] is not None:
            profiles[current[1]][key] = value
    return top, profiles, network_access


def _version(ctx: Context) -> str | None:
    host = ctx.shared.get("host", {})
    if isinstance(host, dict) and host.get("codex_version") is not None:
        value = host["codex_version"]
        return value if isinstance(value, str) else None
    result = runner.run(["codex", "--version"], timeout=15)
    if result.rc != 0:
        return None
    match = re.search(rb"\d+\.\d+\.\d+", result.stdout)
    return match.group(0).decode("ascii") if match else None


def collect(ctx: Context) -> dict:
    host = ctx.shared.get("host", {})
    raw_home = host.get("codex_home") if isinstance(host, dict) else None
    codex_home = Path(raw_home) if isinstance(raw_home, str) else Path(
        os.environ.get("CODEX_HOME", str(ctx.home / ".codex"))
    )
    codex_home = Path(os.path.realpath(codex_home.expanduser()))
    display_home = _display(codex_home, ctx.home)
    if not codex_home.is_dir():
        ctx.skip(NAME, "not_applicable")
        return {"codex_home": display_home, "config_exists": False}

    config_path = codex_home / "config.toml"
    config_exists = config_path.is_file()
    text = ""
    config_mode = None
    owner_is_user = None
    if config_exists:
        try:
            info = os.stat(config_path)
            config_mode = f"{stat.S_IMODE(info.st_mode):04o}"
            owner_is_user = info.st_uid == os.getuid()
            text = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    top, profiles, network_access = _parse_config(text)

    agents_path = codex_home / "AGENTS.md"
    agents_exists = agents_path.is_file()
    agents_bytes = None
    blocks = None
    if agents_exists:
        try:
            agents_bytes = agents_path.stat().st_size
            blocks = sum(
                "BEGIN team-context" in line
                for line in agents_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            )
        except OSError:
            pass
    return {
        "codex_home": display_home,
        "config_exists": config_exists,
        "config_mode": config_mode,
        "config_owner_is_user": owner_is_user,
        "top": top,
        "profiles": profiles,
        "sandbox_workspace_write_network_access": network_access,
        "danger_full_access_anywhere": any(
            values.get("sandbox_mode") == "danger-full-access"
            for values in [top, *profiles.values()]
        ),
        "global_agents_md": {
            "exists": agents_exists,
            "bytes": agents_bytes,
            "team_context_blocks": blocks,
        },
        "codex_version": _version(ctx),
    }
