"""Tests for src/ccnget/config.py — set/get/unset/resolve and CLI config subcommands."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ccnget.config import (
    CONFIG_FILE,
    KNOWN_KEYS,
    _load_config,
    _resolve,
    get_config,
    list_config,
    set_config,
    show_config_path,
    unset_config,
)
from ccnget.geturl import config_cmd


class TestSetGetUnset:
    """Test set_config, get_config, unset_config with tmp_path as config dir."""

    def _setup(self, tmp_path: Path) -> Path:
        """Patch CONFIG_DIR/CONFIG_FILE to use tmp_path."""
        cfg_file = tmp_path / "config.json"
        os.environ.pop("CDX_LOOKUP_URL", None)
        os.environ.pop("CC_CRAWL_BASE_URL", None)
        return cfg_file

    @patch("ccnget.config.CONFIG_FILE")
    @patch("ccnget.config.CONFIG_DIR")
    def test_set_and_get(self, mock_dir, mock_file, tmp_path):
        cfg_file = self._setup(tmp_path)
        mock_dir.__truediv__ = lambda self, other: cfg_file
        mock_file.__truediv__ = lambda self, other: cfg_file
        # Use the real file
        with patch("ccnget.config.CONFIG_FILE", cfg_file), \
             patch("ccnget.config.CONFIG_DIR", tmp_path):
            set_config("cdx-url", "http://localhost:8000/lookup")
            assert get_config("cdx-url") == "http://localhost:8000/lookup"

    @patch("ccnget.config.CONFIG_FILE")
    @patch("ccnget.config.CONFIG_DIR")
    def test_unset_removes_key(self, mock_dir, mock_file, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("ccnget.config.CONFIG_FILE", cfg_file), \
             patch("ccnget.config.CONFIG_DIR", tmp_path):
            set_config("cdx-url", "http://localhost:8000/lookup")
            assert get_config("cdx-url") == "http://localhost:8000/lookup"
            unset_config("cdx-url")
            assert get_config("cdx-url") is None

    @patch("ccnget.config.CONFIG_FILE")
    @patch("ccnget.config.CONFIG_DIR")
    def test_set_unknown_key_raises(self, mock_dir, mock_file, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("ccnget.config.CONFIG_FILE", cfg_file), \
             patch("ccnget.config.CONFIG_DIR", tmp_path):
            with pytest.raises(KeyError, match="Unknown config key"):
                set_config("bogus-key", "value")

    @patch("ccnget.config.CONFIG_FILE")
    @patch("ccnget.config.CONFIG_DIR")
    def test_get_returns_none_when_not_set(self, mock_dir, mock_file, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("ccnget.config.CONFIG_FILE", cfg_file), \
             patch("ccnget.config.CONFIG_DIR", tmp_path):
            assert get_config("cdx-url") is None

    @patch("ccnget.config.CONFIG_FILE")
    @patch("ccnget.config.CONFIG_DIR")
    def test_set_idempotent_preserves_other_keys(self, mock_dir, mock_file, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("ccnget.config.CONFIG_FILE", cfg_file), \
             patch("ccnget.config.CONFIG_DIR", tmp_path):
            set_config("cdx-url", "http://localhost:8000/lookup")
            set_config("cc-crawl-base-url", "http://mirror.example.org")
            assert get_config("cdx-url") == "http://localhost:8000/lookup"
            assert get_config("cc-crawl-base-url") == "http://mirror.example.org"

    @patch("ccnget.config.CONFIG_FILE")
    @patch("ccnget.config.CONFIG_DIR")
    def test_config_file_created_on_set(self, mock_dir, mock_file, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("ccnget.config.CONFIG_FILE", cfg_file), \
             patch("ccnget.config.CONFIG_DIR", tmp_path):
            assert not cfg_file.exists()
            set_config("cdx-url", "http://localhost:8000/lookup")
            assert cfg_file.exists()
            data = json.loads(cfg_file.read_text())
            assert data["cdx-url"] == "http://localhost:8000/lookup"


class TestResolve:
    """Test _resolve priority chain: config > env > default."""

    @patch("ccnget.config._load_config")
    def test_config_file_wins(self, mock_load):
        mock_load.return_value = {"cdx-url": "http://config-val/lookup"}
        with patch.dict(os.environ, {"CDX_LOOKUP_URL": "http://env-val/lookup"}):
            result = _resolve("cdx-url", default="http://default/lookup", env_var="CDX_LOOKUP_URL")
            assert result == "http://config-val/lookup"

    @patch("ccnget.config._load_config")
    def test_env_var_wins_over_default(self, mock_load):
        mock_load.return_value = {}
        with patch.dict(os.environ, {"CDX_LOOKUP_URL": "http://env-val/lookup"}):
            result = _resolve("cdx-url", default="http://default/lookup", env_var="CDX_LOOKUP_URL")
            assert result == "http://env-val/lookup"

    @patch("ccnget.config._load_config")
    def test_default_used_when_nothing_set(self, mock_load):
        mock_load.return_value = {}
        with patch.dict(os.environ, {}, clear=True):
            # Remove env var if it exists
            os.environ.pop("CDX_LOOKUP_URL", None)
            result = _resolve("cdx-url", default="http://default/lookup", env_var="CDX_LOOKUP_URL")
            assert result == "http://default/lookup"

    @patch("ccnget.config._load_config")
    def test_raises_when_no_value(self, mock_load):
        mock_load.return_value = {}
        with pytest.raises(ValueError, match="No value resolved"):
            _resolve("unknown-key", default=None, env_var=None)


class TestListConfig:
    """Test list_config returns all keys with sources."""

    @patch("ccnget.config._load_config")
    def test_list_all_defaults(self, mock_load):
        mock_load.return_value = {}
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CDX_LOOKUP_URL", None)
            os.environ.pop("CC_CRAWL_BASE_URL", None)
            result = list_config()
            assert "cdx-url" in result
            assert result["cdx-url"]["source"] == "default"
            assert "cc-crawl-base-url" in result
            assert result["cc-crawl-base-url"]["source"] == "default"

    @patch("ccnget.config._load_config")
    def test_list_shows_env_source(self, mock_load):
        mock_load.return_value = {}
        with patch.dict(os.environ, {"CDX_LOOKUP_URL": "http://env/lookup"}):
            result = list_config()
            assert result["cdx-url"]["source"] == "env (CDX_LOOKUP_URL)"
            assert result["cdx-url"]["value"] == "http://env/lookup"

    @patch("ccnget.config._load_config")
    def test_list_shows_config_source(self, mock_load):
        mock_load.return_value = {"cdx-url": "http://config/lookup"}
        result = list_config()
        assert result["cdx-url"]["source"] == "config"
        assert result["cdx-url"]["value"] == "http://config/lookup"


class TestShowConfigPath:
    def test_returns_path_string(self):
        result = show_config_path()
        assert isinstance(result, str)
        assert "ccnget" in result


class TestKnownKeys:
    def test_known_keys_contains_expected(self):
        assert "cdx-url" in KNOWN_KEYS
        assert "cc-crawl-base-url" in KNOWN_KEYS
        # Each entry is (default, env_var)
        assert KNOWN_KEYS["cdx-url"][1] == "CDX_LOOKUP_URL"
        assert KNOWN_KEYS["cc-crawl-base-url"][1] == "CC_CRAWL_BASE_URL"


class TestConfigCLI:
    """Test the config CLI subcommands."""

    @patch("ccnget.geturl.set_config")
    def test_config_set(self, mock_set, capsys):
        import argparse

        args = argparse.Namespace(config_action="set", key="cdx-url", value="http://localhost:8000/lookup")
        config_cmd(args)
        mock_set.assert_called_once_with("cdx-url", "http://localhost:8000/lookup")
        captured = capsys.readouterr()
        assert "Set cdx-url" in captured.out

    @patch("ccnget.geturl.get_config")
    def test_config_get(self, mock_get, capsys):
        import argparse

        mock_get.return_value = "http://localhost:8000/lookup"
        args = argparse.Namespace(config_action="get", key="cdx-url")
        config_cmd(args)
        captured = capsys.readouterr()
        assert "http://localhost:8000/lookup" in captured.out

    @patch("ccnget.geturl.get_config")
    def test_config_get_not_set_exits(self, mock_get, capsys):
        import argparse

        mock_get.return_value = None
        args = argparse.Namespace(config_action="get", key="cdx-url")
        with pytest.raises(SystemExit):
            config_cmd(args)
        captured = capsys.readouterr()
        assert "not set" in captured.err

    @patch("ccnget.geturl.list_config")
    def test_config_show(self, mock_list, capsys):
        import argparse

        mock_list.return_value = {
            "cdx-url": {"value": "http://localhost:8000/lookup", "source": "config"},
            "cc-crawl-base-url": {"value": "https://data.commoncrawl.org", "source": "default"},
        }
        args = argparse.Namespace(config_action="show")
        config_cmd(args)
        captured = capsys.readouterr()
        assert "cdx-url" in captured.out
        assert "cc-crawl-base-url" in captured.out
        assert "source" in captured.out

    @patch("ccnget.geturl.unset_config")
    def test_config_unset(self, mock_unset, capsys):
        import argparse

        args = argparse.Namespace(config_action="unset", key="cdx-url")
        config_cmd(args)
        mock_unset.assert_called_once_with("cdx-url")
        captured = capsys.readouterr()
        assert "Unset cdx-url" in captured.out

    @patch("ccnget.geturl.set_config")
    def test_config_set_unknown_key(self, mock_set, capsys):
        import argparse

        mock_set.side_effect = KeyError("Unknown config key 'bogus'")
        args = argparse.Namespace(config_action="set", key="bogus", value="val")
        with pytest.raises(SystemExit):
            config_cmd(args)
        captured = capsys.readouterr()
        assert "Unknown config key" in captured.err
