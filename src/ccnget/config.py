"""Persistent configuration management for ccnget.

Reads/writes a JSON file under the user config directory
(platformdirs: ~/.config/ccnget/config.json on Linux).

Resolution chain (highest priority first):
    1. CLI flag / function argument (explicit override)
    2. Config file (set via ``ccnget config set``)
    3. Environment variable
    4. Hard-coded default
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from platformdirs import user_config_dir

logger: logging.Logger = logging.getLogger(__name__)

CONFIG_DIR: Path = Path(user_config_dir("ccnget"))
CONFIG_FILE: Path = CONFIG_DIR / "config.json"

# Valid config keys and their defaults
KNOWN_KEYS: dict[str, tuple[str, str | None]] = {
    "cdx-url": (
        "https://brian-learns-cc-news-cdx-server.hf.space/",
        "CDX_URL",
    ),
    "cc-crawl-base-url": (
        "https://data.commoncrawl.org",
        "CC_CRAWL_BASE_URL",
    ),
}


def _load_config() -> dict[str, str]:
    """Load the config file, returning an empty dict if missing."""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items() if isinstance(v, str)}
            logger.warning("Config file is not a valid dict, ignoring")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read config file: %s", e)
    return {}


def _write_config(data: dict[str, str]) -> None:
    """Write the config file with owner-only permissions (0600)."""
    fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(fd, 0o600)  # also tighten a pre-existing file
        f.write(json.dumps(data, indent=2) + "\n")


def _save_config(settings: dict[str, str]) -> None:
    """Merge *settings* into the config file (idempotent)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    current = _load_config()
    current.update(settings)
    _write_config(current)
    logger.debug("Wrote config to %s", CONFIG_FILE)


def _unset_config(key: str) -> None:
    """Remove *key* from the config file."""
    current = _load_config()
    if key in current:
        del current[key]
        _write_config(current)
        logger.debug("Unset %s from %s", key, CONFIG_FILE)


def _resolve(
    key: str,
    default: str | None = None,
    env_var: str | None = None,
) -> str:
    """Resolve a setting using the priority chain.

    Priority: config file > env var > default.

    Parameters
    ----------
    key : str
        Config key (e.g. ``"cdx-url"``).
    default : str | None
        Hard-coded fallback.
    env_var : str | None
        Environment variable name to check.

    Returns
    -------
    str
        The resolved value.
    """
    cfg = _load_config()
    if key in cfg:
        return cfg[key]
    if env_var and env_var in os.environ:
        return os.environ[env_var]
    if default is not None:
        return default
    raise ValueError(f"No value resolved for '{key}' (no config, env var, or default)")


def get_config(key: str) -> str | None:
    """Return the value for *key* from the config file, or ``None`` if not set."""
    return _load_config().get(key)


def set_config(key: str, value: str) -> None:
    """Persist *value* for *key* in the config file."""
    if key not in KNOWN_KEYS:
        raise KeyError(f"Unknown config key '{key}'. Valid keys: {', '.join(KNOWN_KEYS)}")
    _save_config({key: value})


def unset_config(key: str) -> None:
    """Remove *key* from the config file."""
    if key not in KNOWN_KEYS:
        raise KeyError(f"Unknown config key '{key}'. Valid keys: {', '.join(KNOWN_KEYS)}")
    _unset_config(key)


def list_config() -> dict[str, dict[str, str | None]]:
    """Return all config keys with their resolved values and sources."""
    cfg = _load_config()
    result: dict[str, dict[str, str | None]] = {}
    for key, (default, env_var) in KNOWN_KEYS.items():
        source: str | None = None
        value: str | None = None
        if key in cfg:
            value = cfg[key]
            source = "config"
        elif env_var and env_var in os.environ:
            value = os.environ[env_var]
            source = f"env ({env_var})"
        else:
            value = default
            source = "default"
        result[key] = {"value": value, "source": source}
    return result


def show_config_path() -> str:
    """Return the path to the config file."""
    return str(CONFIG_FILE)
