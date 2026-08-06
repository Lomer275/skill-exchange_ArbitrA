#!/usr/bin/env bash
#
# agents-context.sh — give Claude Code and Codex the same team context.
#
# Problem this solves: the two agents have identical two-layer config mechanics
# (a global instruction file plus a per-project one), and on most machines both
# global slots are empty. An agent opened outside the one configured repository
# knows nothing — not the team rules, not the stop lines, not that a second
# agent works alongside it.
#
# This script fills those slots deterministically. No network, no LLM: it must
# keep working exactly when a token limit has run out, which is the moment
# people actually need to move over to the other agent.
#
# Nothing is ever overwritten wholesale. Content is written between markers:
#
#     <!-- BEGIN team-context -->
#     ...managed block...
#     <!-- END team-context -->
#
# Only the inside of that block is replaced. Anything a person wrote around it
# survives every rerun. A file that has no markers gets the block appended, so
# the first run cannot destroy an existing hand-written file either.
#
# Usage:
#   agents-context.sh apply                    # global slots of both agents
#   agents-context.sh apply --project <path>   # ...plus that project
#   agents-context.sh apply --all              # ...plus every git repo in ~/projects
#   agents-context.sh check [same flags]       # report drift, change nothing, exit 1 if any
#   agents-context.sh link-worktrees           # give existing worktrees the project's skills
#
#   --dry-run    show a diff of what would change and write nothing
#   --verbose    explain every decision, including skips
#
set -euo pipefail

BEGIN_MARK='<!-- BEGIN team-context -->'
END_MARK='<!-- END team-context -->'

SELF_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
POLICY_FILE="$SELF_DIR/policy.md"

MODE=""
DRY_RUN=0
VERBOSE=0
DO_ALL=0
PROJECTS=()
PROJECTS_DIR="${AGENTS_CONTEXT_PROJECTS_DIR:-$HOME/projects}"

REPORT=()
DRIFT=0
FAILED=0

# --------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------

log()  { [ "$VERBOSE" -eq 1 ] && printf '  · %s\n' "$*" >&2 || true; }
note() { REPORT+=("$*"); }
die()  { printf 'ошибка: %s\n' "$*" >&2; exit 2; }

usage() {
    sed -n '3,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

# --------------------------------------------------------------------------
# marker mechanics
# --------------------------------------------------------------------------

# Classify a file's marker state. Echoes one of:
#   none                     — no markers at all
#   ok <begin_ln> <end_ln>   — exactly one well-ordered pair
#   corrupt <reason>         — anything else; caller must not write
marker_state() {
    local file="$1" begin_ln end_ln nb ne
    begin_ln="$(grep -n -F -x "$BEGIN_MARK" "$file" | cut -d: -f1 || true)"
    end_ln="$(grep -n -F -x "$END_MARK" "$file" | cut -d: -f1 || true)"
    nb="$(printf '%s' "$begin_ln" | grep -c . || true)"
    ne="$(printf '%s' "$end_ln" | grep -c . || true)"

    if [ "$nb" -eq 0 ] && [ "$ne" -eq 0 ]; then
        echo "none"
    elif [ "$nb" -eq 1 ] && [ "$ne" -eq 1 ] && [ "$begin_ln" -lt "$end_ln" ]; then
        echo "ok $begin_ln $end_ln"
    elif [ "$nb" -eq 0 ]; then
        echo "corrupt закрывающий маркер без открывающего, строка $end_ln"
    elif [ "$ne" -eq 0 ]; then
        echo "corrupt открывающий маркер без закрывающего, строка $begin_ln"
    elif [ "$nb" -gt 1 ] || [ "$ne" -gt 1 ]; then
        echo "corrupt маркеров больше одной пары (BEGIN×$nb, END×$ne)"
    else
        echo "corrupt END раньше BEGIN (строки $end_ln и $begin_ln)"
    fi
}

# Build the intended full content of <file> given <block content file>.
# Prints the result to stdout; never touches the original.
render_target() {
    local file="$1" block="$2" template="${3:-}"

    if [ ! -f "$file" ]; then
        if [ -n "$template" ]; then
            # The template carries a {{BLOCK}} line where the managed block goes.
            awk -v b="$block" -v bm="$BEGIN_MARK" -v em="$END_MARK" '
                $0 == "{{BLOCK}}" {
                    print bm
                    while ((getline line < b) > 0) print line
                    close(b)
                    print em
                    next
                }
                { print }
            ' "$template"
        else
            printf '%s\n' "$BEGIN_MARK"
            cat "$block"
            printf '%s\n' "$END_MARK"
        fi
        return 0
    fi

    local state
    state="$(marker_state "$file")"

    case "$state" in
        none)
            # Append, separated by a blank line. Nothing existing is removed.
            cat "$file"
            [ -n "$(tail -c 1 "$file")" ] && printf '\n'
            printf '\n%s\n' "$BEGIN_MARK"
            cat "$block"
            printf '%s\n' "$END_MARK"
            ;;
        ok*)
            awk -v b="$block" -v bm="$BEGIN_MARK" -v em="$END_MARK" '
                $0 == bm {
                    print
                    while ((getline line < b) > 0) print line
                    close(b)
                    skip = 1
                    next
                }
                $0 == em { skip = 0; print; next }
                !skip { print }
            ' "$file"
            ;;
        corrupt*)
            return 3
            ;;
    esac
}

