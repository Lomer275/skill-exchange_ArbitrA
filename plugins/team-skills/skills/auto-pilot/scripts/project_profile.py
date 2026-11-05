#!/usr/bin/env python3
"""Resolve required repository paths from the team-skills v1 profile."""
import json
import sys
from pathlib import Path


def profile_path(root: Path, key: str) -> Path:
    source = root / ".claude/team-skills.json"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("version must be 1")
        value = data
        for part in key.split("."):
            value = value[part]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("expected a nonempty relative path")
        path = Path(value)
        if path.is_absolute() or not (root / path).resolve().is_relative_to(root.resolve()):
            raise ValueError("path must stay inside the repository")
        return root / path
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(
            f"{source}: required key '{key}' unavailable or invalid ({exc}). "
            "See team-skills:init_dev and docs/team-skills-profile.md in the catalog."
        ) from exc


if __name__ == "__main__":
    try:
        print(profile_path(Path(sys.argv[1]), sys.argv[2]))
    except ValueError as exc:
        sys.stderr.write(f"autopilot profile: {exc}\n")
        sys.exit(3)
