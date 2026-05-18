#!/usr/bin/env bash
# Autopilot heartbeat watchdog.
# Cron: */2 * * * * — runs every 2 min, independent of autopilot itself.
# Goal: «знак жизни» в TG чтобы человек видел что процесс не помер тихо.
#
# v2 (post-codereview):
#   R5: detect wrapper по PID-file /tmp/autopilot_wrapper.pid (atomic), не pgrep -f.
#   R6: state-file хранит wrapper_id (PID+start_ts) — crash-detection привязан к
#       конкретному запуску, не к последнему MACRO-TICK end в файле.
#   R10: state-file пишется через tmp+atomic mv с advisory flock (свой лок).
#   E4: все Python heredoc'и читают пути через env, не через ${} интерполяцию.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

# Source env (.env.dev) для TG-creds. Non-fatal если файла нет.
if [[ -f "${REPO_ROOT}/.env.dev" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env.dev"
  set +a
fi

STATE_FILE="/tmp/autopilot_heartbeat_state.json"
HEARTBEAT_LOCK="/tmp/autopilot_heartbeat.lock"
WRAPPER_PID_FILE="/tmp/autopilot_wrapper.pid"
LOG_DIR="${REPO_ROOT}/logs/autopilot"
TODAY_LOG="${LOG_DIR}/$(date -u +%Y-%m-%d).log"
NOW_TS="$(date -u +%s)"
NOW_ISO="$(date -u +%FT%TZ)"
TG_NOTIFY="${REPO_ROOT}/scripts/autopilot/tg_notify.sh"
AUTOPILOT_JSON="${REPO_ROOT}/.claude/autopilot.json"

# R10: advisory lock — два cron-instance heartbeat не должны конкурентно
# писать state-file. Non-blocking: если уже идёт — этот тик молча выходит.
exec 8>"${HEARTBEAT_LOCK}"
if ! flock -n 8; then
  exit 0
fi

# ---- Read previous state (E4: paths через env) ----
PREV_STATE="$(STATE_FILE="${STATE_FILE}" python3 -c "
import json, os
try:
    with open(os.environ['STATE_FILE']) as f:
        d = json.load(f)
    print(d.get('state', 'unknown'))
except Exception:
    print('unknown')
")"
PREV_MILESTONE="$(STATE_FILE="${STATE_FILE}" python3 -c "
import json, os
try:
    with open(os.environ['STATE_FILE']) as f:
        d = json.load(f)
    print(d.get('milestone', 0))
except Exception:
    print(0)
")"
PREV_WRAPPER_ID="$(STATE_FILE="${STATE_FILE}" python3 -c "
import json, os
try:
    with open(os.environ['STATE_FILE']) as f:
        d = json.load(f)
    print(d.get('wrapper_id', ''))
except Exception:
    print('')
")"
PREV_PID="$(STATE_FILE="${STATE_FILE}" python3 -c "
import json, os
try:
    with open(os.environ['STATE_FILE']) as f:
        d = json.load(f)
    print(d.get('pid', ''))
except Exception:
    print('')
")"
PREV_LAST_END_TS="$(STATE_FILE="${STATE_FILE}" python3 -c "
import json, os
try:
    with open(os.environ['STATE_FILE']) as f:
        d = json.load(f)
    print(d.get('last_end_ts', 0))
except Exception:
    print(0)
")"

# ---- R5: detect current wrapper through PID-file (not pgrep) ----
WRAPPER_PID=""
WRAPPER_ID=""
if [[ -f "${WRAPPER_PID_FILE}" ]]; then
  CANDIDATE_PID="$(cat "${WRAPPER_PID_FILE}" 2>/dev/null | head -1 | tr -d ' \n')"
  if [[ -n "${CANDIDATE_PID}" ]] && [[ "${CANDIDATE_PID}" =~ ^[0-9]+$ ]]; then
    # Verify alive AND it's actually run_tick.sh (PID could be recycled)
    if kill -0 "${CANDIDATE_PID}" 2>/dev/null; then
      if [[ -r "/proc/${CANDIDATE_PID}/cmdline" ]]; then
        CMDLINE="$(tr '\0' ' ' < "/proc/${CANDIDATE_PID}/cmdline" 2>/dev/null || true)"
        if [[ "${CMDLINE}" == *"run_tick.sh"* ]]; then
          WRAPPER_PID="${CANDIDATE_PID}"
          # R6: wrapper_id = PID + start time из /proc/.../stat (стабильно, не зависит от логов)
          PROC_START_CLK="$(awk '{print $22}' "/proc/${CANDIDATE_PID}/stat" 2>/dev/null || echo 0)"
          WRAPPER_ID="${CANDIDATE_PID}-${PROC_START_CLK}"
        fi
      fi
    fi
  fi
fi

if [[ -n "${WRAPPER_PID}" ]]; then
  # Tick running. Compute elapsed minutes.
  ETIME_RAW="$(ps -p "${WRAPPER_PID}" -o etime= 2>/dev/null | tr -d ' ')"
  # etime format: MM:SS or HH:MM:SS or D-HH:MM:SS
  ELAPSED_MIN=$(ETIME_RAW="${ETIME_RAW}" python3 -c "
import os, re
s = os.environ['ETIME_RAW']
parts = re.split(r'[-:]', s) if s else ['0', '0']
nums = [int(x) for x in parts if x.isdigit()]
if len(nums) == 2:    mins = nums[0]
elif len(nums) == 3:  mins = nums[0]*60 + nums[1]
elif len(nums) == 4:  mins = nums[0]*1440 + nums[1]*60 + nums[2]
else: mins = 0
print(mins)
")
  CUR_STATE="running"

  # Compute milestone (5, 15, 25 minutes) — only ping ONCE per milestone
  # AND only if wrapper_id совпадает с previous (т.е. это тот же запуск)
  if [[ "${WRAPPER_ID}" != "${PREV_WRAPPER_ID}" ]]; then
    # Новый wrapper — сбрасываем milestone
    CUR_MILESTONE_PREV=0
  else
    CUR_MILESTONE_PREV=${PREV_MILESTONE}
  fi

  if   (( ELAPSED_MIN >= 25 )); then CUR_MILESTONE=25
  elif (( ELAPSED_MIN >= 15 )); then CUR_MILESTONE=15
  elif (( ELAPSED_MIN >= 5 ));  then CUR_MILESTONE=5
  else CUR_MILESTONE=0
  fi

  HEAD_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo ?)"

  # Ping on milestone increase
  if (( CUR_MILESTONE > CUR_MILESTONE_PREV )); then
    case "${CUR_MILESTONE}" in
      5)
        "${TG_NOTIFY}" "🟢 Автопилот идёт 5+ мин
PID: ${WRAPPER_PID}, head: ${HEAD_SHA}
Всё в порядке, продолжает работу." >/dev/null 2>&1
        ;;
      15)
        "${TG_NOTIFY}" "🟢 Автопилот идёт 15+ мин
