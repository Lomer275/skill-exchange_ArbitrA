#!/usr/bin/env bash
# Autopilot installer — разворачивает скрипты + конфиг + cron на пользовательской машине.
#
# Запускать ОДИН РАЗ после `pull` из skill-exchange.
# Идемпотентен: повторный запуск не ломает уже настроенное.
#
# Шаги:
#   1. Найти REPO_ROOT (cwd должен быть git-репо проекта).
#   2. Скопировать scripts/* в ${REPO_ROOT}/scripts/autopilot/.
#   3. Скопировать templates/autopilot.json в ${REPO_ROOT}/.claude/autopilot.json (если нет).
#   4. Скопировать templates/.env.template — спросить TG credentials интерактивно.
#   5. Опционально: cron entry на 0 5,15 * * 1-5 (08:00 + 18:00 МСК).
#   6. Опционально: heartbeat cron */2 * * * *.
#   7. Запустить listener в фоне.
#
# Все шаги опциональны (с подтверждением). Можно прервать CTRL+C.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

if [[ ! -d "${REPO_ROOT}/.git" ]]; then
  echo "❌ ${REPO_ROOT} не похож на git-репо. Запусти install.sh из корня проекта." >&2
  exit 1
fi

echo "🚀 Autopilot installer"
echo "   Source: ${SKILL_DIR}"
echo "   Target: ${REPO_ROOT}"
echo

# ---- Шаг 1: scripts/autopilot/ ----
DST_SCRIPTS="${REPO_ROOT}/scripts/autopilot"
echo "1. Копирую scripts → ${DST_SCRIPTS}"
mkdir -p "${DST_SCRIPTS}"
cp -p "${SKILL_DIR}/scripts/"*.sh "${DST_SCRIPTS}/" 2>/dev/null || true
cp -p "${SKILL_DIR}/scripts/"*.py "${DST_SCRIPTS}/" 2>/dev/null || true
chmod +x "${DST_SCRIPTS}"/*.sh "${DST_SCRIPTS}"/*.py 2>/dev/null || true

# path-overrides для git-guard
mkdir -p "${DST_SCRIPTS}/path-overrides"
ln -sf "${DST_SCRIPTS}/git-guard.sh" "${DST_SCRIPTS}/path-overrides/git"
echo "   ✓ Scripts copied + path-overrides/git → git-guard.sh symlink"

# ---- Шаг 2: autopilot.json config ----
DST_CONFIG="${REPO_ROOT}/.claude/autopilot.json"
if [[ -f "${DST_CONFIG}" ]]; then
  echo "2. .claude/autopilot.json уже существует — оставляю как есть."
else
  mkdir -p "${REPO_ROOT}/.claude"
  cp -p "${SKILL_DIR}/templates/autopilot.json" "${DST_CONFIG}"
  echo "2. ✓ .claude/autopilot.json создан с defaults (enabled=false)"
fi

# ---- Шаг 3: .env с TG credentials ----
echo
echo "3. TG-bot creds (для escalation/control)"
if [[ -f "${REPO_ROOT}/.env.dev" ]] && grep -q "^AUTOPILOT_TG_BOT_TOKEN=" "${REPO_ROOT}/.env.dev"; then
  echo "   .env.dev уже содержит AUTOPILOT_TG_* — пропускаю."
else
  echo "   Нужен TG-bot чтобы автопилот мог писать/спрашивать."
  echo "   Если у тебя его ещё нет — создай через @BotFather в Telegram:"
  echo "     1) /newbot → имя + username"
  echo "     2) Скопируй token (формат: NNNNNN:AAA...)"
  echo "     3) В TG: отправь /start своему боту от своего аккаунта"
  echo
  read -rp "   Введи AUTOPILOT_TG_BOT_TOKEN (или ENTER чтобы пропустить): " TG_TOKEN
  if [[ -n "${TG_TOKEN}" ]]; then
    read -rp "   Введи свой @username (без @, например Lobster_21): " TG_USERNAME
    TG_USERNAME="${TG_USERNAME:-anonymous}"

    ENV_FILE="${REPO_ROOT}/.env.dev"
    cat >> "${ENV_FILE}" <<EOF

# Autopilot TG control (added by install.sh)
AUTOPILOT_TG_BOT_TOKEN=${TG_TOKEN}
AUTOPILOT_TG_ALLOWED_USERNAME=${TG_USERNAME}
AUTOPILOT_TG_CHAT_ID=
AUTOPILOT_TG_ALLOWED_USER_ID=
EOF
    echo "   ✓ Token + username записаны в ${ENV_FILE}"
    echo "   Запускаю discover_chat_id.sh — заполнит chat_id + user_id из последнего сообщения от @${TG_USERNAME}…"
    cd "${REPO_ROOT}" && "${DST_SCRIPTS}/discover_chat_id.sh" || echo "   ⚠️ discover не нашёл сообщение — отправь /start боту и запусти ${DST_SCRIPTS}/discover_chat_id.sh вручную"
  else
    echo "   ⚠️ Пропустил TG setup. Без него /auto-pilot не сможет писать в TG."
    echo "      Заполни .env.dev руками (см. .env.template) когда будешь готов."
  fi
fi

# ---- Шаг 4: cron entries ----
echo
read -rp "4. Установить cron (autopilot 8:00+18:00 МСК + heartbeat /2min)? [y/N]: " INSTALL_CRON
if [[ "${INSTALL_CRON,,}" == "y" ]]; then
  CURRENT_CRON="$(crontab -l 2>/dev/null || true)"
  if echo "${CURRENT_CRON}" | grep -q "autopilot/run_tick.sh"; then
    echo "   Cron уже содержит autopilot/run_tick.sh — пропускаю."
  else
    NEW_CRON="${CURRENT_CRON}
# Autopilot (08:00 + 18:00 МСК, пн-пт)
0 5,15 * * 1-5 ${DST_SCRIPTS}/run_tick.sh
# Autopilot heartbeat watchdog
*/2 * * * * ${DST_SCRIPTS}/heartbeat.sh >> ${REPO_ROOT}/logs/autopilot/heartbeat-cron.log 2>&1"
    echo "${NEW_CRON}" | crontab -
    echo "   ✓ Cron установлен. crontab -l для проверки."
  fi
fi

# ---- Шаг 5: listener daemon ----
echo
read -rp "5. Запустить TG-listener сейчас в фоне? [y/N]: " START_LISTENER
if [[ "${START_LISTENER,,}" == "y" ]]; then
  mkdir -p "${REPO_ROOT}/logs/autopilot"
  cd "${REPO_ROOT}"
  setsid nohup python3 "${DST_SCRIPTS}/tg_listener.py" >> "${REPO_ROOT}/logs/autopilot/listener.log" 2>&1 < /dev/null & disown
  sleep 2
  LISTENER_PID="$(pgrep -af 'tg_listener.py' | head -1 | awk '{print $1}')"
  if [[ -n "${LISTENER_PID}" ]]; then
    echo "   ✓ Listener PID ${LISTENER_PID} запущен. Tail логи: tail -f logs/autopilot/listener.log"
  else
    echo "   ⚠️ Listener не стартовал — проверь logs/autopilot/listener.log"
  fi
fi

echo
echo "✅ Установка закончена."
echo
echo "Дальше:"
echo "  • Открой бота в TG и пиши /help — увидишь команды управления"
echo "  • Прочитай SKILL.md для архитектуры и контрактов"
echo "  • Прочитай README.md для day-to-day операций"
echo "  • Включить автопилот: /enable в TG (или флипни enabled=true в .claude/autopilot.json)"
