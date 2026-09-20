from datetime import date, timedelta
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .items import file_sha1, json_text, secure_directory, write_private
from .plan import PLAN_SCHEMA


APPLY_SCHEMA = "env-audit/cleanup-apply"


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _mkdir_backup(path: Path, backup_root: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    current = path
    while current == backup_root or backup_root in current.parents:
        current.chmod(0o700)
        if current == backup_root:
            break
        current = current.parent


def _canonical_backup(backup_root: Path, target: Path) -> Path:
    return backup_root / str(target.resolve()).lstrip("/")


def _backup(target: Path, backup_root: Path, identifier: str) -> tuple[Path, Path]:
    canonical = _canonical_backup(backup_root, target)
    rollback_copy = canonical
    if canonical.exists():
        rollback_copy = backup_root / ".steps" / identifier / str(target.resolve()).lstrip("/")
    _mkdir_backup(rollback_copy.parent, backup_root)
    shutil.copy2(target, rollback_copy)
    rollback_copy.chmod(0o600)
    if not canonical.exists():
        canonical = rollback_copy
    return canonical, rollback_copy


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=".env-audit-", dir=path.parent)
    temp = Path(raw_temp)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temp.unlink(missing_ok=True)


def _operations(plan_dir: Path, item: dict) -> list[dict]:
    primary = {
        "path": item["path"],
        "artifact": f"after/{item['id']}",
        "before_sha1": item["before_sha1"],
        "after_sha1": item["after_sha1"],
        "created": bool(item.get("before_missing")),
    }
    result = [primary]
    for operation in item.get("related", []):
        if not isinstance(operation, dict):
            continue
        result.append(dict(operation))
    for operation in result:
        artifact = (plan_dir / operation["artifact"]).resolve()
        if plan_dir.resolve() not in artifact.parents:
            raise ValueError("artifact is outside the plan directory")
        operation["artifact_path"] = artifact
    return result


def _is_stale(operation: dict) -> bool:
    path = Path(operation["path"])
    current = file_sha1(path)
    if operation.get("created"):
        return current is not None
    return current != operation.get("before_sha1")


def _restore_file(record: dict) -> None:
    path = Path(record["path"])
    if record["created"]:
        path.unlink(missing_ok=True)
        return
    backup = Path(record["rollback_backup_path"])
    data = backup.read_bytes()
    _atomic_write(path, data, int(record["original_mode"]))


def _apply_item(item: dict, plan_dir: Path, backup_root: Path) -> dict:
    result = {
        "id": item["id"],
        "kind": item["kind"],
        "path": item["path"],
        "status": "stale",
        "backup_path": None,
        "created": bool(item.get("before_missing")),
        "files": [],
    }
    operations = _operations(plan_dir, item)
    if any(_is_stale(operation) for operation in operations):
        return result

    changed = []
    try:
        for index, operation in enumerate(operations):
            target = Path(operation["path"])
            created = bool(operation.get("created"))
            backup_path = None
            rollback_path = None
            original_mode = 0o600
            if not created:
                original_mode = stat.S_IMODE(target.stat().st_mode)
                canonical, rollback_copy = _backup(
                    target, backup_root, f"{item['id']}-{index}"
                )
                backup_path = str(canonical)
                rollback_path = str(rollback_copy)
            data = Path(operation["artifact_path"]).read_bytes()
            _atomic_write(target, data, 0o600 if created else original_mode)
            record = {
                "path": str(target),
                "backup_path": backup_path,
                "rollback_backup_path": rollback_path,
                "created": created,
                "original_mode": original_mode,
                "after_sha1": operation["after_sha1"],
            }
            changed.append(record)
        result["status"] = "applied"
        result["files"] = changed
        if changed:
            result["backup_path"] = changed[0]["backup_path"]
            result["created"] = changed[0]["created"]
    except Exception as error:
        for record in reversed(changed):
            try:
                _restore_file(record)
            except OSError:
                pass
        result["status"] = "error"
        result["error_kind"] = type(error).__name__
        result["files"] = changed
    return result


def apply_plan(plan_path: Path, *, confirmed: bool) -> int:
    if not confirmed:
        return 2
    plan_path = plan_path.resolve()
    plan = _read_json(plan_path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("not a cleanup plan")
    if plan.get("diff_blocked") is True:
        return 3
    home = Path(plan["home"])
    backup_root = home / f"audit-{date.today().isoformat()}" / "backup"
    secure_directory(backup_root.parent)
    secure_directory(backup_root)
    results = []
    for item in sorted(plan.get("items", []), key=lambda value: value.get("id", "")):
        if not isinstance(item, dict) or item.get("selected") is not True or item.get("blocked") is not None:
            continue
        results.append(_apply_item(item, plan_path.parent, backup_root))
    document = {
        "schema": APPLY_SCHEMA,
        "plan_path": str(plan_path),
        "backup_root": str(backup_root),
        "delete_backup_after": (date.today() + timedelta(days=14)).isoformat(),
        "items": results,
    }
    write_private(plan_path.parent / "apply.json", json_text(document))
    return 0


def rollback_plan(plan_path: Path, *, confirmed: bool) -> int:
    if not confirmed:
        return 2
    plan_path = plan_path.resolve()
    apply_path = plan_path.parent / "apply.json"
    applied = _read_json(apply_path)
    if applied.get("schema") != APPLY_SCHEMA:
        raise ValueError("not a cleanup apply result")
    results = []
    for item in reversed(applied.get("items", [])):
        if not isinstance(item, dict) or item.get("status") != "applied":
            continue
        files = item.get("files") if isinstance(item.get("files"), list) else []
        result = {"id": item.get("id"), "status": "modified_after_apply"}
        if all(
            isinstance(record, dict)
            and file_sha1(Path(record["path"])) == record.get("after_sha1")
            for record in files
        ):
            try:
                for record in reversed(files):
                    _restore_file(record)
                result["status"] = "rolled_back"
            except Exception as error:
                result["status"] = "error"
                result["error_kind"] = type(error).__name__
        results.append(result)
    results.reverse()
    write_private(
        plan_path.parent / "rollback.json",
        json_text({"schema": "env-audit/cleanup-rollback", "items": results}),
    )
    return 0
