import pytest


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_221B_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("MCP_221B_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("MCP_221B_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY_FILE", raising=False)
