from hashlib import sha1
import json
import os
from pathlib import Path


EMPTY_SHA1 = sha1(b"").hexdigest()


def sha1_bytes(data: bytes) -> str:
    return sha1(data).hexdigest()


def file_sha1(path: Path) -> str | None:
    try:
        return sha1_bytes(path.read_bytes())
    except OSError:
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write_private(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        mode = "wb" if isinstance(data, bytes) else "w"
        kwargs = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
        with os.fdopen(descriptor, mode, **kwargs) as stream:
            descriptor = -1
            stream.write(data)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
