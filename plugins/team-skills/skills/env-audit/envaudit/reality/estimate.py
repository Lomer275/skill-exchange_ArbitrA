from collections import Counter
import json
import os
from pathlib import Path
from statistics import median
import time

from envaudit.core.context import Context, Flags
from envaudit.core.resources import read_data
from envaudit.core.transcripts import Record, Usage, load_index


_KINDS = ("close", "accept")
_USAGE_FIELDS = ("input", "output", "cache_creation", "cache_read")


def _inside(path: str, root: Path) -> bool:
    try:
        return os.path.commonpath((os.path.realpath(path), str(root))) == str(root)
    except (OSError, ValueError):
        return False


def _command_kind(record: Record) -> str | None:
    if record.command_name is None:
        return None
    kind = record.command_name.rsplit(":", 1)[-1]
    return kind if kind in _KINDS else None


def _deduplicated_usage(records: list[Record]) -> list[tuple[Usage, str | None]]:
    result = []
    seen: set[tuple[str | None, str | None]] = set()
    for record in records:
        if record.type != "assistant" or record.usage is None or record.is_subagent_file:
            continue
        key = (record.message_id, record.request_id)
        if key != (None, None):
            if key in seen:
                continue
            seen.add(key)
        result.append((record.usage, record.model))
    return result


def _segments(index, root: Path) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {kind: [] for kind in _KINDS}
    for records in index.sessions().values():
        if not any(record.cwd and _inside(record.cwd, root) for record in records):
            continue
        for position, record in enumerate(records):
            kind = _command_kind(record)
            if record.type != "user" or kind is None:
                continue
            end = len(records)
            for later in range(position + 1, len(records)):
                boundary = records[later]
                if (
                    boundary.type == "user"
                    and boundary.origin_kind == "human"
                    and _command_kind(boundary) is None
                ):
                    end = later
                    break
            usage_records = _deduplicated_usage(records[position:end])
            model_counts = Counter(model for _usage, model in usage_records if model)
            segment_model = (
                sorted(model_counts, key=lambda item: (-model_counts[item], item))[0]
                if model_counts
                else None
            )
            totals = {
                field: sum(getattr(usage, field) for usage, _model in usage_records)
                for field in _USAGE_FIELDS
            }
            result[kind].append(
                {
                    "started_at": record.timestamp or 0.0,
                    "tokens": totals,
                    "model": segment_model,
                }
            )
    for kind in _KINDS:
        result[kind].sort(key=lambda item: item["started_at"], reverse=True)
        result[kind] = result[kind][:10]
    return result


def _median(values: list[int]) -> int | float:
    if not values:
        return 0
    value = median(values)
    return int(value) if float(value).is_integer() else value


def _price_table() -> tuple[str | None, dict]:
    raw = read_data("prices.json")
    if raw is None:
        return None, {}
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return None, {}
    if not isinstance(document, dict) or not isinstance(document.get("models"), dict):
        return None, {}
    date = document.get("date")
    return (date if isinstance(date, str) else None), document["models"]


def _model_price(model: str | None, prices: dict) -> dict | None:
    if model is None:
        return None
    candidates = [
        (str(marker), value)
        for marker, value in prices.items()
        if isinstance(marker, str) and marker in model and isinstance(value, dict)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item[0]))[1]


def _view(items: list[dict], prices: dict) -> dict:
    medians = {
        field: _median([item["tokens"][field] for item in items])
        for field in _USAGE_FIELDS
    }
    models = Counter(item["model"] for item in items if item["model"] is not None)
    model = sorted(models, key=lambda item: (-models[item], item))[0] if models else None
    rates = _model_price(model, prices)
    estimated = None
    if rates is not None:
        names = {
            "input": "input",
            "output": "output",
            "cache_creation": "cache_write",
            "cache_read": "cache_read",
        }
        try:
            estimated = round(
                sum(float(medians[field]) * float(rates[names[field]]) for field in _USAGE_FIELDS)
                / 1_000_000,
                6,
            )
        except (KeyError, TypeError, ValueError):
            estimated = None
    return {
        "runs": len(items),
        "median_tokens": medians,
        "model": model,
        "est_usd": estimated,
    }


def estimate(facts: dict, root: Path) -> dict:
    root = Path(os.path.realpath(root))
    host = facts.get("host") if isinstance(facts.get("host"), dict) else {}
    raw_home = host.get("home") if isinstance(host.get("home"), str) else str(Path.home())
    home = Path(os.path.realpath(Path(raw_home).expanduser()))
    started = time.time()
    ctx = Context(Flags(), home, [root], started, started + 300)
    segments = _segments(load_index(ctx), root)
    price_date, prices = _price_table()
    close = _view(segments["close"], prices)
    accept = _view(segments["accept"], prices)
    total = sum(value["est_usd"] or 0.0 for value in (close, accept))
    return {
        "root": str(root),
        "close": close,
        "accept": accept,
        "suggested_max_budget_usd": max(1.0, round(2 * total, 2)),
        "price_table_date": price_date,
    }
