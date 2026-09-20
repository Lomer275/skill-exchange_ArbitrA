from pathlib import Path


CGROUP_ROOT = Path("/sys/fs/cgroup")
SYSTEMD_SYSTEM_ROOT = Path("/etc/systemd/system")
_INITIAL_CGROUP_ROOT = CGROUP_ROOT


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return None


def _limit_mb(value: str | None) -> int | None:
    if value is None or value == "max":
        return None
    try:
        return int(value) // (1024 * 1024)
    except ValueError:
        return None


def _integer_limit(value: str | None) -> int | None:
    if value is None or value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _events(value: str | None) -> dict[str, int | None]:
    parsed = {"high": None, "max": None, "oom_kill": None}
    if value is None:
        return parsed
    for line in value.splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[0] not in parsed:
            continue
        try:
            parsed[fields[0]] = int(fields[1])
        except ValueError:
            pass
    return parsed


def _dropins() -> list[str]:
    names = []
    for directory_name in ("user-.slice.d", "user@.service.d"):
        directory = SYSTEMD_SYSTEM_ROOT / directory_name
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        names.extend(
            f"{directory_name}/{path.name}"
            for path in entries
            if path.is_file()
        )
    return sorted(names)


def user_slice_limits(uid: int, cgroup_root: Path = CGROUP_ROOT) -> dict:
    if cgroup_root == _INITIAL_CGROUP_ROOT and CGROUP_ROOT != _INITIAL_CGROUP_ROOT:
        cgroup_root = CGROUP_ROOT
    user_slice = cgroup_root / "user.slice" / f"user-{uid}.slice"
    events = _events(_read(user_slice / "memory.events.local"))
    return {
        "memory_max_mb": _limit_mb(_read(user_slice / "memory.max")),
        "memory_high_mb": _limit_mb(_read(user_slice / "memory.high")),
        "cpu_max": _read(user_slice / "cpu.max"),
        "pids_max": _integer_limit(_read(user_slice / "pids.max")),
        "events_high": events["high"],
        "events_max": events["max"],
        "oom_kill": events["oom_kill"],
        "dropins": _dropins(),
    }
