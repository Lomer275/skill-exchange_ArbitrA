import json
from pathlib import Path

from envaudit.core.context import Context


def _read_object(path: Path, ctx: Context, error_kind: str) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        ctx.error("machine", error_kind)
        return None
    if not isinstance(value, dict):
        ctx.error("machine", error_kind)
        return None
    return value


def _names(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(key for key in value if isinstance(key, str))


def collect_claude_settings(ctx: Context) -> dict:
    claude_dir = ctx.home / ".claude"
    path = claude_dir / "settings.json"
    backups = set()
    for pattern in ("*.bak*", "settings.json.*"):
        try:
            backups.update(
                item.name for item in claude_dir.glob(pattern) if item.is_file()
            )
        except OSError:
            pass

    document = _read_object(path, ctx, "settings_parse")
    if document is None:
        return {
            "exists": path.is_file(),
            "allow_rules": None,
            "deny_rules": None,
            "default_mode": None,
            "model": None,
            "env_keys": [],
            "enabled_plugins": 0,
            "backups": sorted(backups),
        }

    permissions = document.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    allow = permissions.get("allow")
    deny = permissions.get("deny")
    env = document.get("env")
    plugins = document.get("enabledPlugins")
    default_mode = permissions.get("defaultMode")
    model = document.get("model")
    return {
        "exists": True,
        "allow_rules": len(allow) if isinstance(allow, list) else 0,
        "deny_rules": len(deny) if isinstance(deny, list) else 0,
        "default_mode": default_mode if isinstance(default_mode, str) else None,
        "model": model if isinstance(model, str) else None,
        "env_keys": _names(env),
        "enabled_plugins": (
            sum(value is True for value in plugins.values())
            if isinstance(plugins, dict)
            else 0
        ),
        "backups": sorted(backups),
    }


def collect_declared_mcp(ctx: Context) -> dict:
    user_names: set[str] = set()
    project_names: dict[str, set[str]] = {}

    claude_config = _read_object(ctx.home / ".claude.json", ctx, "mcp_config_parse")
    if claude_config is not None:
        user_names.update(_names(claude_config.get("mcpServers")))
        projects = claude_config.get("projects")
        if isinstance(projects, dict):
            for root, project in projects.items():
                if not isinstance(root, str) or not isinstance(project, dict):
                    continue
                names = _names(project.get("mcpServers"))
                if names:
                    project_names.setdefault(root, set()).update(names)

    mcp_config = _read_object(ctx.home / ".mcp.json", ctx, "mcp_config_parse")
    if mcp_config is not None:
        user_names.update(_names(mcp_config.get("mcpServers")))

    for root in ctx.roots:
        root_config = _read_object(root / ".mcp.json", ctx, "mcp_config_parse")
        if root_config is None:
            continue
        names = _names(root_config.get("mcpServers"))
        if names:
            project_names.setdefault(str(root), set()).update(names)

    return {
        "user": sorted(user_names),
        "projects": {
            root: sorted(names) for root, names in sorted(project_names.items())
        },
    }
