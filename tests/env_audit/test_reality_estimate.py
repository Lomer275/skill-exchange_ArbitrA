import json

import envaudit.reality.estimate as estimate_module

from .reality_builders import facts_document, install_fake_tools, irina_like
from .transcript_builders import assistant_line, iso, user_line, write_session


def _segments(home, root, *, model="claude-opus-5"):
    lines = []
    for index, amount in enumerate((10, 30, 50), 1):
        lines.append(user_line(iso(8 - index), command="close", cwd=str(root)))
        assistant = assistant_line(
            iso(8 - index - 0.1),
            msg_id=f"message-{index}",
            req_id=f"request-{index}",
            model=model,
            usage=(amount, amount + 1, amount + 2, amount + 3),
            cwd=str(root),
        )
        lines.append(assistant)
        if index == 1:
            lines.append(dict(assistant))
        lines.append(user_line(iso(8 - index - 0.2), text="дальше", cwd=str(root)))
    write_session(home, str(root), "reality-estimate", lines)


def test_segments_and_median(fake_home, tmp_path, monkeypatch):
    install_fake_tools(monkeypatch, tmp_path)
    root = irina_like(fake_home / "projects" / "estimate")
    _segments(fake_home, root)
    monkeypatch.setattr(
        estimate_module,
        "read_data",
        lambda _name: json.dumps(
            {
                "date": "2026-09-17",
                "models": {
                    "opus-5": {"input": 1, "output": 2, "cache_write": 3, "cache_read": 4}
                },
            }
        ),
    )

    result = estimate_module.estimate(facts_document(fake_home, root), root)

    assert result["close"]["runs"] == 3
    assert result["close"]["median_tokens"] == {
        "input": 30,
        "output": 31,
        "cache_creation": 32,
        "cache_read": 33,
    }
    assert result["close"]["model"] == "claude-opus-5"
    assert result["price_table_date"] == "2026-09-17"


def test_price_table_missing_model(fake_home, tmp_path, monkeypatch):
    install_fake_tools(monkeypatch, tmp_path)
    root = irina_like(fake_home / "projects" / "unknown-model")
    _segments(fake_home, root, model="claude-unknown-model")
    monkeypatch.setattr(
        estimate_module,
        "read_data",
        lambda _name: json.dumps(
            {
                "date": "2026-09-17",
                "models": {
                    "different-model": {"input": 1, "output": 1, "cache_write": 1, "cache_read": 1}
                },
            }
        ),
    )

    result = estimate_module.estimate(facts_document(fake_home, root), root)

    assert result["close"]["est_usd"] is None
    assert result["suggested_max_budget_usd"] == 1.0
