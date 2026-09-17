import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import time

from envaudit.core import redact, runner
from envaudit.core.patterns import find
from envaudit.core.resources import read_data
from envaudit.reality.estimate import estimate
from envaudit.reality.sandbox import (
    PrepareError,
    memory_path,
    prepare,
    read_json,
    write_json,
)
from envaudit.reality.verdict import build_verdict


ALLOWED_TOOLS = (
    "Read,Edit,Write,Glob,Grep,Skill,TodoWrite,"
    "Bash(ls:*),Bash(date:*),Bash(find:*),Bash(cat:*),Bash(mkdir:*),"
    "Bash(wc:*),Bash(head:*),Bash(tail:*)"
)
DISALLOWED_TOOLS = (
    "Bash(git push:*),Bash(gh:*),Bash(curl:*),Bash(wget:*),"
    "Bash(ssh:*),Bash(scp:*),WebFetch,WebSearch"
)


def _emit(document: dict) -> None:
    print(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1))


def _number(value: float) -> str:
    return format(value, "g")


def _task_file(document: dict) -> str:
    if not document.get("has_task_file"):
        return "файла задачи нет"
    sandbox = Path(document["sandbox"])
    matches = sorted(sandbox.rglob("T999_env_audit_reality_check.md"))
    if not matches:
        return "файла задачи нет"
    return matches[0].relative_to(sandbox).as_posix()


def _prompt(document: dict) -> str:
    template = read_data("reality_prompt.md")
    if template is None:
        raise FileNotFoundError("reality_prompt.md")
    return template.format(
        typo_line=document["typo_line"],
        task_file=_task_file(document),
    ).strip()


def command_view(
    sandbox_file: Path,
    *,
    max_turns: int,
    max_budget_usd: float,
    model: str | None,
) -> dict:
    document = read_json(sandbox_file)
    argv = [
        "claude",
        "-p",
        _prompt(document),
        "--no-session-persistence",
        "--max-turns",
        str(max_turns),
        "--max-budget-usd",
        _number(max_budget_usd),
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        ALLOWED_TOOLS,
        "--disallowedTools",
        DISALLOWED_TOOLS,
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--output-format",
        "json",
    ]
    if model is not None:
        argv.extend(("--model", model))
    return {
        "cwd": document["sandbox"],
        "argv": argv,
        "shell": shlex.join(argv),
    }


def _redact_text(value: str) -> str:
    data = value.encode("utf-8", "replace")
    matches = find(data, self_check_only=True)
    if not matches:
        return value
    ranges = []
    for item in sorted(matches, key=lambda match: (match.start, match.end)):
        if ranges and item.start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], item.end))
        else:
            ranges.append((item.start, item.end))
    parts = []
    previous = 0
    for start, end in ranges:
        parts.append(data[previous:start])
        sample = data[start:end].decode("utf-8", errors="replace")
        clean, _pointers = redact.self_check(sample)
        replacement = clean if isinstance(clean, str) else redact.REDACTED
        parts.append(replacement.encode("utf-8"))
        previous = end
    parts.append(data[previous:])
    return b"".join(parts).decode("utf-8", errors="replace")


def run_agent(
    sandbox_file: Path,
    *,
    max_turns: int,
    max_budget_usd: float,
    model: str | None,
) -> dict:
    view = command_view(
        sandbox_file,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        model=model,
    )
    started = time.time()
    result = runner.run(view["argv"], cwd=Path(view["cwd"]), timeout=1800)
    finished = time.time()
    document = {
        "started_at": started,
        "finished_at": finished,
        "rc": result.rc,
        "timed_out": result.timed_out,
        "parse_error": False,
    }
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("expected object")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        document["parse_error"] = True
    else:
        denials = payload.get("permission_denials")
        text = payload.get("result")
        document.update(
            {
                "subtype": payload.get("subtype") if isinstance(payload.get("subtype"), str) else None,
                "is_error": payload.get("is_error") if isinstance(payload.get("is_error"), bool) else None,
                "num_turns": payload.get("num_turns") if isinstance(payload.get("num_turns"), int) else None,
                "total_cost_usd": (
                    payload.get("total_cost_usd")
                    if isinstance(payload.get("total_cost_usd"), (int, float))
                    and not isinstance(payload.get("total_cost_usd"), bool)
                    else None
                ),
                "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
                "permission_denials_count": len(denials) if isinstance(denials, list) else 0,
                "result_text": _redact_text(text)[:4000] if isinstance(text, str) else "",
            }
        )
    return write_json(sandbox_file.parent / "run.json", document)


