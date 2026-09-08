"""Configuration is loaded only when explicitly requested; imports never prompt."""

import json
import os
import tempfile
from pathlib import Path

from platformdirs import user_config_path, user_data_path


def config_path() -> Path:
    override = os.environ.get("MCP_221B_CONFIG")
    return Path(override) if override else user_config_path("221b-mcp") / "config.json"


def data_path() -> Path:
    override = os.environ.get("MCP_221B_DATA_DIR")
    return Path(override) if override else user_data_path("221b-mcp")


def read_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    config = json.loads(path.read_text())
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object.")
    return config


def brave_key() -> str:
    return os.environ.get("BRAVE_API_KEY", "") or read_config().get("brave_api_key", "")


def search_provider() -> str:
    provider = os.environ.get("MCP_221B_SEARCH_PROVIDER") or read_config().get(
        "search_provider", "keyless"
    )
    if provider not in {"keyless", "brave"}:
        raise ValueError("Search provider must be keyless or brave.")
    return provider


def save_config(config: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".config-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(config, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
