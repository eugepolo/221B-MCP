"""credentials from explicit runtime sources or an OS credential store."""

import importlib
import os
import platform
import stat

from mcp_221b.config import read_config

SERVICE = "221b-mcp"
PROVIDERS = {"brave": "Brave", "shodan": "Shodan"}
MAX_SECRET_BYTES = 8192


class CredentialError(ValueError):
    """A sanitized credential error safe to display to the user."""


def _os_backend():
    # Select concrete OS backends; never use keyring's plugin/fallback discovery.
    backends = {
        "Darwin": ("keyring.backends.macOS", "Keyring"),
        "Windows": ("keyring.backends.Windows", "WinVaultKeyring"),
        "Linux": ("keyring.backends.SecretService", "Keyring"),
    }
    try:
        module, name = backends[platform.system()]
        backend = getattr(importlib.import_module(module), name)()
        if backend.priority <= 0:
            raise RuntimeError
        return backend
    except Exception:
        raise CredentialError(
            "OS credential storage is unavailable. Enable your OS credential service "
            "or supply BRAVE_API_KEY_FILE or SHODAN_API_KEY_FILE. No plaintext fallback is used."
        ) from None


def _validate_key(value: str, provider: str = "brave") -> str:
    value = value.strip()
    if not value or len(value.encode()) > MAX_SECRET_BYTES or any(c.isspace() for c in value):
        raise CredentialError(
            f"{PROVIDERS[provider]} key must be a nonempty token without whitespace."
        )
    return value


def _save_key(value: str, provider: str) -> None:
    value = _validate_key(value, provider)
    backend = _os_backend()
    try:
        backend.set_password(SERVICE, f"{provider}-api-key", value)
        if backend.get_password(SERVICE, f"{provider}-api-key") != value:
            raise RuntimeError
    except Exception:
        raise CredentialError(
            f"Could not save and verify the {PROVIDERS[provider]} key in OS credential storage. "
            "Check that the credential store is unlocked and access is allowed."
        ) from None


def _file_key(path: str, provider: str = "brave") -> str:
    variable = f"{provider.upper()}_API_KEY_FILE"
    try:
        # Avoid hanging on pipes/devices; mounted secret symlinks are supported.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise CredentialError(f"{variable} must point to a regular file.")
            raw = stream.read(MAX_SECRET_BYTES + 1)
        if len(raw) > MAX_SECRET_BYTES:
            raise CredentialError(f"{variable} exceeds the secret size limit.")
        return _validate_key(raw.decode("utf-8"), provider)
    except (OSError, UnicodeError):
        raise CredentialError(f"Cannot read {variable} as a UTF-8 secret file.") from None


def _load_key(provider: str) -> str:
    variable = f"{provider.upper()}_API_KEY"
    if f"{variable}_FILE" in os.environ:
        return _file_key(os.environ[f"{variable}_FILE"], provider)
    if variable in os.environ:
        return _validate_key(os.environ[variable], provider)
    config = read_config()
    if f"{provider}_api_key" in config:
        raise CredentialError(
            "Plaintext config keys are no longer read. Re-enter the key using 221b-mcp init "
            "or remove that field and supply a mounted secret."
        )
    if config.get(f"{provider}_key_storage") != "keyring":
        return ""
    backend = _os_backend()
    try:
        value = backend.get_password(SERVICE, f"{provider}-api-key")
    except Exception:
        raise CredentialError(
            "Unlock the OS credential store and allow access, or use a mounted secret."
        ) from None
    if value is None:
        raise CredentialError(
            f"Saved {PROVIDERS[provider]} key was not found. Re-enter it using 221b-mcp init."
        )
    return _validate_key(value, provider)


def credential_status(provider: str = "brave") -> dict:
    """Doctor never opens/unlocks the keychain or reports key contents."""
    variable = f"{provider.upper()}_API_KEY"
    if f"{variable}_FILE" in os.environ:
        try:
            _file_key(os.environ[f"{variable}_FILE"], provider)
            return {"source": "file", "configured": True, "verified": True}
        except CredentialError as exc:
            return {"source": "file", "configured": False, "verified": False, "error": str(exc)}
    if variable in os.environ:
        try:
            _validate_key(os.environ[variable], provider)
            return {"source": "environment", "configured": True, "verified": True}
        except CredentialError as exc:
            return {
                "source": "environment",
                "configured": False,
                "verified": False,
                "error": str(exc),
            }
    config = read_config()
    if f"{provider}_api_key" in config:
        return {"source": "unsupported_plaintext", "configured": False, "verified": False}
    saved = config.get(f"{provider}_key_storage") == "keyring"
    return {"source": "keyring" if saved else "none", "configured": saved, "verified": False}


def save_brave_key(value: str) -> None:
    _save_key(value, "brave")


def save_shodan_key(value: str) -> None:
    _save_key(value, "shodan")


def load_brave_key() -> str:
    return _load_key("brave")


def load_shodan_key() -> str:
    return _load_key("shodan")