# apply_block <label> <file> <block content file> [template] [create_only]
#
# create_only=1 means: create the file if it is missing, otherwise leave it
# entirely alone. Used for CLAUDE.md — it is the project's own hand-written
# document, and the team policy already reaches Claude through the global slot.
apply_block() {
    local label="$1" file="$2" block="$3" template="${4:-}" create_only="${5:-0}"
    local rendered state

    if [ "$create_only" = "1" ] && [ -f "$file" ]; then
        log "$label — существует, не трогаю (файл ведёт человек)"
        note "= $label — существует, не трогаю"
        return 0
    fi

    if [ -f "$file" ]; then
        state="$(marker_state "$file")"
        if [[ "$state" == corrupt* ]]; then
            note "✗ $label — маркеры повреждены: ${state#corrupt }. Файл не тронут."
            FAILED=1
            return 0
        fi
    fi

    rendered="$(mktemp "${TMPDIR:-/tmp}/agents-context.XXXXXX")"
    if ! render_target "$file" "$block" "$template" > "$rendered"; then
        rm -f "$rendered"
        note "✗ $label — не удалось собрать содержимое."
        FAILED=1
        return 0
    fi

    if [ -f "$file" ] && cmp -s "$file" "$rendered"; then
        rm -f "$rendered"
        log "$label — уже актуально"
        [ "$MODE" = "check" ] && note "✓ $label — актуально" || note "= $label — без изменений"
        return 0
    fi

    if [ "$MODE" = "check" ]; then
        rm -f "$rendered"
        DRIFT=1
        if [ ! -f "$file" ]; then
            note "✗ $label — файла нет, блок не установлен"
        else
            note "✗ $label — блок отсутствует или отличается от policy.md"
        fi
        return 0
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        printf '\n--- %s ---\n' "$label"
        if [ -f "$file" ]; then
            diff -u "$file" "$rendered" || true
        else
            printf '(файл будет создан, %s строк)\n' "$(wc -l < "$rendered")"
        fi
        rm -f "$rendered"
        note "~ $label — изменился бы (dry-run, не записано)"
        return 0
    fi

    mkdir -p "$(dirname "$file")"
    # Atomic swap: a interrupted run must not leave a truncated file.
    local tmp
    tmp="$(mktemp "$(dirname "$file")/.agents-context.XXXXXX")"
    cat "$rendered" > "$tmp"
    chmod 644 "$tmp"
    mv -f "$tmp" "$file"
    rm -f "$rendered"
    note "✓ $label — записан"
}

# --------------------------------------------------------------------------
# block content
# --------------------------------------------------------------------------

