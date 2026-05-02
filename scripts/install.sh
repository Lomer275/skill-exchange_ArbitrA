#!/usr/bin/env bash
# Manual skill installation without CLI (fallback for users without Python).
# Copies SKILL.md + README.md to <target>/<skill-name>/.
#
# Usage: bash scripts/install.sh <skill-name> [target-dir]
#
# Examples:
#   bash scripts/install.sh example-skill
#   bash scripts/install.sh example-skill ~/.claude/skills

set -euo pipefail

SKILL_NAME="${1:?Usage: bash install.sh <skill-name> [target-dir]}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/plugins/team-skills/skills"
SKILL_SRC="$SKILLS_DIR/$SKILL_NAME"

if [ ! -d "$SKILL_SRC" ]; then
    echo "Error: skill '$SKILL_NAME' not found in $SKILLS_DIR"
    echo "Available skills:"
    ls "$SKILLS_DIR" | grep -v -e "index.json" -e ".gitkeep"
    exit 1
fi

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
    echo "Error: $SKILL_SRC/SKILL.md not found — skill is malformed."
    exit 1
fi

TARGET_DIR="${2:-$HOME/.claude/skills}"
DEST="$TARGET_DIR/$SKILL_NAME"
mkdir -p "$DEST"

cp "$SKILL_SRC/SKILL.md" "$DEST/SKILL.md"
[ -f "$SKILL_SRC/README.md" ] && cp "$SKILL_SRC/README.md" "$DEST/README.md"

echo "Skill '$SKILL_NAME' installed to $DEST"
echo "Restart Claude Code to apply. The skill will be available as /$SKILL_NAME"
