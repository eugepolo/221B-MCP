import json
import os
import stat

import pytest

from mcp_221b.config import save_config


def test_config_private_and_contains_no_keys():
    path = save_config({"brave_key_storage": "keyring", "search_provider": "brave"})
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "brave_api_key" not in json.loads(path.read_text())
    with pytest.raises(ValueError):
        save_config({"brave_api_key": "never-write-this"})
    assert "never-write-this" not in path.read_text()
