#!/usr/bin/env bash
# /auto-pilot tick runner — invoked by cron / manually / from TG /sprint.
#
# v4 (post-codereview):
#   R4: trap on TERM/INT/EXIT — финальный статус всегда пишется,
#       SIGTERM пробрасывается в process group claude.
#   R5/R6: PID-file /tmp/autopilot_wrapper.pid + wrapper_id (PID-startclk) в логах.
#       Heartbeat читает PID-file (не pgrep -f), привязан к конкретному запуску.
#   R14: FINAL_RC=0 init + explicit для pause/budget exit.
#   R15: после macro-tick проверяем dirty tree — если есть uncommitted
#        работа без commit и progress=false → escalate, не следующий macro.
#
# v3 (2026-05-14): continuous mode.
#   Wrapper выполняет внешний цикл macro-ticks пока:
#     • спека не завершена (нет новых коммитов 2 макро-тика подряд)
#     • OR ⛔ AUTOPILOT_PAUSE в HANDOFF
#     • OR daily token budget (.claude/autopilot.json:budget) почти исчерпан (>=90%)
#     • OR OUTER_MAX=10 макро-тиков (safety cap)
#     • OR macro-tick завершился rc!=0 (escalation already sent)
#     • OR dirty tree без progress (R15)
#
#   Внутри каждого macro-tick: v2 retry-loop (до 4× $5 = $20 cap) при budget exhaust.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

export HOME="${HOME:-/home/zhigalovka}"
# R1+R18: PATH-override чтобы git-guard.sh перехватывал destructive git ops у
# spawned claude --print. Shim читает .claude/autopilot.json denylist.
export PATH="${REPO_ROOT}/scripts/autopilot/path-overrides:${HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

LOCK_FILE="${REPO_ROOT}/.claude/autopilot.lock"
PID_FILE="/tmp/autopilot_wrapper.pid"
LOG_DIR="${REPO_ROOT}/logs/autopilot"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/$(date -u +%Y-%m-%d).log"

# Flock — non-blocking. If a previous wrapper invocation still loops, exit cleanly.
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "[$(date -u +%FT%TZ)] CONTINUOUS skipped: previous wrapper still active" >> "${LOG_FILE}"
  exit 0
fi

# R5: PID-file. Удаляется trap'ом при выходе.
echo "$$" > "${PID_FILE}"

# R6: wrapper_id = PID + start_clk из /proc/.../stat — стабильный uniquerunner ID
WRAPPER_PID="$$"
PROC_START_CLK="$(awk '{print $22}' "/proc/$$/stat" 2>/dev/null || echo 0)"
WRAPPER_ID="${WRAPPER_PID}-${PROC_START_CLK}"

# R14: explicit init для всех globals что могут быть прочитаны при early-exit
FINAL_RC=0
STOP_REASON=""
OUTER_COUNT=0
TOTAL_ATTEMPTS=0
TOTAL_COMMITS=0
MACRO_ATTEMPTS=0
MACRO_REASON=""
MACRO_PRE_HEAD=""
MACRO_POST_HEAD=""

# Load AUTOPILOT_* and other env so spawned Claude sessions have them.
if [[ -f "${REPO_ROOT}/.env.dev" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env.dev"
  set +a
fi

TG_NOTIFY="${REPO_ROOT}/scripts/autopilot/tg_notify.sh"
AUTOPILOT_JSON="${REPO_ROOT}/.claude/autopilot.json"

WRAPPER_START_TS="$(date -u +%FT%TZ)"
WRAPPER_START_SEC="$(date -u +%s)"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo ?)"
INITIAL_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo ?)"

# R4: trap для cleanup. Гарантирует финальный статус даже при SIGTERM.
# Идея: если убивают, убиваем child claude и пишем «CONTINUOUS exit reason=signal».
cleanup() {
  local SIG="${1:-EXIT}"
  echo "[$(date -u +%FT%TZ)] CONTINUOUS cleanup triggered by ${SIG} (FINAL_RC=${FINAL_RC} stop=${STOP_REASON:-unknown})" >> "${LOG_FILE}"

  # Убить любых живых child claude --print через process group
  if [[ -n "${CHILD_TIMEOUT_PID:-}" ]]; then
    kill -TERM -"${CHILD_TIMEOUT_PID}" 2>/dev/null || true
  fi

  # Если из-за signal — финальный TG-ping (best effort).
  if [[ "${SIG}" == "TERM" || "${SIG}" == "INT" ]]; then
    "${TG_NOTIFY}" "🛑 Автопилот прерван сигналом ${SIG}
Wrapper ID: ${WRAPPER_ID}
Длительность: $(( ( $(date -u +%s) - WRAPPER_START_SEC ) / 60 )) мин
Stop reason: ${STOP_REASON:-killed-by-signal}
Лог: logs/autopilot/$(date -u +%Y-%m-%d).log" >/dev/null 2>&1 || true
    STOP_REASON="${STOP_REASON:-killed-by-signal-${SIG}}"
    FINAL_RC=143  # 128+15 (SIGTERM convention)
  fi

  # Удалить PID-file (R5)
  rm -f "${PID_FILE}" 2>/dev/null || true
}

