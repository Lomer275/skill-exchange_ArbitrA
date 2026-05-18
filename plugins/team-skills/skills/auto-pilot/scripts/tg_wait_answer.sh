#!/usr/bin/env bash
# Block until tg_listener.py writes a callback answer to /tmp/autopilot_answers/<msg_id>.json.
#
# Usage:
#   tg_wait_answer.sh <message_id> [timeout_seconds] [poll_interval_seconds]
#
# Defaults:
#   timeout_seconds       = 480    (8 min — под Bash-tool hard cap 600s)
#   poll_interval_seconds = 3      (filesystem poll, очень дёшево)
#
# Архитектура (после фикса tg_listener ↔ tg_wait_answer collision, 2026-05-14):
#   tg_listener.py — единственный owner Telegram getUpdates API.
#   На callback_query пишет /tmp/autopilot_answers/<msg_id>.json (atomic rename)
#   и вызывает answerCallbackQuery (спиннер пропадает).
#   Этот скрипт просто polls filesystem — никаких TG-API вызовов.
#
# R9 fix: TARGET_MSG_ID валидируется по regex ^[0-9]+$ — Telegram message_id
# всегда integer. Путь передаётся через env var, не интерполируется в Python код.
#
# Sub-agent контракт (Bash-tool hard cap 600s):
#   Если rc=1 (timeout), вызови снова. /sprint SKILL.md инструктирует
#   до 12 итераций (=96 мин wait total). После — задача blocked.
#
# Print to stdout: callback_data ("yes" / "no" / "skip") on success.
# Exit 0=got answer, 1=timeout, 2+=usage/env error.

set -uo pipefail

TARGET_MSG_ID="${1:-}"
TIMEOUT="${2:-480}"
POLL_INTERVAL="${3:-3}"

# R9: strict validation of TARGET_MSG_ID (защита от Python injection в heredoc).
if [[ -z "${TARGET_MSG_ID}" ]]; then
  echo "Usage: $0 <message_id> [timeout_seconds] [poll_interval_seconds]" >&2
  exit 2
fi
if ! [[ "${TARGET_MSG_ID}" =~ ^[0-9]+$ ]]; then
  echo "tg_wait_answer: message_id must be integer, got: ${TARGET_MSG_ID}" >&2
  exit 2
fi
if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]]; then
  echo "tg_wait_answer: timeout must be integer, got: ${TIMEOUT}" >&2
  exit 2
fi
if ! [[ "${POLL_INTERVAL}" =~ ^[0-9]+$ ]]; then
  echo "tg_wait_answer: poll_interval must be integer, got: ${POLL_INTERVAL}" >&2
  exit 2
fi

ANSWERS_DIR="/tmp/autopilot_answers"
ANSWER_FILE="${ANSWERS_DIR}/${TARGET_MSG_ID}.json"

mkdir -p "${ANSWERS_DIR}"

DEADLINE=$(( $(date +%s) + TIMEOUT ))

while true; do
  if [[ -f "${ANSWER_FILE}" ]]; then
    # R9: путь передаётся через env, не интерполяция в Python.
    DATA="$(ANSWER_FILE="${ANSWER_FILE}" python3 -c "
import json, os, sys
try:
    with open(os.environ['ANSWER_FILE']) as f:
        d = json.load(f)
    print(d.get('data', ''))
except Exception as e:
    sys.stderr.write(f'parse error: {e}\n')
    sys.exit(2)
")" || exit 3

    rm -f "${ANSWER_FILE}" 2>/dev/null
    if [[ -z "${DATA}" ]]; then
      echo "tg_wait_answer: empty data in ${ANSWER_FILE}" >&2
      exit 4
    fi
    echo "${DATA}"
    exit 0
  fi

  NOW="$(date +%s)"
  if (( NOW >= DEADLINE )); then
    echo "tg_wait_answer: timeout (no file ${ANSWER_FILE} after ${TIMEOUT}s)" >&2
    exit 1
  fi

  REMAINING=$(( DEADLINE - NOW ))
  if (( REMAINING < POLL_INTERVAL )); then
    sleep "${REMAINING}"
  else
    sleep "${POLL_INTERVAL}"
  fi
done
