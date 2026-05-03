# Code Review (Dual) Loop

Цикл `/codereview-dual → /fix` до полной чистоты от CRITICAL и HIGH. Принудительный dual (Claude + Codex) на каждой итерации.

## Когда использовать

«двойной ревью до чистоты», «цикл двойного ревью», «доведи dual-ревью до MEDIUM/LOW», `/codereview-dual-loop`.

## Что делает

- На каждой итерации зовёт `/codereview-dual` напрямую (без routing-развилки на classic).
- Применяет `/fix` в быстром режиме только для CRITICAL и HIGH.
- Стоп: `CRITICAL == 0 AND HIGH == 0`. Лимит — 5 итераций.
- При недоступном Codex — graceful fallback на одиночный `/review-loop`.

## Связанные скиллы

- `/codereview-dual` — одна итерация двойного ревью.
- `/review-loop` — цикл с роутинг-выбором dual/single.
- `/fix` — применение фиксов.
- `/codex-toggle` — kill-switch связки.
