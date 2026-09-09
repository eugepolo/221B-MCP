"""Interactive configuration is separate from the noninteractive MCP process."""

import argparse
import getpass
import json

from mcp_221b import __version__
from mcp_221b.config import (
    config_path,
    data_path,
    read_config,
    save_config,
    search_provider,
)
from mcp_221b.credentials import CredentialError, credential_status, save_brave_key
from mcp_221b.executables import sherlock_command
from mcp_221b.logging_setup import configure_logging, log_directory, logger


def main():
    parser = argparse.ArgumentParser(description="Local public-source investigation tools for MCP")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("command", nargs="?", choices=["serve", "init", "doctor"], default="serve")
    args = parser.parse_args()
    if args.command == "init":
        config = read_config()
        print("Web search defaults to keyless metasearch. Brave API is optional.")
        current = config.get("search_provider", "keyless")
        while True:
            provider = input(f"Default search provider [keyless/brave] ({current}): ").strip()
            provider = provider or current
            if provider in {"keyless", "brave"}:
                break
            print("Choose keyless or brave.")
        config["search_provider"] = provider
        if provider == "brave":
            print("The key will be saved in your OS credential store.")
            key = getpass.getpass("Brave API key (Enter to keep current setting or skip): ").strip()
            if key:
                try:
                    save_brave_key(key)
                except CredentialError as exc:
                    parser.exit(1, f"{exc}\n")
                config["brave_key_storage"] = "keyring"
                config.pop("brave_api_key", None)
        if "brave_api_key" in config:
            parser.exit(
                1, "Re-enter the key to replace the old plaintext setting, or remove that field.\n"
            )
        print(f"Configuration saved to {save_config(config)}")
    elif args.command == "doctor":
        credentials = credential_status()
        print(
            json.dumps(
                {
                    "version": __version__,
                    "config_path": str(config_path()),
                    "data_path": str(data_path()),
                    "brave_configured": credentials["configured"],
                    "brave_credentials": credentials,
                    "search_provider": search_provider(),
                    "sherlock_installed": sherlock_command() is not None,
                    "transport": "stdio",
                    "log_directory": str(log_directory()),
                },
                indent=2,
            )
        )
    else:
        configure_logging()
        logger.info("server_starting")
        from mcp_221b.server import mcp

        mcp.run(transport="stdio")