def cleanup(sandbox_file: Path) -> dict:
    document = read_json(sandbox_file)
    sandbox = Path(document["sandbox"])
    expected_memory = memory_path(sandbox)
    allowed = {
        os.path.abspath(os.fspath(sandbox)),
        os.path.abspath(os.fspath(expected_memory)),
    }
    removed = []
    for raw in document.get("owned_paths", []):
        if not isinstance(raw, str) or os.path.abspath(raw) not in allowed:
            continue
        path = Path(os.path.abspath(raw))
        if path == sandbox and not path.name.startswith("env-audit-sbx-"):
            continue
        if path == expected_memory and path != memory_path(sandbox):
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
            removed.append(str(path))
        elif path.exists() or path.is_symlink():
            path.unlink()
            removed.append(str(path))
    return {"removed": removed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run env-audit reality checks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    estimate_parser = subparsers.add_parser("estimate")
    estimate_parser.add_argument("--facts", type=Path, required=True)
    estimate_parser.add_argument("--root", type=Path, required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--facts", type=Path, required=True)
    prepare_parser.add_argument("--root", type=Path, required=True)
    prepare_parser.add_argument("--out-dir", type=Path, required=True)

    for name in ("command", "run"):
        command_parser = subparsers.add_parser(name)
        command_parser.add_argument("--sandbox", type=Path, required=True)
        command_parser.add_argument("--max-turns", type=int, default=40)
        command_parser.add_argument("--max-budget-usd", type=float, default=3.0)
        command_parser.add_argument("--model")
        if name == "run":
            command_parser.add_argument("--confirmed", action="store_true")

    verdict_parser = subparsers.add_parser("verdict")
    verdict_parser.add_argument("--sandbox", type=Path, required=True)
    verdict_parser.add_argument("--run", dest="run_file", type=Path)

    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--sandbox", type=Path, required=True)
    return parser


def _sandbox_file(path: Path) -> Path | None:
    candidate = path / "sandbox.json" if path.is_dir() else path
    return candidate if candidate.is_file() else None


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("estimate", "prepare"):
        facts = read_json(args.facts)
        if args.command == "estimate":
            _emit(estimate(facts, args.root))
            return 0
        try:
            document = prepare(facts, args.root, args.out_dir)
        except PrepareError as error:
            _emit(error.payload)
            return error.code
        _emit(document)
        return 0
    sandbox_file = _sandbox_file(args.sandbox)
    if sandbox_file is None:
        _emit({"error": f"не найден sandbox.json по пути {args.sandbox}"})
        return 2
    args.sandbox = sandbox_file
    if args.command == "command":
        _emit(
            command_view(
                args.sandbox,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget_usd,
                model=args.model,
            )
        )
        return 0
    if args.command == "run":
        if not args.confirmed:
            _emit(
                command_view(
                    args.sandbox,
                    max_turns=args.max_turns,
                    max_budget_usd=args.max_budget_usd,
                    model=args.model,
                )
            )
            return 2
        _emit(
            run_agent(
                args.sandbox,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget_usd,
                model=args.model,
            )
        )
        return 0
    if args.command == "verdict":
        _emit(build_verdict(args.sandbox, args.run_file))
        return 0
    _emit(cleanup(args.sandbox))
    return 0