# The project-layer block is an adapter, not a knowledge store: role, pointers,
# and nothing project-specific. Everything factual lives outside the markers
# (or in CLAUDE.md), so regeneration can never lose knowledge.
project_block() {
    local name="$1" out="$2"
    cat > "$out" <<EOF
## Роль агента в проекте \`$name\`

**Главный документ проекта — [CLAUDE.md](CLAUDE.md), читай его первым.** Здесь только
роль и указатели; всё знание о проекте живёт там и в разделах ниже, вне этого блока.

- Ты — исполнитель. Задание приходит брифом: файл найден, подход выбран, границы
  и критерии готовности зафиксированы. Реализуй бриф, а не проектируй заново.
- Бриф неверен — сделай возможное и **опиши расхождение** в финальном отчёте.
  Молча переписывать задачу нельзя.
- Общие правила команды и стоп-линии — в глобальных настройках агента
  (\`~/.claude/CLAUDE.md\` и \`\$CODEX_HOME/AGENTS.md\`), они одинаковы во всех проектах.

Блок ведёт \`agents-context\`. Правки внутри маркеров затрутся при следующем запуске —
пиши снаружи.
EOF
}

agents_template() {
    local name="$1" out="$2"
    cat > "$out" <<EOF
# AGENTS.md — инструкции для агента-исполнителя в проекте $name

{{BLOCK}}

## Контекст проекта

<!-- Заполни: что это за проект, стек, точка входа. Этот раздел вне блока и переживает
     перезапуск agents-context. -->

## Как запускать тесты

<!-- Заполни: команда прогона тестов. -->

## Проектные запреты

<!-- Заполни: что в этом проекте трогать нельзя. -->
EOF
}

# CLAUDE.md is never a managed file: it is the project's own document, written by
# a person. The script only offers a scaffold when none exists, and there is no
# marked block in it — the team policy reaches Claude through the global slot.
claude_template() {
    local name="$1" out="$2"
    cat > "$out" <<EOF
# CLAUDE.md

Указания для агента при работе в проекте **$name**.

Общие правила команды приходят из глобальных настроек агента и здесь не дублируются.
Роль исполнителя и указатели для Codex — в [AGENTS.md](AGENTS.md).

## Проект

<!-- Заполни: чем занимается проект, кто пользователь, что важно. -->

## Команды

<!-- Заполни: запуск, тесты, деплой. -->

## Архитектура

<!-- Заполни: ключевые модули и как они связаны. -->
EOF
}

# --------------------------------------------------------------------------
# layers
# --------------------------------------------------------------------------

do_global() {
    local claude_home="$HOME/.claude"
    local codex_home="${CODEX_HOME:-$HOME/.codex}"

    if [ -d "$claude_home" ]; then
        apply_block "Claude · $claude_home/CLAUDE.md" "$claude_home/CLAUDE.md" "$POLICY_FILE"
    else
        note "— Claude не найден ($claude_home нет) — пропустил"
    fi

    if [ -d "$codex_home" ]; then
        apply_block "Codex · $codex_home/AGENTS.md" "$codex_home/AGENTS.md" "$POLICY_FILE"
    else
        note "— Codex не найден ($codex_home нет) — пропустил"
    fi
}

do_project() {
    local dir="$1" name block agents_tpl claude_tpl
    dir="$(cd "$dir" 2>/dev/null && pwd)" || { note "— $1 — каталога нет, пропустил"; return 0; }
    name="$(basename "$dir")"

    if [ ! -e "$dir/.git" ]; then
        note "— $name — не git-репозиторий, пропустил"
        return 0
    fi

    # In a linked worktree `.git` is a file, not a directory. Such a checkout
    # already receives AGENTS.md from git, so writing here would only leave an
    # uncommitted change on every session branch. The block reaches worktrees
    # through the main checkout's commit instead.
    if [ -f "$dir/.git" ]; then
        note "— $name — git-worktree, приедет из основного чекаута, пропустил"
        return 0
    fi

    block="$(mktemp "${TMPDIR:-/tmp}/agents-context-block.XXXXXX")"
    agents_tpl="$(mktemp "${TMPDIR:-/tmp}/agents-context-tpl.XXXXXX")"
    claude_tpl="$(mktemp "${TMPDIR:-/tmp}/agents-context-tpl.XXXXXX")"
    project_block "$name" "$block"
    agents_template "$name" "$agents_tpl"
    claude_template "$name" "$claude_tpl"

    apply_block "$name · AGENTS.md" "$dir/AGENTS.md" "$block" "$agents_tpl"
    apply_block "$name · CLAUDE.md" "$dir/CLAUDE.md" "$block" "$claude_tpl" 1

    rm -f "$block" "$agents_tpl" "$claude_tpl"
}

# One-off sweep for checkouts that already exist. New worktrees get their skills
# at birth (session.sh), so this is deliberately not part of `apply`: most of the
# 46 stale checkouts here belong to finished sprints and are about to be deleted.
do_link_worktrees() {
    local repo="${1:-$PWD}" main wt skills
    git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
        || { note "— $repo — не git-репозиторий, нечего связывать"; return 0; }

    # Read the whole listing rather than `exit`-ing on the first match: with 47
    # worktrees git is still writing when awk leaves, and the resulting SIGPIPE
    # kills the script (exit 141). Invisible on a repo with few worktrees.
    main="$(git -C "$repo" worktree list --porcelain | awk '/^worktree / && !seen {print $2; seen = 1}')"
    skills="$main/.claude/skills"
    [ -d "$skills" ] || { note "— в основном чекауте нет .claude/skills — связывать нечем"; return 0; }

    while read -r wt; do
        [ "$wt" = "$main" ] && continue
        if [ -e "$wt/.claude/skills" ]; then
            log "$(basename "$wt") — скиллы уже есть"
            continue
        fi
        if [ "$DRY_RUN" -eq 1 ]; then
            note "~ $(basename "$wt") — связал бы скиллы (dry-run)"
            continue
        fi
        mkdir -p "$wt/.claude"
        ln -s "$skills" "$wt/.claude/skills"
        note "✓ $(basename "$wt") — скиллы связаны"
    done < <(git -C "$repo" worktree list --porcelain | awk '/^worktree /{print $2}')
}

do_all_projects() {
    [ -d "$PROJECTS_DIR" ] || { note "— $PROJECTS_DIR нет — нечего обходить"; return 0; }
    local d
    for d in "$PROJECTS_DIR"/*/; do
        [ -d "$d" ] || continue
        do_project "$d"
    done
}

# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

[ $# -gt 0 ] || usage 1

case "$1" in
    apply|check)     MODE="$1"; shift ;;
    link-worktrees)  MODE="$1"; shift ;;
    -h|--help)       usage 0 ;;
    *)               die "неизвестная команда «$1» (нужно apply, check или link-worktrees)" ;;
esac

while [ $# -gt 0 ]; do
    case "$1" in
        --project)      shift; [ $# -gt 0 ] || die "--project требует путь"; PROJECTS+=("$1") ;;
        --all)          DO_ALL=1 ;;
        --projects-dir) shift; [ $# -gt 0 ] || die "--projects-dir требует путь"; PROJECTS_DIR="$1" ;;
        --dry-run)      DRY_RUN=1 ;;
        --verbose|-v)   VERBOSE=1 ;;
        -h|--help)      usage 0 ;;
        *)              die "неизвестный флаг «$1»" ;;
    esac
    shift
done

[ "$MODE" = "check" ] && DRY_RUN=0

if [ "$MODE" = "link-worktrees" ]; then
    if [ "${#PROJECTS[@]}" -gt 0 ]; then
        for p in "${PROJECTS[@]}"; do do_link_worktrees "$p"; done
    else
        do_link_worktrees "$PWD"
    fi
else
    [ -f "$POLICY_FILE" ] || die "не нашёл policy.md рядом со скриптом ($POLICY_FILE)"
    do_global
    for p in ${PROJECTS+"${PROJECTS[@]}"}; do do_project "$p"; done
    [ "$DO_ALL" -eq 1 ] && do_all_projects
fi

printf '\n'
if [ "$MODE" = "check" ]; then
    printf 'Проверка (ничего не менялось):\n'
else
    printf 'Итог:\n'
fi
for line in ${REPORT+"${REPORT[@]}"}; do printf '  %s\n' "$line"; done

if [ "$FAILED" -eq 1 ]; then
    printf '\nЕсть файлы с повреждёнными маркерами — почини их руками и запусти снова.\n'
    exit 2
fi
if [ "$MODE" = "check" ] && [ "$DRIFT" -eq 1 ]; then
    printf '\nНайдены расхождения. Чинит их только явный apply.\n'
    exit 1
fi
exit 0