PID: ${WRAPPER_PID}, head: ${HEAD_SHA}
Если ждёт твоего клика — проверь TG выше." >/dev/null 2>&1
        ;;
      25)
        "${TG_NOTIFY}" "⚠️ Автопилот идёт 25+ мин
PID: ${WRAPPER_PID}, head: ${HEAD_SHA}
До kill-timeout 30 мин осталось ~5 мин.
Если есть pending TG-вопрос — лучше ответить сейчас." >/dev/null 2>&1
        ;;
    esac
  fi

  NEW_STATE_PAYLOAD="{
    \"state\": \"running\",
    \"pid\": \"${WRAPPER_PID}\",
    \"wrapper_id\": \"${WRAPPER_ID}\",
    \"milestone\": ${CUR_MILESTONE},
    \"last_end_ts\": ${PREV_LAST_END_TS},
    \"updated\": \"${NOW_ISO}\"
  }"

else
  # No tick running. R6: detect crash through wrapper_id transition.
  # Если previously running И PREV_WRAPPER_ID был задан И нет MACRO-TICK end
  # для этого wrapper_id → crashed.
  if [[ "${PREV_STATE}" == "running" ]] && [[ -n "${PREV_WRAPPER_ID}" ]]; then
    # Check log for MACRO-TICK end with matching wrapper_id (если wrapper его пишет).
    # Wrapper при v3+ пишет «MACRO-TICK end final_rc=X wrapper_id=PID-CLK ...».
    LAST_MACRO_END="$(grep "MACRO-TICK end" "${TODAY_LOG}" 2>/dev/null | grep "wrapper_id=${PREV_WRAPPER_ID}" | tail -1)"
    # Fallback для wrapper'ов без wrapper_id в логе: смотрим последний MACRO-TICK end.
    if [[ -z "${LAST_MACRO_END}" ]]; then
      LAST_MACRO_END="$(grep "MACRO-TICK end\|CONTINUOUS exit" "${TODAY_LOG}" 2>/dev/null | tail -1)"
    fi

    if [[ -n "${LAST_MACRO_END}" ]] && { [[ "${LAST_MACRO_END}" =~ final_rc=0 ]] || [[ "${LAST_MACRO_END}" =~ reason=success ]] || [[ "${LAST_MACRO_END}" =~ reason=no-progress ]] || [[ "${LAST_MACRO_END}" =~ reason=pause-set ]] || [[ "${LAST_MACRO_END}" =~ reason=daily-budget ]]; } ; then
      CUR_STATE="idle"
      LAST_END_TS="${NOW_TS}"
    elif [[ -n "${LAST_MACRO_END}" ]]; then
      CUR_STATE="crashed"
      "${TG_NOTIFY}" "🔴 Автопилот завершился аномально
