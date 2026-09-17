import json
import os
from pathlib import Path
import pwd
import pytest
import socket
import time

from envaudit.core.context import Context, Flags
from envaudit.core.runner import RunResult
from envaudit.net.probe import TcpResult, tcp_probe
from envaudit.sections import network


def _context(home: Path) -> Context:
    started = time.time()
    ctx = Context(
        flags=Flags(),
        home=home,
        roots=[home],
        started_at=started,
        deadline=started + 300,
    )
    ctx.shared["host"] = {"user": pwd.getpwuid(os.geteuid()).pw_name}
    return ctx


def _result(status: str, attempts: int = 1) -> TcpResult:
    return TcpResult(
        status != "dns_fail",
        0.1 if status != "dns_fail" else None,
        "ipv4" if status != "dns_fail" else None,
        attempts,
        1 if status == "open" else 0,
        0.2 if status == "open" else None,
        status,
    )


def _definitions(home: Path, *, granted: bool = False, port: int = 22) -> None:
    name = "prod"
    user = pwd.getpwuid(os.geteuid()).pw_name
    path = home / ".config" / "env-audit" / "network.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": "test",
                "must_reach": [],
                "restricted": [
                    {
                        "name": name,
                        "kind": "prod",
                        "hosts": ["127.0.0.1"],
                        "ports": [port],
                    }
                ],
                "granted": {user: [name]} if granted else {},
                "team_vault_names": [],
            }
        ),
        encoding="utf-8",
    )


def _ssh_config(home: Path) -> None:
    ssh = home / ".ssh"
    ssh.mkdir(parents=True)
    (ssh / "config").write_text(
        "Host prod\n  HostName 127.0.0.1\n  IdentityFile ~/.ssh/id_x\n",
        encoding="utf-8",
    )
    (ssh / "id_x").write_bytes(b"not-a-real-key")


def _ssh_g(command, **kwargs):
    if command[:2] == ["ssh", "-G"]:
        return RunResult(
            0,
            b"hostname 127.0.0.1\nuser root\nport 22\nidentityfile ~/.ssh/id_x\n",
            False,
            None,
        )
    return RunResult(1, b"", False, None)


def test_tcp_probe_open_closed():
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except PermissionError:
        pytest.skip("the test sandbox forbids creating local sockets")
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    try:
        opened = tcp_probe("127.0.0.1", port, attempts=1, timeout=1)
    finally:
        listener.close()
    closed = tcp_probe("127.0.0.1", port, attempts=1, timeout=1)
    assert opened.status == "open"
    assert isinstance(opened.median_ms, float)
    assert closed.status == "closed"


def test_no_definitions_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        network,
        "tcp_probe",
        lambda host, port, **kwargs: _result("open", kwargs.get("attempts", 3)),
    )
    ctx = _context(tmp_path)
    result = network.collect(ctx)
    assert result["restricted"] == []
    assert len(result["must_reach"]) == 7
    assert {"section": "network", "reason": "no_definitions", "details": None} in ctx.skipped


def test_restricted_access_possible(tmp_path, monkeypatch):
    _definitions(tmp_path)
    _ssh_config(tmp_path)
    monkeypatch.setattr(network, "tcp_probe", lambda *args, **kwargs: _result("open"))
    monkeypatch.setattr(network.sshlocal.runner, "run", _ssh_g)
    monkeypatch.setattr(network.sshlocal, "known_hosts_has", lambda *args: False)
    monkeypatch.setattr(network.sshlocal, "keyscan_fingerprints", lambda *args: None)
    result = network.collect(_context(tmp_path))
    restricted = result["restricted"][0]
    assert restricted["granted"] is False
    assert restricted["targets"][0]["access_possible_unconfirmed"] is True


def test_granted_user(tmp_path, monkeypatch):
    _definitions(tmp_path, granted=True)
    monkeypatch.setattr(network, "tcp_probe", lambda *args, **kwargs: _result("closed"))
    result = network.collect(_context(tmp_path))
    assert result["restricted"][0]["granted"] is True


def test_never_ssh_login(tmp_path, monkeypatch):
    _definitions(tmp_path)
    _ssh_config(tmp_path)
    calls = []

    def intercepted(command, **kwargs):
        calls.append(command)
        return _ssh_g(command, **kwargs)

    monkeypatch.setattr(network, "tcp_probe", lambda *args, **kwargs: _result("open"))
    monkeypatch.setattr(network.sshlocal.runner, "run", intercepted)
    network.collect(_context(tmp_path))
    assert all(command[:2] == ["ssh", "-G"] for command in calls if command[0] == "ssh")
    assert not any(command[0] in {"scp", "sftp", "ssh-copy-id"} for command in calls)


def test_closed_port_not_measured(tmp_path, monkeypatch):
    _definitions(tmp_path)
    monkeypatch.setattr(network, "tcp_probe", lambda *args, **kwargs: _result("closed"))

    def unexpected(*args, **kwargs):
        raise AssertionError("SSH metadata must not be checked for a closed port")

    monkeypatch.setattr(network.sshlocal, "ssh_config_aliases_for", unexpected)
    result = network.collect(_context(tmp_path))
    target = result["restricted"][0]["targets"][0]
    assert target["access_possible_unconfirmed"] is None


def test_ssh_hosts_points_to_local(tmp_path, monkeypatch):
    _ssh_config(tmp_path)
    monkeypatch.setattr(network, "tcp_probe", lambda *args, **kwargs: _result("open"))
    monkeypatch.setattr(network.sshlocal.runner, "run", _ssh_g)
    monkeypatch.setattr(
        network.sshlocal, "keyscan_fingerprints", lambda *args: ["SHA256:local"]
    )
    monkeypatch.setattr(
        network.sshlocal, "known_fingerprints", lambda *args: ["SHA256:recorded"]
    )
    monkeypatch.setattr(
        network.sshlocal, "local_host_fingerprints", lambda: ["SHA256:local"]
    )
    result = network.collect(_context(tmp_path))
    host = result["ssh_hosts"][0]
    assert host["points_to_local_machine"] is True
    assert host["host_key_matches_known"] is False
