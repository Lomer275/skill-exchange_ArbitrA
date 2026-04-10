#!/usr/bin/env bash
# Manual skill installation without CLI.
# Usage: bash scripts/install.sh <skill-name> [target-dir]
#
# Examples:
#   bash scripts/install.sh git-commit-helper
#   bash scripts/install.sh git-commit-helper ~/.claude/plugins

set -euo pipefail

SKILL_NAME="${1:?Usage: bash install.sh <skill-name> [target-dir]}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"
SKILL_SRC="$SKILLS_DIR/$SKILL_NAME"

if [ ! -d "$SKILL_SRC" ]; then
    echo "Error: skill '$SKILL_NAME' not found in $SKILLS_DIR"
    echo "Available skills:"
    ls "$SKILLS_DIR" | grep -v -e "index.json" -e ".gitkeep"
    exit 1
fi

TARGET_DIR="${2:-$HOME/.claude/plugins}"
mkdir -p "$TARGET_DIR"

cp -r "$SKILL_SRC" "$TARGET_DIR/"
echo "Skill '$SKILL_NAME' installed to $TARGET_DIR/$SKILL_NAME"
echo "Restart Claude Code to apply."
