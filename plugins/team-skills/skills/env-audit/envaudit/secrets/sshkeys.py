import base64
from pathlib import Path
import stat

from envaudit.core import osinfo
from envaudit.core.runner import run, which


def _key_type(header: bytes) -> str:
    if b"OPENSSH" in header:
        return "OPENSSH"
    for name in (b"RSA", b"EC", b"DSA"):
        if name in header:
            return name.decode("ascii")
    return "UNKNOWN"


def _openssh_encrypted(data: bytes) -> bool | None:
    try:
        lines = data.splitlines()
        body = b"".join(lines[1:-1])
        decoded = base64.b64decode(body, validate=True)
        magic = b"openssh-key-v1" + bytes((0,))
        if not decoded.startswith(magic):
            return None
        offset = len(magic)
        size = int.from_bytes(decoded[offset : offset + 4], "big")
        offset += 4
        if size < 1 or offset + size > len(decoded):
            return None
        return decoded[offset : offset + size] != b"none"
    except (ValueError, IndexError):
        return None


def _encrypted(data: bytes, key_type: str) -> bool | None:
    if key_type == "OPENSSH":
        return _openssh_encrypted(data)
    if b"ENCRYPTED PRIVATE KEY" in data or b"Proc-Type: 4,ENCRYPTED" in data:
        return True
    if key_type in {"RSA", "EC", "DSA"}:
        return False
    return None


def _passphrase(path: Path) -> bool | str:
    executable = which("ssh-keygen")
    if executable is None:
        return "not_checked"
    result = run(
        [executable, "-y", "-P", "", "-f", str(path)],
        timeout=15,
    )
    if result.rc is None:
        return "not_checked"
    return result.rc != 0


def key_info(path: Path, data: bytes | None = None) -> dict:
    windows = osinfo.is_windows()
    mode = None if windows else stat.S_IMODE(path.stat().st_mode)
    if data is None:
        data = path.read_bytes()
    header = data.splitlines()[0] if data else b""
    key_type = _key_type(header)
    result = {
        "file": str(path),
        "type": key_type,
        "mode": None if mode is None else f"{mode:04o}",
        "wider_than_600": None if mode is None else bool(mode & 0o077),
        "encrypted": _encrypted(data, key_type),
        "passphrase": _passphrase(path),
    }
    if windows:
        result["acl"] = "not_checked"
    return result
