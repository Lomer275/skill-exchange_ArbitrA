#!/usr/bin/env bash
# Wrapper-shim around `git` для технического enforcement destructive_git_ops_forbidden.
#
# Контекст (R1, R18 из codereview-dual): SKILL.md содержит список запретов
# (push --force, reset --hard, branch -D, ...), но при `claude --print
# --permission-mode bypassPermissions` это только текстовые инструкции. Если
# модель ошибётся / промпт скомпрометирован — никакой технический контроль не
# мешает destructive git операции.
#
# Эта обёртка читает .claude/autopilot.json:destructive_git_ops_forbidden и
# отказывает в выполнении подходящих под паттерн команд. Сама команда
# делегируется в реальный git (по дефолту /usr/bin/git).
#
# Использование (в run_tick.sh):
#   export PATH="${REPO_ROOT}/scripts/autopilot/path-overrides:${PATH}"
# где path-overrides/git → symlink на git-guard.sh.
#
# Или напрямую: vim ~/.bashrc → alias git=/path/to/git-guard.sh
#
# Этот shim сам ловит первый позиционный arg (subcommand) + ищет matching
# substring из forbidden list по всей argv. Сравнение string-contains (не regex),
# как в JSON.

set -euo pipefail

# Resolve real path (если вызвано через symlink из path-overrides/git → guard).
# readlink -f следует все symlink'и до physical файла.
REAL_SELF="$(readlink -f "${BASH_SOURCE[0]}")"
REPO_ROOT="$(cd "$(dirname "${REAL_SELF}")/../.." && pwd)"
AUTOPILOT_JSON="${REPO_ROOT}/.claude/autopilot.json"
REAL_GIT="${GIT_GUARD_REAL_GIT:-/usr/bin/git}"

# Если real git не существует — пробуем через PATH (исключая текущую папку).
if [[ ! -x "${REAL_GIT}" ]]; then
  REAL_GIT="$(PATH="${PATH#${REPO_ROOT}/scripts/autopilot/path-overrides:}" command -v git 2>/dev/null || echo "")"
fi
if [[ -z "${REAL_GIT}" ]] || [[ ! -x "${REAL_GIT}" ]]; then
  echo "git-guard: real git binary not found (set GIT_GUARD_REAL_GIT)" >&2
  exit 127
fi

# Собираем argv в одну строку для substring-match
ARGV_STRING="$*"

# Читаем denylist из autopilot.json (Python для атомарного JSON parse).
DENYLIST="$(AUTOPILOT_JSON="${AUTOPILOT_JSON}" python3 -c '
import json, os, sys
try:
    d = json.load(open(os.environ["AUTOPILOT_JSON"]))
    for item in d.get("destructive_git_ops_forbidden", []):
        print(item)
except Exception as e:
    sys.stderr.write(f"git-guard: cant read denylist: {e}\n")
    sys.exit(0)  # fail-open — не блокируем git если конфиг битый
' 2>/dev/null)" || DENYLIST=""

if [[ -n "${DENYLIST}" ]]; then
  while IFS= read -r pattern; do
    [[ -z "${pattern}" ]] && continue
    # substring match (не regex) — точно как в JSON
    if [[ "${ARGV_STRING}" == *"${pattern}"* ]]; then
      echo "❌ git-guard: команда '${ARGV_STRING}' содержит forbidden pattern '${pattern}'" >&2
      echo "   denylist живёт в .claude/autopilot.json:destructive_git_ops_forbidden" >&2
      echo "   Если действительно нужно — отредактируй autopilot.json или используй GIT_GUARD_REAL_GIT=/usr/bin/git напрямую." >&2
      exit 100
    fi
  done <<< "${DENYLIST}"
fi

# Пропускаем дальше в реальный git
exec "${REAL_GIT}" "$@"
