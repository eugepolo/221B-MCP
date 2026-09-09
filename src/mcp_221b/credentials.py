"""credentials from explicit runtime sources or an OS credential store."""

import importlib
import os
import platform
import stat

from mcp_221b.config import read_config

SERVICE = "221b-mcp"
ACCOUNT = "brave-api-key"
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
            "or supply BRAVE_API_KEY_FILE. No plaintext fallback is used."
        ) from None


def _validate_key(value: str) -> str:
    value = value.strip()
    if not value or len(value.encode()) > MAX_SECRET_BYTES or any(c.isspace() for c in value):
        raise CredentialError("Brave key must be a nonempty token without whitespace.")
    return value


def save_brave_key(value: str) -> None:
    value = _validate_key(value)
    backend = _os_backend()
    try:
        backend.set_password(SERVICE, ACCOUNT, value)
        if backend.get_password(SERVICE, ACCOUNT) != value:
            raise RuntimeError
    except Exception:
        raise CredentialError(
            "Could not save and verify the Brave key in OS credential storage. "
            "Check that the credential store is unlocked and access is allowed."
        ) from None


def _file_key(path: str) -> str:
    try:
        # Avoid hanging on pipes/devices; mounted secret symlinks are supported.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise CredentialError("BRAVE_API_KEY_FILE must point to a regular file.")
            raw = stream.read(MAX_SECRET_BYTES + 1)
        if len(raw) > MAX_SECRET_BYTES:
            raise CredentialError("BRAVE_API_KEY_FILE exceeds the secret size limit.")
        return _validate_key(raw.decode("utf-8"))
    except (OSError, UnicodeError):
        raise CredentialError("Cannot read BRAVE_API_KEY_FILE as a UTF-8 secret file.") from None


def load_brave_key() -> str:
    if "BRAVE_API_KEY_FILE" in os.environ:
        return _file_key(os.environ["BRAVE_API_KEY_FILE"])
    if "BRAVE_API_KEY" in os.environ:
        return _validate_key(os.environ["BRAVE_API_KEY"])
    config = read_config()
    if "brave_api_key" in config:
        raise CredentialError(
            "Plaintext config keys are no longer read. Re-enter the key using 221b-mcp init "
            "or remove that field and supply a mounted secret."
        )
    if config.get("brave_key_storage") != "keyring":
        return ""
    backend = _os_backend()
    try:
        value = backend.get_password(SERVICE, ACCOUNT)
    except Exception:
        raise CredentialError(
            "Unlock the OS credential store and allow access, or use a mounted secret."
        ) from None
    if value is None:
        raise CredentialError("Saved Brave key was not found. Re-enter it using 221b-mcp init.")
    return _validate_key(value)


def credential_status() -> dict:
    """Doctor never opens/unlocks the keychain or reports key contents."""
    if "BRAVE_API_KEY_FILE" in os.environ:
        try:
            _file_key(os.environ["BRAVE_API_KEY_FILE"])
            return {"source": "file", "configured": True, "verified": True}
        except CredentialError as exc:
            return {"source": "file", "configured": False, "verified": False, "error": str(exc)}
    if "BRAVE_API_KEY" in os.environ:
        try:
            _validate_key(os.environ["BRAVE_API_KEY"])
            return {"source": "environment", "configured": True, "verified": True}
        except CredentialError as exc:
            return {
                "source": "environment",
                "configured": False,
                "verified": False,
                "error": str(exc),
            }
    config = read_config()
    if "brave_api_key" in config:
        return {"source": "unsupported_plaintext", "configured": False, "verified": False}
    saved = config.get("brave_key_storage") == "keyring"
    return {"source": "keyring" if saved else "none", "configured": saved, "verified": False}
