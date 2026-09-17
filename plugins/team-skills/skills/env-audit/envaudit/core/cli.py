import argparse
import base64
import json
import os
from pathlib import Path
import pwd
import time

from envaudit.core.bundle import build_bundle
from envaudit.core.context import Context, Flags
from envaudit.core.host import collect_host
from envaudit.core.output import build_document, emit, finalize
from envaudit.core.redact import scan_file
from envaudit.core.runner import run, which
from envaudit.sections import discover, run_sections


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect environment audit facts")
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--root-b64", action="append", default=[])
    parser.add_argument("--expect-user")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scan-file", type=Path)
    parser.add_argument("--budget-seconds", type=int, default=300)
    parser.add_argument("--max-text-mb", type=int, default=2)
    parser.add_argument("--max-hash-mb", type=int, default=20)
    parser.add_argument("--pytest-collect", action="store_true")
    parser.add_argument("--pytest-python")
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--sibling")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--bundle", action="store_true")
    return parser


def _expect_user(name: str) -> bool:
    account = pwd.getpwuid(os.geteuid())
    return (
        account.pw_name == name
        and os.path.realpath(os.environ.get("HOME", ""))
        == os.path.realpath(account.pw_dir)
    )


def _lower_priority() -> None:
    try:
        os.nice(15)
    except OSError:
        pass
    ionice = which("ionice")
    if ionice:
        run([ionice, "-c3", "-p", str(os.getpid())], timeout=5)


def _default_roots(home: Path) -> list[str]:
    projects = home / "projects"
    try:
        return [
            str(path)
            for path in sorted(projects.iterdir(), key=lambda item: item.name)
            if not path.name.startswith(".") and path.is_dir()
        ]
    except OSError:
        return []


def _root_arguments(args: argparse.Namespace, home: Path) -> list[str]:
    roots = list(args.root)
    roots.extend(
        base64.b64decode(value).decode("utf-8") for value in args.root_b64
    )
    return roots or _default_roots(home)


def _resolve_roots(
    raw_roots: list[str], ctx: Context
) -> tuple[list[Path], list[dict]]:
    roots = []
    view = []
    for raw_root in raw_roots:
        path = Path(os.path.realpath(Path(raw_root).expanduser()))
        exists = path.exists()
        view.append({"path": str(path), "exists": exists})
        if exists:
            roots.append(path)
        else:
            ctx.error("roots", "root_not_found")
    if not roots and not ctx.errors:
        ctx.error("roots", "root_not_found")
    return roots, view


def _flags_view(flags: Flags) -> dict:
    return {
        "budget_seconds": flags.budget_seconds,
        "max_text_mb": flags.max_text_mb,
        "max_hash_mb": flags.max_hash_mb,
        "pytest_collect": flags.pytest_collect,
        "pytest_python": flags.pytest_python,
        "docker": flags.docker,
        "sibling": flags.sibling,
        "only": flags.only,
    }


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.bundle:
        print(build_bundle(), end="")
        return 0
    if args.scan_file is not None:
        code, report = scan_file(args.scan_file)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1))
        return code
    if args.expect_user is not None and not _expect_user(args.expect_user):
        print("{}")
        return 4

    _lower_priority()
    home = Path(os.path.realpath(Path.home()))
    started_at = time.time()
    flags = Flags(
        budget_seconds=args.budget_seconds,
        max_text_mb=args.max_text_mb,
        max_hash_mb=args.max_hash_mb,
        pytest_collect=args.pytest_collect,
        pytest_python=args.pytest_python,
        docker=args.docker,
        sibling=args.sibling,
        only=args.only,
    )
    ctx = Context(
        flags=flags,
        home=home,
        roots=[],
        started_at=started_at,
        deadline=started_at + flags.budget_seconds,
    )
    ctx.roots, roots_view = _resolve_roots(_root_arguments(args, home), ctx)
    host = collect_host(ctx)
    ctx.shared["host"] = host
    sections, durations = run_sections(ctx, discover())
    doc = build_document(
        ctx, host, sections, durations, roots_view, _flags_view(flags)
    )
    doc, exit_code = finalize(doc, ctx)
    emit(doc, args.output)
    return exit_code
