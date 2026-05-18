#!/usr/bin/env python3
"""Read the autopilot pre-authorization YAML block from SUP-HANDOFF.md and
answer one question. Used by /sprint --yes to decide auto-go vs TG-ask.

Format of the HANDOFF block (fenced under «## 🤖 Автопилот: следующее»):

    ```yaml autopilot
    spec: S14
    plan_confirmed: yes
    risky_default: ask          # ask | auto | skip
    deploy_default: ask
    manual_test_default: ask
    test_failure_default: ask
    unplanned_risk_default: ask
    pre_authorized_tasks: [T125, T127, T128]
    always_escalate_tasks:  [T126, T131, T132]
    ```

Decision precedence (most specific wins):
  1. task in always_escalate_tasks  → "ask"
  2. task in pre_authorized_tasks   → "auto"
  3. <checkpoint>_default           → its value
  4. If block missing entirely      → "ask" (safe default)

Usage:
  check_authz.py --task T125 --checkpoint risky_default
      → prints one of: auto | ask | skip

  check_authz.py --checkpoint plan_confirmed
      → prints: yes | no

  check_authz.py --spec
      → prints current spec id (e.g. "S14") or empty

Exits 0 on success, 2 on bad CLI, 3 if HANDOFF unreadable.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import]
except ImportError:
    yaml = None  # we'll fall back to a regex-based mini-parser


# Fenced block we recognize. We look only inside the section opened by
# «## 🤖 Автопилот: следующее» (which is the conventional anchor — see CLAUDE.md).
SECTION_RE = re.compile(
    r"##\s*🤖\s*Автопилот[^\n]*\n(.*?)(?=\n##\s|\Z)",
    re.DOTALL,
)
BLOCK_RE = re.compile(
    r"```yaml\s*autopilot\s*\n(.*?)```",
    re.DOTALL,
)


def find_yaml_block(handoff_text: str) -> str | None:
    sec = SECTION_RE.search(handoff_text)
    if not sec:
        return None
    blk = BLOCK_RE.search(sec.group(1))
    if not blk:
        return None
    return blk.group(1)


_TRUTHY = {"true", "yes", "on", "1"}
_FALSY = {"false", "no", "off", "0"}


def _coerce_bool(val):
    """Strict bool coercion. PyYAML без quotes возвращает True для unquoted yes/true,
    но с quotes — строку. Codex review R7: «yes» строкой проходило как truthy, баг.
    Здесь нормализуем строго: только знакомые слова → bool, остальное → возвращаем как есть.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        s = val.strip().strip("'\"").lower()
        if s in _TRUTHY:
            return True
        if s in _FALSY:
            return False
    return val


def _parse_list_item(s: str) -> str:
    """Снимаем кавычки и запятую с одного элемента списка.
    Codex review R8: `[T125]` парсилось OK, но `["T125"]` → `'"T125"'` (с кавычкой)
    → per-task override silently fails.
    """
    return s.strip().strip(",").strip("'\"")


def parse(block: str) -> dict:
    """Parse the YAML block. Use PyYAML if available, else a tiny fallback that
    handles only the keys we care about (so we don't add a heavy dep for one block).
    """
    if yaml is not None:
        data = yaml.safe_load(block) or {}
        if not isinstance(data, dict):
            return {}
        # Normalize bool-ish values (даже PyYAML возвращает строку для quoted "yes")
        for k in ("plan_confirmed",):
            if k in data:
                data[k] = _coerce_bool(data[k])
        # Normalize list items (strip quotes around strings).
        for k in ("pre_authorized_tasks", "always_escalate_tasks"):
            if isinstance(data.get(k), list):
                data[k] = [str(x).strip("'\"") for x in data[k]]
        return data
    # Minimal fallback parser — handles "key: value" and "key: [a, b, c]".
    out: dict = {}
    for raw in block.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            items = [_parse_list_item(x) for x in inner.split(",") if x.strip()]
            out[k] = items
        elif v.lower() in _TRUTHY:
            out[k] = True
        elif v.lower() in _FALSY:
            out[k] = False
        else:
            out[k] = v.strip("'\"")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--handoff", default="SUP-HANDOFF.md",
                   help="Path to HANDOFF (relative to cwd). Default: SUP-HANDOFF.md")
    p.add_argument("--task", help="Task id like T125 (for per-task lookups)")
    p.add_argument("--checkpoint",
                   help="Checkpoint key: risky_default / deploy_default / "
                        "manual_test_default / test_failure_default / "
                        "unplanned_risk_default / plan_confirmed")
    p.add_argument("--spec", action="store_true",
                   help="Print just the configured spec id and exit.")
    args = p.parse_args()

    path = Path(args.handoff)
    if not path.exists():
        sys.stderr.write(f"check_authz: HANDOFF not found at {path}\n")
        return 3
    text = path.read_text(encoding="utf-8")
    block = find_yaml_block(text)
    cfg: dict = parse(block) if block else {}

    if args.spec:
        print(cfg.get("spec", ""))
        return 0

    if not args.checkpoint:
        sys.stderr.write("check_authz: --checkpoint required (or --spec)\n")
        return 2

    # plan_confirmed: just yes/no (strict coercion на случай PyYAML quoted str)
    if args.checkpoint == "plan_confirmed":
        val = _coerce_bool(cfg.get("plan_confirmed", False))
        # If coerce returned non-bool (unknown string) — safe default False.
        print("yes" if val is True else "no")
        return 0

    # Per-task overrides
    if args.task:
        if args.task in (cfg.get("always_escalate_tasks") or []):
            print("ask")
            return 0
        if args.task in (cfg.get("pre_authorized_tasks") or []):
            print("auto")
            return 0

    default = cfg.get(args.checkpoint)
    if default in ("auto", "ask", "skip"):
        print(default)
        return 0

    # No block / no key — safest default is "ask".
    print("ask")
    return 0


if __name__ == "__main__":
    sys.exit(main())
