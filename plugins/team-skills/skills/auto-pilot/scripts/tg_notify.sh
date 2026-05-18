#!/usr/bin/env bash
# Send a single Telegram message from the autopilot.
#
# Usage:
#   ./scripts/autopilot/tg_notify.sh "🤖 tick #5 started — Rule 1 → /sprint S14"
#
# Reads AUTOPILOT_TG_BOT_TOKEN and AUTOPILOT_TG_CHAT_ID from environment
# (sourced from .env.dev). Plain-text only — Telegram Markdown parsing is
# deliberately not used because `_`, `*`, `[`, slashes (`/auto-pilot`,
# `--dry-run`) frequently appear in autopilot text and cause HTTP 400.
#
# R16 fix: token проброшен в Python через env (не в argv для curl).
# `ps auxf` теперь не покажет token в process list.
#
# Failures are non-fatal: missing token/chat_id or network error → exit 0
# (with stderr note). The autopilot's primary path must never break because
# the side-channel is down.

set -uo pipefail

MSG="${1:-}"
if [[ -z "${MSG}" ]]; then
  echo "Usage: $0 <message>" >&2
  exit 2
fi

# Анти-шум: дропаем сообщения с <10 non-whitespace bytes (UTF-8 unicode aware).
# Ловит случаи когда автопилот пингует с пустыми/подстановочными переменными
# (рендерится в TG как «-» — раздражает).
MEANINGFUL_CHARS="$(MSG_VALUE="${MSG}" python3 -c 'import os; print(sum(1 for c in os.environ["MSG_VALUE"] if not c.isspace()))')"
if (( MEANINGFUL_CHARS < 10 )); then
  echo "tg_notify: dropping low-content msg (${MEANINGFUL_CHARS} chars meaningful): $(printf '%s' "${MSG}" | head -c 60)" >&2
  exit 0
fi

if [[ -z "${AUTOPILOT_TG_BOT_TOKEN:-}" || -z "${AUTOPILOT_TG_CHAT_ID:-}" ]]; then
  echo "tg_notify: AUTOPILOT_TG_BOT_TOKEN / AUTOPILOT_TG_CHAT_ID not set — skipped." >&2
  exit 0
fi

# R16: Python urllib — token не появляется в argv. soft fail на сети.
AUTOPILOT_TG_BOT_TOKEN="${AUTOPILOT_TG_BOT_TOKEN}" \
AUTOPILOT_TG_CHAT_ID="${AUTOPILOT_TG_CHAT_ID}" \
MSG_VALUE="${MSG}" \
python3 - <<'PY' || { echo "tg_notify: TG send failed (non-fatal)" >&2; exit 0; }
import os, sys, urllib.parse, urllib.request

token = os.environ["AUTOPILOT_TG_BOT_TOKEN"]
chat_id = os.environ["AUTOPILOT_TG_CHAT_ID"]
text = os.environ["MSG_VALUE"]

data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
url = f"https://api.telegram.org/bot{token}/sendMessage"
req = urllib.request.Request(url, data=data, method="POST")
try:
    with urllib.request.urlopen(req, timeout=8) as r:
        r.read()  # consume
except Exception as e:
    sys.stderr.write(f"tg_notify: send failed: {e}\n")
    sys.exit(1)
PY
