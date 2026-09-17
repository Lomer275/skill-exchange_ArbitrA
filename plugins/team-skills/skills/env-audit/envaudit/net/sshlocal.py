import os
from pathlib import Path
import re
import socket

from envaudit.core import runner
from envaudit.core.context import Context


_FINGERPRINT = re.compile(rb"\bSHA256:[A-Za-z0-9+/=]+")


def _aliases(home: Path) -> list[str]:
    path = home / ".ssh" / "config"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    result = []
    for line in lines:
        match = re.match(r"\s*Host\s+(.+?)\s*(?:#.*)?$", line, re.IGNORECASE)
        if not match:
            continue
        for alias in match.group(1).split():
            if any(marker in alias for marker in "*?!") or alias in result:
                continue
            result.append(alias)
    return result


def _ssh_view(alias: str) -> dict | None:
    result = runner.run(["ssh", "-G", alias], timeout=10)
    if result.rc != 0:
        return None
    values: dict[str, list[str]] = {}
    for raw_line in result.stdout.decode("utf-8", errors="replace").splitlines():
        key, separator, value = raw_line.partition(" ")
        if separator:
            values.setdefault(key.lower(), []).append(value.strip())
    try:
        port = int(values.get("port", ["22"])[0])
    except ValueError:
        port = 22
    return {
        "alias": alias,
        "hostname": values.get("hostname", [alias])[0],
        "user": values.get("user", [None])[0],
        "port": port,
        "identity_files": values.get("identityfile", []),
    }


def ssh_hosts(ctx: Context) -> list[dict]:
    return [view for alias in _aliases(ctx.home) if (view := _ssh_view(alias))]


def _host_addresses(host: str) -> set[str]:
    try:
        return {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError:
        return set()


def _identity_path(value: str, home: Path) -> Path:
    if value == "~":
        return home
    if value.startswith("~/"):
        return home / value[2:]
    return Path(os.path.expandvars(value))


def ssh_config_aliases_for(host: str, ctx: Context) -> list[dict]:
    addresses = _host_addresses(host)
    matches = []
    for view in ssh_hosts(ctx):
        if view["hostname"] != host and view["hostname"] not in addresses:
            continue
        matches.append(
            {
                "alias": view["alias"],
                "user": view["user"],
                "port": view["port"],
                "identity_files_existing": sum(
                    _identity_path(path, ctx.home).is_file()
                    for path in view["identity_files"]
                ),
            }
        )
    return matches


def _known_query(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def _known_output(host: str, port: int, home: Path) -> bytes | None:
    known_hosts = home / ".ssh" / "known_hosts"
    if not known_hosts.is_file():
        return None
    result = runner.run(
        [
            "ssh-keygen",
            "-F",
            _known_query(host, port),
            "-f",
            str(known_hosts),
        ],
        timeout=10,
    )
    return result.stdout if result.rc == 0 else None


def known_hosts_has(host: str, port: int, home: Path) -> bool:
    return _known_output(host, port, home) is not None


def _fingerprints(key_data: bytes) -> list[str]:
    if not key_data:
        return []
    result = runner.run(
        ["ssh-keygen", "-lf", "-"], timeout=10, input_bytes=key_data
    )
    if result.rc != 0:
        return []
    return sorted(
        {match.group(0).decode("ascii") for match in _FINGERPRINT.finditer(result.stdout)}
    )


def keyscan_fingerprints(host: str, port: int) -> list[str] | None:
    result = runner.run(
        ["ssh-keyscan", "-T", "8", "-p", str(port), host], timeout=10
    )
    if result.timed_out:
        return None
    if result.rc != 0 or not result.stdout:
        return []
    return _fingerprints(result.stdout)


def known_fingerprints(host: str, port: int, home: Path) -> list[str]:
    output = _known_output(host, port, home)
    return _fingerprints(output) if output else []


def local_host_fingerprints() -> list[str]:
    result = set()
    try:
        paths = sorted(Path("/etc/ssh").glob("ssh_host_*_key.pub"))
    except OSError:
        return []
    for path in paths:
        try:
            result.update(_fingerprints(path.read_bytes()))
        except OSError:
            continue
    return sorted(result)


def any_private_key(home: Path) -> bool:
    ssh_dir = home / ".ssh"
    try:
        paths = list(ssh_dir.iterdir())
    except OSError:
        return False
    excluded = {"authorized_keys", "config", "known_hosts", "known_hosts.old"}
    return any(
        path.is_file()
        and not path.is_symlink()
        and path.name not in excluded
        and not path.name.endswith(".pub")
        and (path.name.startswith("id_") or Path(str(path) + ".pub").is_file())
        for path in paths
    )
