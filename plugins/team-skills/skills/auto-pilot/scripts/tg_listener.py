#!/usr/bin/env python3
"""Autopilot TG control daemon — listens for slash-commands from authorized user.

Architecture:
    Long-poll Telegram getUpdates → match `/command` from @Lobster_21 → dispatch
    handler → reply in same chat.

Authorized user: AUTOPILOT_TG_ALLOWED_USERNAME (single human, hard-checked by
username, not just chat_id, to survive account-id changes).

Why Python:
    - Cleaner dispatch table than bash case-stmt
    - Easier JSON handling for autopilot.json / log files
    - Subprocess management for /sprint and /abort

Run via systemd (autopilot-tg-listener.service) — restart on fail.

Manually:
    python3 scripts/autopilot/tg_listener.py
        --offset-file /tmp/autopilot_listener_offset
        --once          # process one update batch and exit (smoke-test)

Logs: stdout/stderr go to systemd journal (or logs/autopilot/listener.log if --log).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# -------- Configuration --------

REPO_ROOT = Path(__file__).resolve().parents[2]
HANDOFF_PATH = REPO_ROOT / "SUP-HANDOFF.md"
AUTOPILOT_JSON = REPO_ROOT / ".claude" / "autopilot.json"
AUTOPILOT_LOG = REPO_ROOT / "docs" / "5. SUP-unsorted" / "autopilot_log.md"
HEARTBEAT_STATE = Path("/tmp/autopilot_heartbeat_state.json")
RUN_TICK = REPO_ROOT / "scripts" / "autopilot" / "run_tick.sh"
TG_NOTIFY = REPO_ROOT / "scripts" / "autopilot" / "tg_notify.sh"
WRAPPER_LOCK = REPO_ROOT / ".claude" / "autopilot.lock"
WRAPPER_PID_FILE = Path("/tmp/autopilot_wrapper.pid")  # R5/R6: PID-aware scope для /abort
DEFAULT_OFFSET_FILE = Path("/tmp/autopilot_listener_offset")

# Callback answers state-dir. Listener — sole owner of TG getUpdates API.
# При получении callback_query пишем сюда {message_id}.json с полем `data`.
# tg_wait_answer.sh читает отсюда вместо API (избегаем 409 Conflict).
ANSWERS_DIR = Path("/tmp/autopilot_answers")
ANSWERS_DIR.mkdir(exist_ok=True)

# E1: храним label-map для message_id перед отправкой вопроса. tg_ask.sh пишет
# сюда вместе с MSG_ID, listener читает при обработке callback (т.к. TG не
# включает inline_keyboard в callback_query.message по умолчанию).
PENDING_ASKS_DIR = Path("/tmp/autopilot_pending_asks")
PENDING_ASKS_DIR.mkdir(exist_ok=True)

# R11: idempotency — храним последний обработанный update_id и список свежих
# callback_query.id (последние 1000) чтобы не дублировать после listener restart.
# Структура: {"last_offset": N, "seen_callback_ids": [id1, id2, ...]}
IDEMPOTENCY_FILE = Path("/tmp/autopilot_listener_idem.json")
_IDEM_CALLBACK_HISTORY_SIZE = 1000

# -------- Helpers --------

log = logging.getLogger("tg_listener")


def tg_api(token: str, method: str, params: dict[str, Any] | None = None, timeout: int = 30) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def send_message(token: str, chat_id: str, text: str, reply_markup: str | None = None) -> int | None:
    try:
        params = {"chat_id": chat_id, "text": text}
        if reply_markup:
            params["reply_markup"] = reply_markup
        d = tg_api(token, "sendMessage", params, timeout=10)
        if d.get("ok"):
            return d["result"]["message_id"]
    except Exception as e:
        log.warning("send_message failed: %s", e)
    return None


# Persistent reply-keyboard внизу TG-клиента. Каждая нажатая кнопка отправляет
# свой text как обычное сообщение — listener ловит через тот же dispatch и
# мапит на slash-команду через _RESERVED_KEYBOARD_LABELS.
_REPLY_KEYBOARD = {
    "keyboard": [
        [{"text": "🟢 Статус"}, {"text": "📋 Лог"}],
        [{"text": "⏸ Пауза"}, {"text": "▶️ Resume"}],
        [{"text": "🔴 Disable"}, {"text": "🟢 Enable"}],
        [{"text": "🚀 Sprint"}, {"text": "💰 Бюджет"}],
        [{"text": "❤️ Heartbeat"}, {"text": "🛑 Abort"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
    "input_field_placeholder": "Команда или текст…",
}

_BUTTON_TO_CMD = {
    "🟢 Статус": "/status",
    "📋 Лог": "/log",
    "⏸ Пауза": "/pause",
    "▶️ Resume": "/resume",
    "🔴 Disable": "/disable",
    "🟢 Enable": "/enable",
    "🚀 Sprint": "/sprint",
    "💰 Бюджет": "/budget",
    "❤️ Heartbeat": "/heartbeat",
    "🛑 Abort": "/abort",
}


def run_cmd(args: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str, str]:
    """Subprocess wrapper. Returns (rc, stdout, stderr)."""
    try:
        r = subprocess.run(
            args, cwd=cwd or REPO_ROOT, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


# -------- Command handlers --------
# Each handler: (token, chat_id, args_string) -> reply_text


def cmd_help(token: str, chat_id: str, args: str) -> str:
    return (
        "Команды автопилота:\n"
        "/help — этот список\n"
        "/status — текущее состояние (тик, прогресс, последний коммит)\n"
        "/log [N] — последние N записей из autopilot_log.md (default 1)\n"
        "/enable — включить автопилот (ticks полные)\n"
        "/disable — выключить (kill-switch в .claude/autopilot.json)\n"
        "/pause [причина] — мягкая пауза через ⛔ AUTOPILOT_PAUSE в HANDOFF\n"
        "/resume — снять паузу\n"
        "/sprint <SXX> — записать директиву и запустить тик прямо сейчас\n"
        "/abort — убить активный тик\n"
        "/budget — счётчики дня + остаток бюджета\n"
        "/heartbeat — пнуть watchdog вручную"
    )


def cmd_enable(token: str, chat_id: str, args: str) -> str:
    try:
        d = json.loads(AUTOPILOT_JSON.read_text())
        d["enabled"] = True
        d["disabled_reason"] = None
        d["disabled_at"] = None
        AUTOPILOT_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2))
        return "🟢 Автопилот включён.\nCron в 08:00 + 18:00 МСК подхватит работу.\nИли /sprint <SXX> прямо сейчас."
    except Exception as e:
        return f"❌ Не смог обновить autopilot.json: {e}"


def cmd_disable(token: str, chat_id: str, args: str) -> str:
    reason = args.strip() or "manual via TG"
    try:
        d = json.loads(AUTOPILOT_JSON.read_text())
        d["enabled"] = False
        d["disabled_reason"] = reason
        d["disabled_at"] = datetime.now(timezone.utc).isoformat()
        AUTOPILOT_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2))
        return (
            f"🔴 Автопилот выключен.\n"
            f"Причина: {reason}\n"
            f"Cron-тики будут exit'ить на Phase 0 без действий.\n"
            f"Heartbeat не будет жаловаться на «не работал 2+ часов».\n"
            f"/enable — вернуть."
        )
    except Exception as e:
        return f"❌ Не смог обновить autopilot.json: {e}"


def cmd_status(token: str, chat_id: str, args: str) -> str:
    # 1. Heartbeat state
    hb_state = "unknown"
    hb_pid = ""
    try:
        d = json.loads(HEARTBEAT_STATE.read_text())
        hb_state = d.get("state", "unknown")
        hb_pid = d.get("pid", "")
    except Exception:
        pass

    # 2. Autopilot config (enabled, budget)
    enabled = "?"
    ticks_today = "?"
    tokens_today = "?"
    try:
        d = json.loads(AUTOPILOT_JSON.read_text())
        enabled = d.get("enabled", "?")
        ticks_today = d.get("ticks_today", 0)
        tokens_today = d.get("tokens_today", 0)
    except Exception:
        pass

    # 3. Git state
    rc, head_short, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"])
    rc2, head_msg, _ = run_cmd(["git", "log", "-1", "--format=%s"])
    rc3, branch, _ = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    head_short = head_short.strip() if rc == 0 else "?"
    head_msg = head_msg.strip()[:80] if rc2 == 0 else ""
    branch = branch.strip() if rc3 == 0 else "?"

    # 4. Last tick from log — используем cache.
    last_tick = "нет записей"
    entries = _read_log_entries()
    if entries:
        first_line = entries[0].split("\n", 1)[0]
        if first_line.startswith("## "):
            last_tick = first_line.lstrip("# ").strip()

    # 5. AUTOPILOT_PAUSE check
    pause_line = ""
    try:
        h = HANDOFF_PATH.read_text()
        for ln in h.splitlines()[:5]:
            if "AUTOPILOT_PAUSE" in ln:
                pause_line = ln.strip()
                break
    except Exception:
        pass

    state_emoji = {"running": "🟢", "idle": "😴", "crashed": "🔴", "stale": "⚠️", "unknown": "❔"}.get(hb_state, "❔")

    parts = [
        f"{state_emoji} Состояние: {hb_state}" + (f" (PID {hb_pid})" if hb_pid else ""),
        f"Ветка: {branch} @ {head_short}",
        f"Последний коммит: {head_msg}",
        f"Последний тик в логе: {last_tick}",
        f"Автопилот: enabled={enabled}, ticks_today={ticks_today}, tokens_today={tokens_today}",
    ]
    if pause_line:
        parts.append(f"\n{pause_line}")
    return "\n".join(parts)


# E3 perf: in-memory cache последних N entries из autopilot_log.md
# Invalidate by mtime. Без cache каждый /log парсит весь файл (с ростом — медленно).
_LOG_CACHE: dict = {"mtime": None, "entries": None}
_LOG_CACHE_MAX_ENTRIES = 10  # хватит для cmd_log с cap 5


def _read_log_entries() -> list[str]:
    """Возвращает список tick-entries из autopilot_log.md, самые свежие первыми.
    Кеширует по mtime — пересчёт только если файл изменён.
    """
    try:
        stat = AUTOPILOT_LOG.stat()
    except FileNotFoundError:
        return []
    if _LOG_CACHE["mtime"] == stat.st_mtime and _LOG_CACHE["entries"] is not None:
        return _LOG_CACHE["entries"]

    try:
        text = AUTOPILOT_LOG.read_text()
    except Exception as e:
        log.error("autopilot_log read failed: %s", e)
        return []
    entries: list[str] = []
    buf: list[str] = []
    for ln in text.splitlines():
        if ln.startswith("## "):
            if buf and buf[0].startswith("## "):
                entries.append("\n".join(buf))
                if len(entries) >= _LOG_CACHE_MAX_ENTRIES:
                    break
            buf = [ln]
        elif buf:
            buf.append(ln)
    if buf and buf[0].startswith("## ") and len(entries) < _LOG_CACHE_MAX_ENTRIES:
        entries.append("\n".join(buf))

    _LOG_CACHE["mtime"] = stat.st_mtime
    _LOG_CACHE["entries"] = entries
    return entries


def cmd_log(token: str, chat_id: str, args: str) -> str:
    try:
        n = int(args.strip()) if args.strip() else 1
    except ValueError:
        n = 1
    n = max(1, min(n, 5))  # cap 5 — TG msg limit
    entries = _read_log_entries()
    if not entries:
        return "Лог пуст."
    out = "\n\n---\n\n".join(entries[:n])
    if len(out) > 3500:
        out = out[:3500] + "\n\n[...обрезано, см. файл полностью в autopilot_log.md]"
    return out


def cmd_pause(token: str, chat_id: str, args: str) -> str:
    reason = args.strip() or "вручную через TG"
    try:
        text = HANDOFF_PATH.read_text()
    except Exception as e:
        return f"❌ HANDOFF не читается: {e}"
    if "AUTOPILOT_PAUSE" in text.split("\n")[0:10][0:50] or any(
        "AUTOPILOT_PAUSE" in ln for ln in text.splitlines()[:10]
    ):
        return "⏸️ Уже на паузе. /resume чтобы снять."
    new = f"⛔ AUTOPILOT_PAUSE — {reason} ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%MZ')})\n\n" + text
    HANDOFF_PATH.write_text(new)
    return f"⏸️ Поставил паузу. Причина: {reason}\nСледующий тик увидит флаг и не будет лезть. /resume чтобы снять."


def cmd_resume(token: str, chat_id: str, args: str) -> str:
    try:
        text = HANDOFF_PATH.read_text()
    except Exception as e:
        return f"❌ HANDOFF не читается: {e}"
    lines = text.splitlines(keepends=True)
    new_lines = []
    removed = False
    for ln in lines:
        if not removed and "AUTOPILOT_PAUSE" in ln:
            removed = True
            continue
        new_lines.append(ln)
    if not removed:
        return "▶️ Паузы не было. Уже работаем."
    # Strip leading blank lines that may now be left
    while new_lines and new_lines[0].strip() == "":
        new_lines.pop(0)
    HANDOFF_PATH.write_text("".join(new_lines))
    return "▶️ Снял паузу. Cron сработает в свой час, или /sprint SXX чтобы прямо сейчас."


_SPEC_RE = re.compile(r"^S\d{2,3}$")


def _write_handoff_directive(spec: str) -> bool:
    """R3: Запиши директиву в HANDOFF чтобы /sprint --yes <SXX> реально запустился
    с правильной спекой. Заменяет существующую директиву в секции
    «## 🤖 Автопилот: следующее», вставляя `/sprint --yes <SXX>` первой
    строкой ниже заголовка. Atomic write.
    """
    try:
        text = HANDOFF_PATH.read_text()
    except Exception as e:
        log.error("HANDOFF read failed: %s", e)
        return False

    # Find section "## 🤖 Автопилот: следующее" — replace immediately-following
    # directive line (the first non-blank line after the heading).
    new_directive = f"**`/sprint --yes {spec}`** — установлено через TG `/sprint {spec}` в {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%MZ')}.\n"

    lines = text.splitlines(keepends=True)
    new_lines = []
    in_section = False
    directive_replaced = False
    for ln in lines:
        new_lines.append(ln)
        if ln.startswith("## 🤖 Автопилот"):
            in_section = True
            continue
        if in_section and not directive_replaced and ln.strip().startswith("**`/sprint"):
            # Replace the existing directive line
            new_lines[-1] = new_directive + "\n"
            directive_replaced = True
            in_section = False
        elif in_section and ln.startswith("## "):
            # Hit next section without finding a directive — insert before it
            if not directive_replaced:
                new_lines.insert(len(new_lines) - 1, "\n" + new_directive + "\n")
                directive_replaced = True
            in_section = False

    if not directive_replaced:
        log.warning("HANDOFF: could not find '## 🤖 Автопилот' section, prepending fallback")
        # Fallback: prepend a fresh section before the first heading
        new_text = f"## 🤖 Автопилот: следующее\n\n{new_directive}\n" + text
        try:
            HANDOFF_PATH.write_text(new_text)
            return True
        except Exception as e:
            log.error("HANDOFF write failed: %s", e)
            return False

    try:
        # Atomic-ish: write to tmp, rename
        tmp = HANDOFF_PATH.with_suffix(".md.tmp")
        tmp.write_text("".join(new_lines))
        tmp.replace(HANDOFF_PATH)
        return True
    except Exception as e:
        log.error("HANDOFF write failed: %s", e)
        return False


def cmd_sprint(token: str, chat_id: str, args: str) -> str:
    """R3: реально пишет директиву `/sprint --yes <SXX>` в HANDOFF чтобы
    спавнящийся wrapper подхватил нужную спеку через Rule 1."""
    spec = args.strip().upper()
    if not _SPEC_RE.match(spec):
        return "❌ Формат: /sprint S14 (требуется ID вида S<NN> с 2-3 цифрами)"

    # Check no tick is currently running (R12 — scoped через PID-file)
    if WRAPPER_PID_FILE.exists():
        try:
            existing_pid = int(WRAPPER_PID_FILE.read_text().strip())
            os.kill(existing_pid, 0)  # signal 0 = check alive
            return (
                f"⏳ Тик уже идёт (PID {existing_pid}).\n"
                f"/abort если нужно остановить, или дождись завершения."
            )
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale pidfile — clean up
            WRAPPER_PID_FILE.unlink(missing_ok=True)

    # R3: Записать директиву в HANDOFF ПЕРЕД спавном
    if not _write_handoff_directive(spec):
        return f"❌ Не смог записать директиву /sprint --yes {spec} в HANDOFF — тик не запущен."

    # Spawn run_tick.sh detached
    try:
        log_path = REPO_ROOT / "logs" / "autopilot" / "manual-tg-tick.out"
        with log_path.open("a") as f:
            p = subprocess.Popen(
                [str(RUN_TICK)],
                cwd=REPO_ROOT,
                stdout=f,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,  # detach from listener
                close_fds=True,
            )
        return (
            f"🚀 Запустил тик для {spec}.\n"
            f"Директива записана в HANDOFF, wrapper PID: {p.pid}.\n"
            f"Жди heartbeats (5/15/25 мин) и финальный отчёт.\n"
            f"Если хочешь убить — /abort."
        )
    except Exception as e:
        return f"❌ Не смог запустить run_tick: {e}"


def cmd_abort(token: str, chat_id: str, args: str) -> str:
    """R12: scope kill только к wrapper'у этого репо. Не убивает другие
    claude-сессии в системе (твою interactive в том числе!).

    Логика:
    1. Читаем /tmp/autopilot_wrapper.pid (записан wrapper'ом при старте).
    2. Берём process group ID этого PID — SIGTERM PG-group целиком.
       Это убьёт wrapper + timeout + claude (все в одной PG, потому что
       run_tick.sh запускался через nohup или из listener'а с setsid).
    3. Никаких pgrep -f по всему системному ps.
    """
    if not WRAPPER_PID_FILE.exists():
        return "Нечего убивать — PID-file не найден, тика не было запущено."

    try:
        wrapper_pid = int(WRAPPER_PID_FILE.read_text().strip())
    except ValueError:
        return f"❌ PID-file поломан: {WRAPPER_PID_FILE}"

    # Verify it's still alive AND it's actually our wrapper (not a recycled PID).
    try:
        with open(f"/proc/{wrapper_pid}/cmdline") as f:
            cmdline = f.read().replace("\x00", " ")
        if "run_tick.sh" not in cmdline:
            WRAPPER_PID_FILE.unlink(missing_ok=True)
            return f"❌ PID {wrapper_pid} больше не run_tick.sh (cmdline={cmdline[:80]!r}). PID-file очищен."
    except FileNotFoundError:
        WRAPPER_PID_FILE.unlink(missing_ok=True)
        return f"❌ PID {wrapper_pid} мёртв. PID-file очищен."

    try:
        pgid = os.getpgid(wrapper_pid)
    except ProcessLookupError:
        WRAPPER_PID_FILE.unlink(missing_ok=True)
        return f"❌ PID {wrapper_pid} умер пока проверяли."

    try:
        os.killpg(pgid, signal.SIGTERM)
    except Exception as e:
        return f"❌ kill PG-group {pgid} failed: {e}"

    return (
        f"🛑 SIGTERM послан process group {pgid} (wrapper PID {wrapper_pid}).\n"
        f"Wrapper должен сделать cleanup через trap (если работает) — heartbeat покажет финал."
    )


def cmd_budget(token: str, chat_id: str, args: str) -> str:
    try:
        d = json.loads(AUTOPILOT_JSON.read_text())
    except Exception as e:
        return f"❌ autopilot.json не читается: {e}"
    budget = d.get("budget", {})
    return (
        f"Сегодня: {d.get('ticks_today', 0)}/{budget.get('max_ticks_per_day', '?')} тиков, "
        f"{d.get('tokens_today', 0)}/{budget.get('max_tokens_per_day', '?')} токенов.\n"
        f"Per-tick cap: $5 (--max-budget-usd в wrapper'е).\n"
        f"Last tick: {d.get('last_tick_at') or 'нет'}"
    )


def cmd_heartbeat(token: str, chat_id: str, args: str) -> str:
    rc, out, err = run_cmd(["bash", str(REPO_ROOT / "scripts" / "autopilot" / "heartbeat.sh")])
    state_short = ""
    try:
        d = json.loads(HEARTBEAT_STATE.read_text())
        state_short = f" → state={d.get('state')}"
    except Exception:
        pass
    if rc == 0:
        return f"❤️ Heartbeat запущен{state_short}"
    return f"❌ Heartbeat упал rc={rc}: {err}"


HANDLERS: dict[str, Callable[[str, str, str], str]] = {
    "/help": cmd_help,
    "/start": cmd_help,
    "/status": cmd_status,
    "/log": cmd_log,
    "/enable": cmd_enable,
    "/disable": cmd_disable,
    "/pause": cmd_pause,
    "/resume": cmd_resume,
    "/sprint": cmd_sprint,
    "/abort": cmd_abort,
    "/budget": cmd_budget,
    "/heartbeat": cmd_heartbeat,
}


# -------- Main loop --------


def _is_authorized(from_user_id: int | None, from_username: str | None,
                   allowed_user_id: int | None, allowed_username: str | None) -> bool:
    """R2: Auth по numeric user_id (стабильный) с fallback на username (mutable).
    Если оба заданы — оба должны совпасть. Если только username — fallback,
    с warning в логе.
    """
    if allowed_user_id is not None:
        # Strong path: numeric ID. Username — дополнительно если задан.
        if from_user_id != allowed_user_id:
            return False
        if allowed_username and (from_username or "").lower().lstrip("@") != allowed_username.lower().lstrip("@"):
            log.warning("user_id %d matched but username %r != %r — still allowing",
                        from_user_id, from_username, allowed_username)
        return True
    # Fallback: only username (R2 warning — mutable identifier).
    if allowed_username:
        return (from_username or "").lower().lstrip("@") == allowed_username.lower().lstrip("@")
    log.error("no auth configured (neither user_id nor username) — denying all")
    return False


def dispatch(token: str, chat_id: str, allowed_user_id: int | None,
             allowed_username: str | None, text: str,
             from_user_id: int | None, from_username: str) -> None:
    if not _is_authorized(from_user_id, from_username, allowed_user_id, allowed_username):
        log.warning("ignoring command from id=%s username=%r (not authorized)",
                    from_user_id, from_username)
        # Silent — don't reveal bot to outsiders.
        return
    text = text.strip()

    # Map reply-keyboard buttons → slash commands.
    if text in _BUTTON_TO_CMD:
        text = _BUTTON_TO_CMD[text]

    if not text.startswith("/"):
        return
    cmd, _, rest = text.partition(" ")
    # Strip @botname suffix that Telegram appends in groups (we're in private chat usually but be safe)
    cmd = cmd.split("@", 1)[0]
    handler = HANDLERS.get(cmd)
    if not handler:
        send_message(token, chat_id, f"❔ Неизвестная команда {cmd}. /help — список.")
        return
    try:
        reply = handler(token, chat_id, rest)
    except Exception as e:
        log.exception("handler %s failed", cmd)
        reply = f"❌ Ошибка в обработчике {cmd}: {e}"
    if reply:
        # /help (and /start = alias) — отправляем с reply-keyboard, чтобы прижать
        # кнопки внизу клиента. Остальные команды — без keyboard (Telegram сам
        # сохранит ранее установленную).
        reply_markup = None
        if cmd in ("/help", "/start"):
            reply_markup = json.dumps(_REPLY_KEYBOARD, ensure_ascii=False)
        send_message(token, chat_id, reply, reply_markup=reply_markup)


_CALLBACK_LABEL = {
    "yes": "✅ Да",
    "no": "❌ Нет",
    "skip": "⏩ Пропустить",
}


def _label_for_callback(data: str, msg_id: int | None) -> str:
    """E1 fix: TG не включает inline_keyboard в callback_query.message по умолчанию.
    Берём label из /tmp/autopilot_pending_asks/<msg_id>.json который tg_ask.sh
    создаёт при отправке вопроса. Fallback на hardcoded словарь.
    """
    if msg_id is not None:
        pending_file = PENDING_ASKS_DIR / f"{msg_id}.json"
        if pending_file.exists():
            try:
                d = json.loads(pending_file.read_text())
                # Format: {"buttons": {"yes": "✅ Да", "no": "❌ Нет", ...}}
                buttons = d.get("buttons") or {}
                if data in buttons:
                    return buttons[data]
            except Exception as e:
                log.warning("pending_asks read failed for msg_id=%s: %s", msg_id, e)
    return _CALLBACK_LABEL.get(data, data)


def handle_callback_query(token: str, allowed_user_id: int | None,
                          allowed_username: str | None, cq: dict) -> None:
    """Receive inline-button click — write to state-file for tg_wait_answer.sh.

    Поведение:
    1. answerCallbackQuery — стопим спиннер.
    2. Auth check (R2: user_id strong / username fallback).
    3. Edit оригинального сообщения: убираем inline-keyboard, добавляем строку
       «— Ответ: <label> (HH:MM UTC)».
    4. Пишем /tmp/autopilot_answers/<msg_id>.json — tg_wait_answer.sh подхватит.
    5. Удаляем /tmp/autopilot_pending_asks/<msg_id>.json (cleanup).
    """
    cq_id = cq.get("id") or ""
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    msg_id = msg.get("message_id")
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    original_text = msg.get("text") or ""
    frm = cq.get("from") or {}
    username = frm.get("username") or ""
    from_user_id = frm.get("id")

    # Stop the spinner regardless of auth (don't leave user UI hanging)
    if cq_id:
        try:
            tg_api(token, "answerCallbackQuery",
                   {"callback_query_id": cq_id, "text": "Принято"}, timeout=5)
        except Exception as e:
            log.warning("answerCallbackQuery failed: %s", e)

    # R2: Auth check by user_id (strong) with username fallback
    if not _is_authorized(from_user_id, username, allowed_user_id, allowed_username):
        log.warning("ignoring callback_query from id=%s username=%r (not authorized)",
                    from_user_id, username)
        return

    if not msg_id:
        log.warning("callback_query without message_id: %s", cq)
        return

    # ---- Edit original message: remove keyboard + show choice ----
    label = _label_for_callback(data, msg_id)
    when = datetime.now(timezone.utc).strftime("%H:%M UTC")
    new_text = f"{original_text}\n\n— Ответ: {label} ({when})"
    try:
        tg_api(token, "editMessageText", {
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": new_text,
            "reply_markup": json.dumps({"inline_keyboard": []}, ensure_ascii=False),
        }, timeout=5)
    except Exception as e:
        log.warning("editMessageText failed for msg_id=%s: %s", msg_id, e)

    # ---- Write answer to state-file ----
    answer_file = ANSWERS_DIR / f"{msg_id}.json"
    payload = {
        "message_id": msg_id,
        "data": data,
        "from": username,
        "from_user_id": from_user_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # Atomic write: tmp + rename to avoid wait_answer seeing partial file.
        tmp = answer_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False))
        tmp.replace(answer_file)
        log.info("callback saved msg_id=%s data=%r label=%r", msg_id, data, label)
    except Exception as e:
        log.error("failed to save callback for msg_id=%s: %s", msg_id, e)

    # Cleanup pending_asks state (E1)
    pending_file = PENDING_ASKS_DIR / f"{msg_id}.json"
    pending_file.unlink(missing_ok=True)


def _load_idem_state() -> tuple[int, deque]:
    """R11: загрузить last_offset + последние N processed callback IDs."""
    try:
        d = json.loads(IDEMPOTENCY_FILE.read_text())
        offset = int(d.get("last_offset", 0))
        seen = deque(d.get("seen_callback_ids", []), maxlen=_IDEM_CALLBACK_HISTORY_SIZE)
        return offset, seen
    except Exception:
        return 0, deque(maxlen=_IDEM_CALLBACK_HISTORY_SIZE)


def _save_idem_state(offset: int, seen_callback_ids: deque) -> None:
    """R11: atomic write idempotency state."""
    payload = {"last_offset": offset, "seen_callback_ids": list(seen_callback_ids)}
    tmp = IDEMPOTENCY_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False))
        tmp.replace(IDEMPOTENCY_FILE)
    except Exception as e:
        log.warning("idem state save failed: %s", e)


def main_loop(token: str, allowed_user_id: int | None,
              allowed_username: str | None, offset_file: Path, once: bool = False) -> None:
    # R11: используем merged idem state (offset + callback dedup).
    offset, seen_callback_ids = _load_idem_state()
    # Backward-compat: если IDEMPOTENCY_FILE отсутствует но offset_file есть — мигрируем
    if offset == 0:
        try:
            offset = int(offset_file.read_text().strip())
        except Exception:
            pass

    log.info("listener started: offset=%d allowed_user_id=%s allowed_username=@%s once=%s",
             offset, allowed_user_id, allowed_username, once)

    while True:
        try:
            d = tg_api(
                token,
                "getUpdates",
                {"offset": offset, "timeout": 25, "allowed_updates": '["message","callback_query"]'},
                timeout=35,
            )
        except Exception as e:
            log.warning("getUpdates failed: %s — retry in 5s", e)
            time.sleep(5)
            if once:
                return
            continue
        if not d.get("ok"):
            log.error("TG error: %s", d)
            time.sleep(5)
            if once:
                return
            continue
        results = d.get("result") or []
        for upd in results:
            # 1. Slash-command (text message)
            msg = upd.get("message") or {}
            text = msg.get("text") or ""
            frm = msg.get("from") or {}
            chat = msg.get("chat") or {}
            chat_id = str(chat.get("id") or "")
            from_user_id = frm.get("id")
            username = frm.get("username") or ""
            if text and chat_id:
                dispatch(token, chat_id, allowed_user_id, allowed_username,
                         text, from_user_id, username)
            # 2. Inline-button click (callback_query) — для tg_ask + tg_wait_answer flow
            cq = upd.get("callback_query")
            if cq:
                # R11: idempotency check — пропускаем уже обработанный callback
                cq_id = cq.get("id")
                if cq_id and cq_id in seen_callback_ids:
                    log.info("skipping already-processed callback_query id=%s", cq_id)
                else:
                    handle_callback_query(token, allowed_user_id, allowed_username, cq)
                    if cq_id:
                        seen_callback_ids.append(cq_id)
            # R11: per-update offset persist (atomic save)
            offset = upd["update_id"] + 1
            _save_idem_state(offset, seen_callback_ids)
        if once:
            return


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--offset-file", default=str(DEFAULT_OFFSET_FILE))
    p.add_argument("--once", action="store_true", help="Process one batch then exit (smoke-test)")
    p.add_argument("--reset-offset", action="store_true", help="Drop saved offset")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    # Source .env.dev
    env_file = REPO_ROOT / ".env.dev"
    if env_file.exists():
        for ln in env_file.read_text().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

    token = os.environ.get("AUTOPILOT_TG_BOT_TOKEN")
    allowed_username = os.environ.get("AUTOPILOT_TG_ALLOWED_USERNAME") or "Lobster_21"
    # R2: strong auth — numeric user_id из env, fallback на username.
    allowed_user_id_raw = os.environ.get("AUTOPILOT_TG_ALLOWED_USER_ID")
    allowed_user_id = None
    if allowed_user_id_raw:
        try:
            allowed_user_id = int(allowed_user_id_raw)
        except ValueError:
            log.error("AUTOPILOT_TG_ALLOWED_USER_ID не число: %r", allowed_user_id_raw)
            return 3
    else:
        log.warning("AUTOPILOT_TG_ALLOWED_USER_ID не задан — fallback на username (mutable, R2)")
    if not token:
        log.error("AUTOPILOT_TG_BOT_TOKEN not set")
        return 2

    offset_file = Path(args.offset_file)
    if args.reset_offset:
        offset_file.unlink(missing_ok=True)
        IDEMPOTENCY_FILE.unlink(missing_ok=True)

    try:
        main_loop(token, allowed_user_id, allowed_username, offset_file, once=args.once)
    except KeyboardInterrupt:
        log.info("interrupted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
