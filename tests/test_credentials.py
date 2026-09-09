import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_221b import credentials
from mcp_221b.cli import main
from mcp_221b.config import brave_key, config_path, read_config, save_config


@pytest.fixture(autouse=True)
def no_real_keychain(monkeypatch):
    monkeypatch.setattr(
        credentials, "_os_backend", Mock(side_effect=AssertionError("Real keychain forbidden"))
    )


def test_init_stores_only_in_keyring(monkeypatch, capsys):
    store = Mock()
    store.get_password.return_value = "secret-key"
    monkeypatch.setattr(credentials, "_os_backend", lambda: store)
    monkeypatch.setattr("sys.argv", ["221b-mcp", "init"])
    monkeypatch.setattr("builtins.input", lambda _: "brave")
    monkeypatch.setattr("mcp_221b.cli.getpass.getpass", lambda _: "secret-key")
    main()
    store.set_password.assert_called_once_with("221b-mcp", "brave-api-key", "secret-key")
    assert read_config() == {"search_provider": "brave", "brave_key_storage": "keyring"}
    assert "secret-key" not in config_path().read_text()
    captured = capsys.readouterr()
    assert "secret-key" not in captured.out + captured.err
    assert brave_key() == "secret-key"


def test_storage_failure_preserves_config(monkeypatch, capsys):
    save_config({"search_provider": "keyless"})
    store = Mock()
    store.set_password.side_effect = RuntimeError("secret-key")
    monkeypatch.setattr(credentials, "_os_backend", lambda: store)
    monkeypatch.setattr("sys.argv", ["221b-mcp", "init"])
    monkeypatch.setattr("builtins.input", lambda _: "brave")
    monkeypatch.setattr("mcp_221b.cli.getpass.getpass", lambda _: "secret-key")
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert read_config() == {"search_provider": "keyless"}
    assert "secret-key" not in capsys.readouterr().err


def test_failed_readback_does_not_claim_success(monkeypatch):
    store = Mock()
    store.get_password.return_value = None
    monkeypatch.setattr(credentials, "_os_backend", lambda: store)
    with pytest.raises(credentials.CredentialError, match="save and verify"):
        credentials.save_brave_key("key")


def test_file_precedes_environment_and_keyring(tmp_path, monkeypatch):
    file = tmp_path / "brave"
    file.write_text("mounted-key\n")
    monkeypatch.setenv("BRAVE_API_KEY_FILE", str(file))
    monkeypatch.setenv("BRAVE_API_KEY", "environment-key")
    save_config({"brave_key_storage": "keyring"})
    assert brave_key() == "mounted-key"
    file.write_text("rotated-key\n")
    assert brave_key() == "rotated-key"
    monkeypatch.delenv("BRAVE_API_KEY_FILE")
    assert brave_key() == "environment-key"


@pytest.mark.parametrize("content", [b"", b"  ", b"bad key", b"x" * 8193, b"\xff"])
def test_invalid_file_never_falls_back(tmp_path, monkeypatch, content):
    file = tmp_path / "brave"
    file.write_bytes(content)
    monkeypatch.setenv("BRAVE_API_KEY_FILE", str(file))
    monkeypatch.setenv("BRAVE_API_KEY", "fallback-secret")
    with pytest.raises(credentials.CredentialError):
        brave_key()
    assert credentials.credential_status()["configured"] is False


def test_missing_file_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY_FILE", str(tmp_path / "private-file-name"))
    with pytest.raises(credentials.CredentialError) as error:
        brave_key()
    assert "private-file-name" not in str(error.value)


def test_keyless_and_doctor_do_not_access_keychain(monkeypatch, capsys):
    assert brave_key() == ""
    save_config({"brave_key_storage": "keyring"})
    monkeypatch.setattr("sys.argv", ["221b-mcp", "doctor"])
    main()
    data = json.loads(capsys.readouterr().out)
    assert data["brave_credentials"] == {"source": "keyring", "configured": True, "verified": False}


def test_keychain_access_failure_is_sanitized(monkeypatch):
    save_config({"brave_key_storage": "keyring"})
    store = Mock()
    store.get_password.side_effect = RuntimeError("provider-secret")
    monkeypatch.setattr(credentials, "_os_backend", lambda: store)
    with pytest.raises(credentials.CredentialError) as error:
        brave_key()
    assert "provider-secret" not in str(error.value)


def test_plaintext_legacy_config_is_not_read():
    config_path().write_text('{"brave_api_key":"old-secret"}')
    with pytest.raises(credentials.CredentialError, match="Plaintext"):
        brave_key()
    assert "old-secret" not in json.dumps(credentials.credential_status())


# Exercise concrete backend selection without loading any actual credential backend.
ORIGINAL_BACKEND = credentials._os_backend


@pytest.mark.parametrize(
    "system,module,name",
    [
        ("Darwin", "keyring.backends.macOS", "Keyring"),
        ("Windows", "keyring.backends.Windows", "WinVaultKeyring"),
        ("Linux", "keyring.backends.SecretService", "Keyring"),
    ],
)
def test_only_concrete_os_backends_selected(monkeypatch, system, module, name):
    store = SimpleNamespace(priority=5)
    imported = Mock(return_value=SimpleNamespace(**{name: lambda: store}))
    monkeypatch.setattr(credentials.platform, "system", lambda: system)
    monkeypatch.setattr(credentials.importlib, "import_module", imported)
    assert ORIGINAL_BACKEND() is store
    imported.assert_called_once_with(module)


def test_unavailable_backend_has_no_fallback(monkeypatch):
    monkeypatch.setattr(credentials.platform, "system", lambda: "Linux")
    imported = Mock(side_effect=RuntimeError("backend detail"))
    monkeypatch.setattr(credentials.importlib, "import_module", imported)
    with pytest.raises(credentials.CredentialError, match="No plaintext fallback"):
        ORIGINAL_BACKEND()
    assert imported.call_count == 1
