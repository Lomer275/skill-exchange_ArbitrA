#!/usr/bin/env bash
# PATH shim for autopilot ticks; config errors must never disable the guard.
set -euo pipefail
REAL_SELF="$(readlink -f "${BASH_SOURCE[0]}")"
REPO_ROOT="$(cd "$(dirname "${REAL_SELF}")/../.." && pwd)"
AUTOPILOT_JSON="${REPO_ROOT}/.claude/autopilot.json"
REAL_GIT="${GIT_GUARD_REAL_GIT:-/usr/bin/git}"

AUTOPILOT_JSON="${AUTOPILOT_JSON}" python3 - "$@" <<'GUARD'
import json, os, sys
try:
    with open(os.environ["AUTOPILOT_JSON"], encoding="utf-8") as source:
        config = json.load(source)
    patterns = config["destructive_git_ops_forbidden"]
    if not isinstance(patterns, list) or any(not isinstance(p, str) or not p for p in patterns):
        raise ValueError("destructive_git_ops_forbidden must be a list of nonempty strings")
except (OSError, ValueError, KeyError, TypeError) as exc:
    sys.stderr.write(f"git-guard: cannot read config; refusing git ({exc})\n")
    sys.exit(100)

args = sys.argv[1:]
if os.environ.get("AUTOPILOT_TICK") == "1":
    # Only read commands and fetch are needed by a tick. Unknown aliases and
    # configuration injection must not turn an apparently safe command into a write.
    remaining = list(args)
    while remaining:
        option = remaining[0]
        if option in ("-C", "--git-dir", "--work-tree"):
            if len(remaining) < 2:
                break
            remaining = remaining[2:]
        elif option.startswith(("--git-dir=", "--work-tree=")) or option in ("--no-pager", "--paginate", "--no-optional-locks"):
            remaining = remaining[1:]
        else:
            break
    allowed = {
        "status", "diff", "log", "show", "rev-parse", "ls-files",
        "rev-list", "merge-base", "blame", "cat-file", "describe",
        "for-each-ref", "ls-tree", "shortlog", "grep", "name-rev",
        "show-ref", "ls-remote",
    }
    command = remaining[0] if remaining else None
    operands = remaining[1:]
    permitted = command in allowed
    if command == "branch":
        permitted = True
        index = 0
        while index < len(operands):
            option = operands[index]
            if option in ("--show-current", "--list", "-a", "-r", "-v", "-vv"):
                index += 1
            elif option in ("--contains", "--merged", "--no-merged"):
                index += 1
                if index < len(operands) and not operands[index].startswith("-"):
                    index += 1
            elif any(option.startswith(name + "=") and option[len(name) + 1:]
                     for name in ("--contains", "--merged", "--no-merged")):
                index += 1
            else:
                permitted = False
                break
    elif command == "worktree":
        permitted = operands == ["list"]
    elif command == "remote":
        permitted = not operands or operands == ["-v"]
        if operands and operands[0] in ("show", "get-url"):
            options = {"-n"} if operands[0] == "show" else {"--push", "--all"}
            permitted = all(not arg.startswith("-") or arg in options
                            for arg in operands[1:])
    elif command == "config":
        permitted = bool(operands) and operands[0] in (
            "--get", "--get-all", "--get-regexp", "--list", "-l")
        if permitted:
            if operands[0] in ("--list", "-l"):
                permitted = len(operands) == 1
            else:
                permitted = (2 <= len(operands) <= 3
                             and all(not arg.startswith("-") for arg in operands[1:]))
    elif command == "fetch":
        permitted = not any(
            arg.startswith("--upload-pack")
            or (arg.startswith("-") and not arg.startswith("--") and "u" in arg[1:])
            for arg in operands)
    if not permitted:
        sys.stderr.write("git-guard: operation refused during autopilot tick; human review/approval required\n")
        sys.exit(100)
    sys.exit(0)

if any(pattern in " ".join(args) for pattern in patterns):
    sys.stderr.write("git-guard: operation matches destructive_git_ops_forbidden\n")
    sys.exit(100)
GUARD
exec "${REAL_GIT}" "$@"
