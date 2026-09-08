"""Interactive configuration is separate from the noninteractive MCP process."""

import argparse
import getpass
import json

from osint_mcp import __version__
from osint_mcp.config import (
    brave_key,
    config_path,
    data_path,
    read_config,
    save_config,
    search_provider,
)
from osint_mcp.executables import sherlock_command
from osint_mcp.logging_setup import configure_logging, log_directory, logger


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
            print("Keys are stored as local plaintext (owner-only on POSIX).")
            key = getpass.getpass("Brave API key (Enter to keep current setting or skip): ").strip()
            if key:
                config["brave_api_key"] = key
        print(f"Configuration saved to {save_config(config)}")
    elif args.command == "doctor":
        print(
            json.dumps(
                {
                    "version": __version__,
                    "config_path": str(config_path()),
                    "data_path": str(data_path()),
                    "brave_configured": bool(brave_key()),
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
        from osint_mcp.server import mcp

        mcp.run(transport="stdio")