Был wrapper_id: ${PREV_WRAPPER_ID} (PID ${PREV_PID})
${LAST_MACRO_END}
См. ${TODAY_LOG}" >/dev/null 2>&1
      LAST_END_TS="${PREV_LAST_END_TS}"
    else
      # Process gone but log has no end at all → crashed silently
      CUR_STATE="crashed"
      "${TG_NOTIFY}" "🔴 Автопилот умер тихо
Был wrapper_id: ${PREV_WRAPPER_ID} (PID ${PREV_PID}), нет записи end в логе
См. ${TODAY_LOG}" >/dev/null 2>&1
      LAST_END_TS="${PREV_LAST_END_TS}"
    fi
  else
    # Already idle. Check for staleness (no activity 2h+ on weekday business hours).
    CUR_STATE="idle"
    LAST_END_TS="${PREV_LAST_END_TS:-${NOW_TS}}"

    HOURS_SINCE_LAST=$(NOW_TS="${NOW_TS}" LAST="${LAST_END_TS}" python3 -c "import os; print(int((int(os.environ['NOW_TS']) - int(os.environ['LAST'])) / 3600))")
    DOW="$(date +%u)"  # 1-7
    HOUR_MSK="$(TZ=Europe/Moscow date +%H)"

    # Stale-warning skip если автопилот явно выключен (enabled=false).
    ENABLED="$(AUTOPILOT_JSON="${AUTOPILOT_JSON}" python3 -c "
import json, os
try:
    print('true' if json.load(open(os.environ['AUTOPILOT_JSON'])).get('enabled') else 'false')
except Exception:
    print('true')
" 2>/dev/null)"

    if [[ "${ENABLED}" == "true" ]] && (( DOW <= 5 )) && (( HOUR_MSK >= 8 )) && (( HOUR_MSK <= 20 )); then
      if (( HOURS_SINCE_LAST >= 2 )) && [[ "${PREV_STATE}" != "stale" ]]; then
        "${TG_NOTIFY}" "😴 Автопилот не работал 2+ часов
Сейчас рабочее время. Cron должен срабатывать в 8:00 и 18:00 МСК.
Проверь crontab -l или ${TODAY_LOG}" >/dev/null 2>&1
        CUR_STATE="stale"
      fi
    fi
  fi

  CUR_MILESTONE=0
  NEW_STATE_PAYLOAD="{
    \"state\": \"${CUR_STATE}\",
    \"pid\": \"\",
    \"wrapper_id\": \"\",
    \"milestone\": 0,
    \"last_end_ts\": ${LAST_END_TS},
    \"updated\": \"${NOW_ISO}\"
  }"
fi

# ---- R10: atomic write state ----
TMP_STATE="${STATE_FILE}.tmp"
echo "${NEW_STATE_PAYLOAD}" > "${TMP_STATE}"
mv "${TMP_STATE}" "${STATE_FILE}"

# Debug log (только в случае изменения состояния)
if [[ "${PREV_STATE}" != "${CUR_STATE}" ]] || (( CUR_MILESTONE > PREV_MILESTONE )); then
  echo "[${NOW_ISO}] heartbeat: ${PREV_STATE} → ${CUR_STATE} (milestone ${PREV_MILESTONE}→${CUR_MILESTONE}) wrapper_id=${WRAPPER_ID:-${PREV_WRAPPER_ID}}" \
    >> "${LOG_DIR}/heartbeat.log"
fi
