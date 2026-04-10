import json
import pytest
from pathlib import Path
from unittest.mock import patch


def patched_config(tmp_path):
    """Context manager: patches CONFIG_DIR and CONFIG_FILE to tmp_path."""
    import config as cfg
    return patch.multiple(
        cfg,
        CONFIG_DIR=tmp_path,
        CONFIG_FILE=tmp_path / "config.json",
    )


def test_load_config_returns_default_when_no_file(tmp_path):
    with patched_config(tmp_path):
        import config as cfg
        result = cfg.load_config()
        assert result["installed"] == []
        assert "default_path" in result


def test_save_and_load_roundtrip(tmp_path):
    with patched_config(tmp_path):
        import config as cfg
        data = {"default_path": "/custom/path", "installed": ["skill-a"]}
        cfg.save_config(data)
        loaded = cfg.load_config()
        assert loaded == data


def test_save_creates_directory(tmp_path):
    nested = tmp_path / "deep" / "dir"
    with patch.multiple("config", CONFIG_DIR=nested, CONFIG_FILE=nested / "config.json"):
        import config as cfg
        cfg.save_config({"default_path": "/x", "installed": []})
        assert (nested / "config.json").exists()
