#!/usr/bin/env bash
# Resolve the human's TG chat_id (+ user_id, R2) for /auto-pilot escalations.
#
# Run this once after creating the bot:
#   1. Open https://t.me/ClaudeCode_autopilot_Arbitra_bot in Telegram
#   2. Send /start (or any message) to the bot from your account (@Lobster_21)
#   3. Run this script — оно (R17) пишет ОБА (chat_id + user_id) прямо в .env.dev,
#      без шумного stdout (chat_id — authz-bound identifier, не светим).
#
# Token читается из .env.dev. Token намеренно не печатается в stdout/stderr.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env.dev"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "❌ ${ENV_FILE} not found" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

if [[ -z "${AUTOPILOT_TG_BOT_TOKEN:-}" ]]; then
  echo "❌ AUTOPILOT_TG_BOT_TOKEN not set in ${ENV_FILE}" >&2
  exit 1
fi

ALLOWED="${AUTOPILOT_TG_ALLOWED_USERNAME:-Lobster_21}"

echo "🔎 Fetching recent updates from the autopilot bot…"
echo "    (looking for messages from @${ALLOWED})"

# R16-style: token через env, не в URL argv. Используем Python urllib.
RESPONSE="$(AUTOPILOT_TG_BOT_TOKEN="${AUTOPILOT_TG_BOT_TOKEN}" python3 - <<'PY'
import json, os, sys, urllib.request
token = os.environ["AUTOPILOT_TG_BOT_TOKEN"]
try:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10) as r:
        sys.stdout.write(r.read().decode())
except Exception as e:
    sys.stderr.write(f"getUpdates failed: {e}\n")
    sys.exit(1)
PY
)" || exit 1

# Extract BOTH chat_id and user_id (R2: user_id для strong auth).
RESULT="$(ALLOWED="${ALLOWED}" RESPONSE="${RESPONSE}" python3 -c '
import json, os, sys
allowed = os.environ["ALLOWED"].lstrip("@").lower()
data = json.loads(os.environ["RESPONSE"])
if not data.get("ok"):
    sys.stderr.write(f"❌ Telegram API error: {data}\n"); sys.exit(2)
chat_id = None
user_id = None
for upd in data.get("result", []):
    msg = upd.get("message") or upd.get("edited_message") or {}
    frm = msg.get("from") or {}
    if (frm.get("username") or "").lower() == allowed:
        chat_id = msg.get("chat", {}).get("id")
        user_id = frm.get("id")
        break
if chat_id is None or user_id is None:
    sys.stderr.write(f"❌ No message from @{allowed} found in recent updates.\n")
    sys.stderr.write(f"   Send /start to the bot from @{allowed} and re-run.\n")
    sys.exit(3)
print(f"{chat_id} {user_id}")
')" || exit $?

CHAT_ID="${RESULT% *}"
USER_ID="${RESULT#* }"

# R17: пишем прямо в .env.dev (idempotent) вместо печати в stdout/shell history.
# Используем atomic write через tmp + mv.
TMP_ENV="${ENV_FILE}.tmp"
ENV_FILE_IN="${ENV_FILE}" CHAT_ID="${CHAT_ID}" USER_ID="${USER_ID}" python3 - <<'PY' > "${TMP_ENV}"
import os
env_in = os.environ["ENV_FILE_IN"]
chat_id = os.environ["CHAT_ID"]
user_id = os.environ["USER_ID"]
keys_to_set = {
    "AUTOPILOT_TG_CHAT_ID": chat_id,
    "AUTOPILOT_TG_ALLOWED_USER_ID": user_id,
}
seen = set()
with open(env_in) as f:
    for line in f:
        s = line.rstrip("\n")
        replaced = False
        for k, v in keys_to_set.items():
            if s.startswith(f"{k}="):
                print(f"{k}={v}")
                seen.add(k)
                replaced = True
                break
        if not replaced:
            print(s)
# Append keys that werent in file
for k, v in keys_to_set.items():
    if k not in seen:
        print(f"{k}={v}")
PY

mv "${TMP_ENV}" "${ENV_FILE}"

echo "✅ chat_id и user_id записаны в ${ENV_FILE}"
echo "   AUTOPILOT_TG_CHAT_ID и AUTOPILOT_TG_ALLOWED_USER_ID обновлены"
echo
echo "Listener'у нужен рестарт чтобы подхватить:"
echo "   pkill -f tg_listener.py && nohup python3 scripts/autopilot/tg_listener.py >> logs/autopilot/listener.log 2>&1 &"
