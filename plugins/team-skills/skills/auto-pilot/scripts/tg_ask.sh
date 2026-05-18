#!/usr/bin/env bash
# Send a question to the autopilot's TG channel with inline-keyboard buttons.
#
# Usage:
#   tg_ask.sh "<question text>" "Label1=callback1|Label2=callback2|Label3=callback3"
#
# Prints the message_id of the sent message to stdout. The autopilot then
# passes that message_id to `tg_wait_answer.sh` to block until the human clicks.
#
# Side-effect (E1 fix): пишет /tmp/autopilot_pending_asks/<msg_id>.json с
# label-map. Listener использует это для editMessageText на клике — потому что
# TG не включает inline_keyboard в callback_query.message по умолчанию.
#
# Validation (R13 fix): callback_data ограничен TG: 1-64 bytes. Слишком длинный
# или пустой → TG 400 → ask-flow ломается. Здесь валидируем до curl.
#
# Inline buttons rather than plain-text replies because:
#   1. Phone-friendly (tap one button vs typing)
#   2. callback_data is unambiguous (no parsing «да/нет/yes/no»)
#   3. Telegram delivers callback even if user is on Telegram Desktop or Web
#
# Requires AUTOPILOT_TG_BOT_TOKEN and AUTOPILOT_TG_CHAT_ID in env (.env.dev).

set -uo pipefail

TEXT="${1:-}"
BUTTONS="${2:-}"

if [[ -z "${TEXT}" || -z "${BUTTONS}" ]]; then
  echo "Usage: $0 <text> 'Label1=cb1|Label2=cb2[|Label3=cb3]'" >&2
  exit 2
fi

if [[ -z "${AUTOPILOT_TG_BOT_TOKEN:-}" || -z "${AUTOPILOT_TG_CHAT_ID:-}" ]]; then
  echo "tg_ask: AUTOPILOT_TG_BOT_TOKEN / AUTOPILOT_TG_CHAT_ID not set" >&2
  exit 3
fi

PENDING_ASKS_DIR="/tmp/autopilot_pending_asks"
mkdir -p "${PENDING_ASKS_DIR}"

# Build inline_keyboard JSON + parallel label-map (E1).
# Validate callback_data byte-length 1..64 (R13).
KEYBOARD_DATA="$(BUTTONS_RAW="${BUTTONS}" python3 -c '
import json, os, sys
raw = os.environ["BUTTONS_RAW"]
buttons = []
labels = {}
for pair in raw.split("|"):
    pair = pair.strip()
    if "=" not in pair:
        sys.stderr.write(f"bad button spec (need Label=callback): {pair!r}\n")
        sys.exit(2)
    label, cb = pair.split("=", 1)
    label = label.strip()
    cb = cb.strip()
    # R13: callback_data must be 1-64 bytes UTF-8
    cb_bytes = cb.encode("utf-8")
    if not cb_bytes:
        sys.stderr.write(f"callback_data empty for label={label!r}\n")
        sys.exit(3)
    if len(cb_bytes) > 64:
        sys.stderr.write(f"callback_data {cb!r} too long ({len(cb_bytes)} bytes, max 64)\n")
        sys.exit(4)
    if not label:
        sys.stderr.write(f"label empty for callback={cb!r}\n")
        sys.exit(5)
    buttons.append({"text": label, "callback_data": cb})
    labels[cb] = label
total_chars = sum(len(b["text"]) for b in buttons)
if total_chars > 30:
    rows = [[b] for b in buttons]
else:
    rows = [buttons]
print(json.dumps({"keyboard": {"inline_keyboard": rows}, "labels": labels}, ensure_ascii=False))
')" || {
  echo "tg_ask: keyboard validation failed" >&2
  exit 4
}

KEYBOARD_JSON="$(echo "${KEYBOARD_DATA}" | python3 -c 'import json,sys; print(json.dumps(json.loads(sys.stdin.read())["keyboard"], ensure_ascii=False))')"
LABELS_JSON="$(echo "${KEYBOARD_DATA}" | python3 -c 'import json,sys; print(json.dumps(json.loads(sys.stdin.read())["labels"], ensure_ascii=False))')"

RESP="$(curl -fsSL --max-time 10 -X POST \
  "https://api.telegram.org/bot${AUTOPILOT_TG_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${AUTOPILOT_TG_CHAT_ID}" \
  --data-urlencode "text=${TEXT}" \
  --data-urlencode "reply_markup=${KEYBOARD_JSON}")" || {
  echo "tg_ask: TG send failed" >&2
  exit 5
}

MSG_ID="$(RESP="${RESP}" python3 -c '
import json, os, sys
d = json.loads(os.environ["RESP"])
if not d.get("ok"):
    sys.stderr.write(f"TG error: {d}\n"); sys.exit(1)
print(d["result"]["message_id"])
')" || exit 6

# E1: persist label-map for listener to use on callback edit.
# Atomic write — listener может прочитать в любой момент.
PENDING_FILE="${PENDING_ASKS_DIR}/${MSG_ID}.json"
TMP_FILE="${PENDING_FILE}.tmp"
LABELS="${LABELS_JSON}" python3 -c '
import json, os
labels = json.loads(os.environ["LABELS"])
with open("'"${TMP_FILE}"'", "w") as f:
    json.dump({"buttons": labels, "msg_id": '"${MSG_ID}"'}, f, ensure_ascii=False)
' && mv "${TMP_FILE}" "${PENDING_FILE}"

echo "${MSG_ID}"
