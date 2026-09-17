from concurrent.futures import ThreadPoolExecutor
import os
import pwd

from envaudit.core.context import Context
from envaudit.net.definitions import DEFINITIONS_PATH, load
from envaudit.net.probe import TcpResult, tcp_probe
from envaudit.net import sshlocal


NAME = "network"
ORDER = 75


def _tcp_view(name: str, host: str, port: int, result: TcpResult) -> dict:
    return {
        "name": name,
        "host": host,
        "port": port,
        "status": result.status,
        "dns_ms": result.dns_ms,
        "median_ms": result.median_ms,
        "attempts": result.attempts,
        "ok": result.ok,
    }


def _must_reach(item: tuple[str, str, int]) -> dict:
    name, host, port = item
    return _tcp_view(name, host, port, tcp_probe(host, port))


def _restricted_target(host: str, port: int, ctx: Context) -> dict:
    result = tcp_probe(host, port, attempts=1)
    target = {
        "host": host,
        "port": port,
        "tcp": result.status,
        "ssh_aliases": None,
        "known_hosts_entry": None,
        "host_key_matches_known": None,
        "access_possible_unconfirmed": None,
    }
    if result.status != "open":
        return target

    aliases = sshlocal.ssh_config_aliases_for(host, ctx)
    known = sshlocal.known_hosts_has(host, port, ctx.home)
    target["ssh_aliases"] = aliases
    target["known_hosts_entry"] = known
    scanned = sshlocal.keyscan_fingerprints(host, port)
    recorded = sshlocal.known_fingerprints(host, port, ctx.home) if known else []
    if scanned and recorded:
        target["host_key_matches_known"] = bool(set(scanned) & set(recorded))
    has_key = any(item["identity_files_existing"] > 0 for item in aliases)
    if not has_key:
        has_key = sshlocal.any_private_key(ctx.home)
    target["access_possible_unconfirmed"] = bool(
        (aliases or known) and has_key
    )
    return target


def _ssh_host(view: dict, home) -> dict:
    hostname = view["hostname"]
    port = view["port"]
    scanned = sshlocal.keyscan_fingerprints(hostname, port)
    if scanned:
        keyscan = "ok"
    elif scanned is None:
        keyscan = "timeout"
    else:
        tcp_status = tcp_probe(hostname, port, attempts=1, timeout=8).status
        keyscan = "dns_fail" if tcp_status == "dns_fail" else (
            "timeout" if tcp_status == "timeout" else "refused"
        )
    known = sshlocal.known_fingerprints(hostname, port, home)
    local = sshlocal.local_host_fingerprints()
    return {
        "alias": view["alias"],
        "hostname": hostname,
        "port": port,
        "keyscan": keyscan,
        "host_key_matches_known": (
            bool(set(scanned) & set(known)) if scanned and known else None
        ),
        "points_to_local_machine": (
            bool(set(scanned) & set(local)) if scanned and local else None
        ),
    }


def collect(ctx: Context) -> dict:
    definitions = load(ctx.home)
    with ThreadPoolExecutor(max_workers=max(1, len(definitions.must_reach))) as pool:
        must_reach = list(pool.map(_must_reach, definitions.must_reach))

    if definitions.source == "builtin":
        ctx.skip(NAME, "no_definitions")
        restricted = []
    else:
        shared_host = ctx.shared.get("host", {})
        user = (
            shared_host.get("user")
            if isinstance(shared_host, dict)
            else None
        ) or pwd.getpwuid(os.geteuid()).pw_name
        grants = definitions.granted.get(user, [])
        restricted = [
            {
                "name": item["name"],
                "kind": item["kind"],
                "granted": item["name"] in grants,
                "targets": [
                    _restricted_target(host, port, ctx)
                    for host in item["hosts"]
                    for port in item["ports"]
                ],
            }
            for item in definitions.restricted
        ]

    ssh_hosts = [
        _ssh_host(view, ctx.home) for view in sshlocal.ssh_hosts(ctx)
    ]
    return {
        "definitions": {
            "source": definitions.source,
            "version": definitions.version,
            "path": DEFINITIONS_PATH,
        },
        "must_reach": must_reach,
        "restricted": restricted,
        "ssh_hosts": ssh_hosts,
    }