trap 'cleanup TERM' TERM
trap 'cleanup INT'  INT
trap 'cleanup EXIT' EXIT

LAST_COMMIT_TITLE="$(git log -1 --format='%s' 2>/dev/null | head -c 80)"
HANDOFF_DIRECTIVE="$(grep -m1 -A1 '^## 🤖 Автопилот: следующее' "${REPO_ROOT}/SUP-HANDOFF.md" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//' | head -c 100)"

{
  echo
  echo "════════════════════════════════════════════════════════════════"
  echo "[${WRAPPER_START_TS}] CONTINUOUS start wrapper_id=${WRAPPER_ID} branch=${BRANCH} head=${INITIAL_HEAD}"
} >> "${LOG_FILE}"

"${TG_NOTIFY}" "$(cat <<EOF
🤖 Автопилот стартует (${WRAPPER_START_TS})
Ветка: ${BRANCH} @ ${INITIAL_HEAD}
Последний коммит: ${LAST_COMMIT_TITLE}
Из HANDOFF: ${HANDOFF_DIRECTIVE:-«нет директивы»}

Continuous mode v4: до 10 макро-тиков подряд пока есть прогресс.
EOF
)" >> "${LOG_FILE}" 2>&1

# ---- Helper: check daily budget (returns 0 if budget OK, 1 if >=90% exhausted) ----
check_daily_budget() {
  AUTOPILOT_JSON="${AUTOPILOT_JSON}" python3 - <<'PY'
import json, os, sys
try:
    d = json.load(open(os.environ['AUTOPILOT_JSON']))
    today = d.get('tokens_today', 0)
    cap = d.get('budget', {}).get('max_tokens_per_day', 5_000_000)
    if today >= cap * 0.9:
        sys.exit(1)
    sys.exit(0)
except Exception:
    sys.exit(0)  # на ошибке чтения — не блокируем
PY
}

# ---- Helper: read tokens_today for TG reports ----
get_tokens_today() {
  AUTOPILOT_JSON="${AUTOPILOT_JSON}" python3 - <<'PY' 2>/dev/null
import json, os
try:
    d = json.load(open(os.environ['AUTOPILOT_JSON']))
    cap = d.get('budget', {}).get('max_tokens_per_day', 5_000_000)
    today = d.get('tokens_today', 0)
    print(f"{today}/{cap}")
except Exception:
    print("?/?")
PY
}

# ---- Helper: run ONE macro-tick (v2 retry-loop inside) ----
run_one_macro_tick() {
  MACRO_START_TS="$(date -u +%FT%TZ)"
  MACRO_PRE_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo ?)"

  {
    echo
    echo "[${MACRO_START_TS}] MACRO-TICK start wrapper_id=${WRAPPER_ID} pre_head=${MACRO_PRE_HEAD}"
  } >> "${LOG_FILE}"

  local MAX_RETRIES=4
  local ATTEMPT=0
  FINAL_RC=1
  MACRO_REASON=""
  MACRO_ATTEMPTS=0

  while (( ATTEMPT < MAX_RETRIES )); do
    local ATTEMPT_NUM=$((ATTEMPT + 1))
    local ATTEMPT_START_TS
    ATTEMPT_START_TS="$(date -u +%FT%TZ)"
    echo "[${ATTEMPT_START_TS}] attempt ${ATTEMPT_NUM}/${MAX_RETRIES} (claude --print, \$5 budget)" >> "${LOG_FILE}"

    local PRE_ATTEMPT_LOG_BYTES
    PRE_ATTEMPT_LOG_BYTES="$(wc -c < "${LOG_FILE}")"

    # R4: запускаем timeout в новой process group чтобы trap мог послать SIGTERM
    # всей группе (включая claude --print). $! даст PID timeout.
    setsid timeout --signal=TERM --kill-after=30s 30m \
      claude --print \
        --permission-mode bypassPermissions \
        --max-budget-usd 5 \
        --no-session-persistence \
        "/auto-pilot" \
      >> "${LOG_FILE}" 2>&1 &
    CHILD_TIMEOUT_PID=$!
    wait "${CHILD_TIMEOUT_PID}"
    local RC=$?
    CHILD_TIMEOUT_PID=""

    local ATTEMPT_END_TS
    ATTEMPT_END_TS="$(date -u +%FT%TZ)"
    echo "[${ATTEMPT_END_TS}] attempt ${ATTEMPT_NUM} end rc=${RC}" >> "${LOG_FILE}"

    local ATTEMPT_LOG_TAIL
    ATTEMPT_LOG_TAIL="$(tail -c +"${PRE_ATTEMPT_LOG_BYTES}" "${LOG_FILE}")"

    case "${RC}" in
      0)
        FINAL_RC=0
        MACRO_ATTEMPTS=${ATTEMPT_NUM}
        break
        ;;
      1)
        if echo "${ATTEMPT_LOG_TAIL}" | grep -q "Exceeded USD budget"; then
          MACRO_REASON="budget-exhausted"
          ATTEMPT=$((ATTEMPT + 1))
          if (( ATTEMPT < MAX_RETRIES )); then
            "${TG_NOTIFY}" "🔄 Self-heal retry ${ATTEMPT_NUM}/${MAX_RETRIES}
