import json
import os
from pathlib import Path
import re
import stat

from envaudit.core import runner
from envaudit.core.context import Context
from envaudit.core.walk import iter_files, read_limited
from envaudit.net.definitions import load


NAME = "onepassword"
ORDER = 70
_TEMPLATE = re.compile(r"(?:example|sample|template|dist)", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    rb"^(?:export\s+)?[A-Za-z_][A-Za-z0-9_.-]*\s*=\s*(.*)$"
)


def _empty_env_counts() -> dict:
    return {
        "total": 0,
        "templates": 0,
        "with_values": 0,
        "op_refs_only": 0,
        "mixed": 0,
        "mode_wider_than_600_with_values": 0,
        "by_root": {},
    }


def _is_env_file(path: Path) -> bool:
    name = path.name
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def _value_kinds(content: bytes) -> tuple[bool, bool]:
    has_reference = False
    has_value = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(b"#"):
            continue
        match = _ASSIGNMENT.match(stripped)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {b"'", b'"'}:
            value = value[1:-1].strip()
        if not value:
            continue
        if value.startswith(b"op://"):
            has_reference = True
        else:
            has_value = True
    return has_reference, has_value


def _env_counts(ctx: Context) -> dict:
    totals = _empty_env_counts()
    limit = ctx.flags.max_text_mb * 1024 * 1024
    for root in ctx.roots:
        root_counts = {
            "total": 0,
            "with_values": 0,
            "op_refs_only": 0,
            "mixed": 0,
        }
        totals["by_root"][str(root)] = root_counts
        for entry in iter_files(root, ctx, NAME, max_depth=3):
            if not _is_env_file(entry.path):
                continue
            totals["total"] += 1
            root_counts["total"] += 1
            if _TEMPLATE.search(entry.path.name):
                totals["templates"] += 1
                continue
            content = read_limited(entry, limit)
            if content is None:
                continue
            has_reference, has_value = _value_kinds(content)
            if has_reference and has_value:
                category = "mixed"
            elif has_reference:
                category = "op_refs_only"
            elif has_value:
                category = "with_values"
            else:
                continue
            totals[category] += 1
            root_counts[category] += 1
            if has_value:
                try:
                    mode = stat.S_IMODE(entry.path.lstat().st_mode)
                except OSError:
                    continue
                if mode & ~0o600:
                    totals["mode_wider_than_600_with_values"] += 1
    return totals


def _base(service_account_env: bool, env_files: dict) -> dict:
    return {
        "op_path": None,
        "op_version": None,
        "signed_in": None,
        "signed_in_reason": "not_installed",
        "vaults_count": None,
        "team_vault_present": None,
        "team_vault_source": "none",
        "service_account_env": service_account_env,
        "env_files": env_files,
    }


def collect(ctx: Context) -> dict:
    definitions = load(ctx.home)
    result = _base("OP_SERVICE_ACCOUNT_TOKEN" in os.environ, _env_counts(ctx))
    result["team_vault_source"] = (
        "definitions" if definitions.team_vault_names else "none"
    )
    executable = runner.which("op")
    if executable is None:
        return result
    result["op_path"] = executable

    version = runner.run([executable, "--version"], timeout=10)
    if version.rc == 0:
        result["op_version"] = version.stdout.decode(
            "utf-8", errors="replace"
        ).strip().splitlines()[0] if version.stdout.strip() else None

    whoami = runner.run(
        [executable, "whoami", "--format=json"],
        timeout=10,
        env_extra={"OP_BIOMETRIC_UNLOCK_ENABLED": "false"},
    )
    if whoami.timed_out:
        result["signed_in_reason"] = "timeout"
        return result
    if whoami.rc != 0:
        result["signed_in_reason"] = "not_confirmed"
        return result
    result["signed_in"] = True
    result["signed_in_reason"] = "ok"

    vaults = runner.run(
        [executable, "vault", "list", "--format=json"], timeout=10
    )
    if vaults.rc != 0:
        return result
    try:
        document = json.loads(vaults.stdout)
    except (UnicodeError, json.JSONDecodeError):
        return result
    if not isinstance(document, list):
        return result
    names = {
        item["name"].casefold()
        for item in document
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    result["vaults_count"] = len(document)
    if definitions.team_vault_names:
        result["team_vault_present"] = any(
            name.casefold() in names for name in definitions.team_vault_names
        )
    return result
