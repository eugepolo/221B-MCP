import json
import os
import stat

from mcp_221b.config import brave_key, save_config


def test_config_private_and_environment_precedence(monkeypatch):
    path = save_config({"brave_api_key": "saved"})
    assert brave_key() == "saved"
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    monkeypatch.setenv("BRAVE_API_KEY", "environment")
    assert brave_key() == "environment"
    save_config({"brave_api_key": "replacement"})
    assert json.loads(path.read_text())["brave_api_key"] == "replacement"
