import copy
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".skill-exchange"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _default_config() -> dict:
    return {
        "default_path": str(Path.home() / ".claude" / "skills"),
        "installed": [],
    }


# Kept for backwards-compat with code/tests that read DEFAULT_CONFIG.
# Always read via load_config() in production paths to get a fresh copy.
DEFAULT_CONFIG = _default_config()


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return _default_config()
    with open(CONFIG_FILE, encoding="utf-8") as f:
        config = json.load(f)
    # Forward-compat: ensure required keys exist if older configs lack them.
    defaults = _default_config()
    for key, value in defaults.items():
        config.setdefault(key, copy.deepcopy(value))
    return config


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