Причина: \$5 budget cap, fresh session." >> "${LOG_FILE}" 2>&1
            sleep 5
            continue
          else
            MACRO_REASON="budget-exhausted-cap-reached"
            MACRO_ATTEMPTS=${ATTEMPT_NUM}
            break
          fi
        else
          MACRO_REASON="generic-error-rc1"
          MACRO_ATTEMPTS=${ATTEMPT_NUM}
          break
        fi
        ;;
      124)
        MACRO_REASON="wall-clock-timeout"
        MACRO_ATTEMPTS=${ATTEMPT_NUM}
        break
        ;;
      137|143)
        MACRO_REASON="signaled"
        MACRO_ATTEMPTS=${ATTEMPT_NUM}
        break
        ;;
      *)
        MACRO_REASON="unknown-rc${RC}"
        MACRO_ATTEMPTS=${ATTEMPT_NUM}
        break
        ;;
    esac
  done

  MACRO_POST_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo ?)"
  local MACRO_END_TS
  MACRO_END_TS="$(date -u +%FT%TZ)"
  echo "[${MACRO_END_TS}] MACRO-TICK end final_rc=${FINAL_RC} wrapper_id=${WRAPPER_ID} attempts=${MACRO_ATTEMPTS} reason=${MACRO_REASON:-success} pre_head=${MACRO_PRE_HEAD} post_head=${MACRO_POST_HEAD}" >> "${LOG_FILE}"
}

# ---- OUTER LOOP — continuous mode ----
OUTER_MAX=10
NO_PROGRESS_RUNS=0
NO_PROGRESS_LIMIT=2
PREV_OUTER_HEAD="${INITIAL_HEAD}"

while (( OUTER_COUNT < OUTER_MAX )); do
  OUTER_COUNT=$((OUTER_COUNT + 1))

  # Pre-check: AUTOPILOT_PAUSE in HANDOFF
  if grep -q "AUTOPILOT_PAUSE" "${REPO_ROOT}/SUP-HANDOFF.md" 2>/dev/null; then
    STOP_REASON="pause-set"
    FINAL_RC=0  # R14: explicit
    echo "[$(date -u +%FT%TZ)] CONTINUOUS stop: AUTOPILOT_PAUSE detected" >> "${LOG_FILE}"
    break
  fi

  # Pre-check: daily budget
  if ! check_daily_budget; then
    STOP_REASON="daily-budget-90pct"
    FINAL_RC=0  # R14: explicit
    echo "[$(date -u +%FT%TZ)] CONTINUOUS stop: daily token budget >= 90%" >> "${LOG_FILE}"
    break
  fi

  echo "[$(date -u +%FT%TZ)] CONTINUOUS iteration ${OUTER_COUNT}/${OUTER_MAX} (no-progress: ${NO_PROGRESS_RUNS}/${NO_PROGRESS_LIMIT})" >> "${LOG_FILE}"

  # Run one macro-tick
  run_one_macro_tick
  TOTAL_ATTEMPTS=$((TOTAL_ATTEMPTS + MACRO_ATTEMPTS))

  # Check if final_rc != 0 → escalation already happened inside, stop outer
  if (( FINAL_RC != 0 )); then
    STOP_REASON="macro-tick-failed:${MACRO_REASON}"
    break
  fi

  # R15: dirty tree check (uncommitted changes after macro-tick = autopilot
  # сделал работу но не закоммитил → опасно для следующего тика).
  DIRTY="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  if (( DIRTY > 0 )); then
    STOP_REASON="dirty-tree-uncommitted"
    FINAL_RC=2  # отличный rc — escalation, не success
    echo "[$(date -u +%FT%TZ)] CONTINUOUS stop: dirty tree (${DIRTY} files uncommitted)" >> "${LOG_FILE}"
    "${TG_NOTIFY}" "⚠️ Автопилот оставил uncommitted работу (${DIRTY} файлов)
