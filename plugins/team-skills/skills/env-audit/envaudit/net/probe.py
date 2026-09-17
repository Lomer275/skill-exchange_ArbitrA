from dataclasses import dataclass
import errno
import socket
import statistics
import time


@dataclass(frozen=True)
class TcpResult:
    dns_ok: bool
    dns_ms: float | None
    addr_family: str | None
    attempts: int
    ok: int
    median_ms: float | None
    status: str


def _family_name(family: int) -> str:
    if family == socket.AF_INET:
        return "ipv4"
    if family == socket.AF_INET6:
        return "ipv6"
    return str(family)


def tcp_probe(
    host: str, port: int, *, attempts: int = 3, timeout: float = 5.0
) -> TcpResult:
    dns_started = time.perf_counter()
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror):
        return TcpResult(False, None, None, attempts, 0, None, "dns_fail")
    dns_ms = round((time.perf_counter() - dns_started) * 1000, 3)
    if not addresses:
        return TcpResult(False, dns_ms, None, attempts, 0, None, "dns_fail")

    family, socktype, protocol, _, address = addresses[0]
    elapsed = []
    refused = False
    for _ in range(attempts):
        try:
            connection = socket.socket(family, socktype, protocol)
            connection.settimeout(timeout)
        except OSError as error:
            refused = refused or error.errno == errno.ECONNREFUSED
            continue
        started = time.perf_counter()
        try:
            connection.connect(address)
            elapsed.append((time.perf_counter() - started) * 1000)
        except OSError as error:
            refused = refused or error.errno == errno.ECONNREFUSED
        finally:
            connection.close()

    if elapsed:
        status = "open"
        median_ms = round(statistics.median(elapsed), 3)
    else:
        status = "closed" if refused else "timeout"
        median_ms = None
    return TcpResult(
        True,
        dns_ms,
        _family_name(family),
        attempts,
        len(elapsed),
        median_ms,
        status,
    )
