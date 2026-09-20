from dataclasses import dataclass
import json
from pathlib import Path


DEFINITIONS_PATH = "~/.config/env-audit/network.json"
PUBLIC_MUST_REACH = (
    ("GitHub", "github.com", 443),
    ("GitHub SSH over 443", "ssh.github.com", 443),
    ("Anthropic API", "api.anthropic.com", 443),
    ("OpenAI API", "api.openai.com", 443),
    ("ChatGPT (Codex login)", "chatgpt.com", 443),
    ("PyPI", "pypi.org", 443),
    ("npm", "registry.npmjs.org", 443),
)


@dataclass
class Definitions:
    version: str | None
    must_reach: list[tuple[str, str, int]]
    restricted: list[dict]
    granted: dict[str, list[str]]
    team_vault_names: list[str]
    source: str


def _must_reach(value: object) -> list[tuple[str, str, int]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, dict):
            name, host, port = item.get("name"), item.get("host"), item.get("port")
        elif isinstance(item, list) and len(item) == 3:
            name, host, port = item
        else:
            continue
        if (
            isinstance(name, str)
            and isinstance(host, str)
            and isinstance(port, int)
            and 0 < port < 65536
        ):
            result.append((name, host, port))
    return result


def _restricted(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        kind = item.get("kind")
        hosts = item.get("hosts")
        ports = item.get("ports")
        if (
            isinstance(name, str)
            and kind in {"prod", "team_machine"}
            and isinstance(hosts, list)
            and all(isinstance(host, str) for host in hosts)
            and isinstance(ports, list)
            and all(isinstance(port, int) and 0 < port < 65536 for port in ports)
        ):
            result.append(
                {"name": name, "kind": kind, "hosts": hosts, "ports": ports}
            )
    return result


def _granted(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {
        user: names
        for user, names in value.items()
        if isinstance(user, str)
        and isinstance(names, list)
        and all(isinstance(name, str) for name in names)
    }


def load(home: Path) -> Definitions:
    path = home / ".config" / "env-audit" / "network.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return Definitions(None, list(PUBLIC_MUST_REACH), [], {}, [], "builtin")
    if not isinstance(document, dict):
        return Definitions(None, list(PUBLIC_MUST_REACH), [], {}, [], "builtin")

    version = document.get("version")
    vault_names = document.get("team_vault_names")
    return Definitions(
        version=version if isinstance(version, str) else None,
        must_reach=_must_reach(document.get("must_reach")),
        restricted=_restricted(document.get("restricted")),
        granted=_granted(document.get("granted")),
        team_vault_names=(
            [name for name in vault_names if isinstance(name, str)]
            if isinstance(vault_names, list)
            else []
        ),
        source="file",
    )