Останавливаю continuous-loop чтобы не усугубить состояние.
Проверь: git status; либо commit, либо checkout." >/dev/null 2>&1
    break
  fi

  # Check progress (HEAD change)
  if [[ "${MACRO_POST_HEAD}" == "${PREV_OUTER_HEAD}" ]]; then
    NO_PROGRESS_RUNS=$((NO_PROGRESS_RUNS + 1))
    echo "[$(date -u +%FT%TZ)] CONTINUOUS: no new commits this iteration (count ${NO_PROGRESS_RUNS}/${NO_PROGRESS_LIMIT})" >> "${LOG_FILE}"
    if (( NO_PROGRESS_RUNS >= NO_PROGRESS_LIMIT )); then
      STOP_REASON="no-progress"
      FINAL_RC=0  # R14: no-progress = успешное завершение (спека сделана)
      break
    fi
  else
    NO_PROGRESS_RUNS=0
    TOTAL_COMMITS=$((TOTAL_COMMITS + $(git log --oneline "${PREV_OUTER_HEAD}..${MACRO_POST_HEAD}" 2>/dev/null | wc -l)))
    PREV_OUTER_HEAD="${MACRO_POST_HEAD}"
  fi

  # Brief pause between macro-ticks
  sleep 10
done

# Hit OUTER_MAX without other stop reason?
if [[ -z "${STOP_REASON}" ]]; then
  STOP_REASON="outer-max-reached"
fi

# ---- Final report ----
WRAPPER_END_TS="$(date -u +%FT%TZ)"
WRAPPER_END_SEC="$(date -u +%s)"
WRAPPER_MIN=$(( (WRAPPER_END_SEC - WRAPPER_START_SEC) / 60 ))

END_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo ?)"
NEW_COMMITS_COUNT="$(git log --oneline "${INITIAL_HEAD}..HEAD" 2>/dev/null | wc -l | tr -d ' ')"
NEW_COMMITS_LIST="$(git log --oneline "${INITIAL_HEAD}..HEAD" 2>/dev/null | head -5 | sed 's/^/  • /')"
[[ -z "${NEW_COMMITS_LIST}" ]] && NEW_COMMITS_LIST="  (нет новых коммитов)"
TOKENS_DISPLAY="$(get_tokens_today)"

echo "[${WRAPPER_END_TS}] CONTINUOUS exit reason=${STOP_REASON} wrapper_id=${WRAPPER_ID} iterations=${OUTER_COUNT} total_attempts=${TOTAL_ATTEMPTS} new_commits=${NEW_COMMITS_COUNT} final_rc=${FINAL_RC}" >> "${LOG_FILE}"

# Emoji by reason
case "${STOP_REASON}" in
  pause-set)            EMOJI="⏸" ;;
  daily-budget-90pct)   EMOJI="💰" ;;
  no-progress)          EMOJI="✅" ;;
  outer-max-reached)    EMOJI="🛑" ;;
  dirty-tree-uncommitted) EMOJI="⚠️" ;;
  killed-by-signal-*)   EMOJI="🛑" ;;
  macro-tick-failed:*)  EMOJI="🔴" ;;
  *)                    EMOJI="ℹ️" ;;
esac

"${TG_NOTIFY}" "$(cat <<EOF
${EMOJI} Автопилот закончил continuous-режим
Длительность: ${WRAPPER_MIN} мин, итераций: ${OUTER_COUNT}/${OUTER_MAX}, attempts total: ${TOTAL_ATTEMPTS}
Stop reason: ${STOP_REASON}
Ветка: ${BRANCH} @ ${END_HEAD}
Новых коммитов: ${NEW_COMMITS_COUNT}
${NEW_COMMITS_LIST}

Tokens today: ${TOKENS_DISPLAY}
Лог: logs/autopilot/$(date -u +%Y-%m-%d).log
EOF
)" >> "${LOG_FILE}" 2>&1

exit "${FINAL_RC}"
