import argparse
from pathlib import Path
import sys

from envaudit.core.output import prepare_directory

from .apply import apply_plan, rollback_plan
from .plan import build_plan, render_plan
from .verify import verify_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="План безопасного клинапа env-audit")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="собрать план и дифф")
    plan.add_argument("--facts", type=Path, required=True)
    plan.add_argument("--out-dir", type=Path, required=True)

    render = commands.add_parser("render", help="пересобрать дифф")
    render.add_argument("--plan", type=Path, required=True)

    apply_command = commands.add_parser("apply", help="применить выбранные пункты")
    apply_command.add_argument("--plan", type=Path, required=True)
    apply_command.add_argument("--confirmed", action="store_true")

    verify = commands.add_parser("verify", help="проверить результат повторным сбором")
    verify.add_argument("--plan", type=Path, required=True)

    rollback = commands.add_parser("rollback", help="откатить применённые пункты")
    rollback.add_argument("--plan", type=Path, required=True)
    rollback.add_argument("--confirmed", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        try:
            prepare_directory(args.out_dir)
        except OSError as error:
            print(
                f"не удаётся писать в {args.out_dir}: {error}",
                file=sys.stderr,
            )
            return 2
    try:
        if args.command == "plan":
            return build_plan(args.facts, args.out_dir)
        if args.command == "render":
            return render_plan(args.plan)
        if args.command == "apply":
            code = apply_plan(args.plan, confirmed=args.confirmed)
            if code == 2:
                print("Нужно явное подтверждение: --confirmed", file=sys.stderr)
            return code
        if args.command == "verify":
            return verify_plan(args.plan)
        if args.command == "rollback":
            code = rollback_plan(args.plan, confirmed=args.confirmed)
            if code == 2:
                print("Нужно явное подтверждение: --confirmed", file=sys.stderr)
            return code
    except (OSError, ValueError, KeyError) as error:
        print(f"Ошибка клинапа: {type(error).__name__}", file=sys.stderr)
        return 1
    raise AssertionError("unknown command")
