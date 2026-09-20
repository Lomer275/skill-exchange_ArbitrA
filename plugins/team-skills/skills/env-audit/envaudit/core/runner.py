from collections.abc import Iterator
from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time


GIT_SAFE_CONFIG = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.quotepath=off",
)
GIT_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}


@dataclass(frozen=True)
class RunResult:
    rc: int | None
    stdout: bytes
    timed_out: bool
    error_kind: str | None


def _environment(env_extra: dict[str, str] | None) -> dict[str, str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return env


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def run(
    cmd: list[str],
    *,
    timeout: float = 30,
    cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> RunResult:
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=_environment(env_extra),
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        return RunResult(None, b"", False, "not_found")
    except OSError:
        return RunResult(None, b"", False, "os_error")

    try:
        stdout, _ = process.communicate(input=input_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        stdout, _ = process.communicate()
        return RunResult(None, stdout, True, "timeout")
    except BaseException:
        _kill_process_group(process)
        process.communicate()
        raise
    return RunResult(process.returncode, stdout, False, None)


def stream_lines(
    cmd: list[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> Iterator[bytes]:
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=_environment(env_extra),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return

    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    pending = b""
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_process_group(process)
                break
            events = selector.select(remaining)
            if not events:
                _kill_process_group(process)
                break
            chunk = os.read(process.stdout.fileno(), 64 * 1024)
            if not chunk:
                break
            pending += chunk
            parts = pending.splitlines(keepends=True)
            if parts and not parts[-1].endswith((b"\n", b"\r")):
                pending = parts.pop()
            else:
                pending = b""
            yield from parts
        if pending:
            yield pending
    finally:
        selector.close()
        if process.poll() is None:
            _kill_process_group(process)
        process.wait()
        process.stdout.close()


def git(repo: Path, *args: str, timeout: float = 30) -> RunResult:
    return run(
        ["git", *GIT_SAFE_CONFIG, "-C", str(repo), *args],
        timeout=timeout,
        env_extra=GIT_ENV,
    )


def git_stream(repo: Path, *args: str, timeout: float = 600) -> Iterator[bytes]:
    return stream_lines(
        ["git", *GIT_SAFE_CONFIG, "-C", str(repo), *args],
        timeout=timeout,
        env_extra=GIT_ENV,
    )


def is_git_repo(path: Path) -> bool:
    result = git(path, "rev-parse", "--is-inside-work-tree")
    return result.rc == 0 and result.stdout.strip() == b"true"


def which(name: str) -> str | None:
    return shutil.which(name)
