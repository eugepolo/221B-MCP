# 221B

A local MCP server for OSINT research. Give your AI client tools to find public profiles,
search the web, inspect pages, and export findings with sources and timestamps.
No API keys required by default.

## Quick start

Requires Python 3.11+.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[sherlock]'
221b-mcp doctor
```

The `sherlock` extra enables username searches. Skip it with `pip install .` if you only
need the other tools.

Add a stdio server to your MCP client. For clients using `mcpServers` JSON:

```json
{
  "mcpServers": {
    "221b": {
      "command": "/absolute/path/to/221B-MCP/.venv/bin/221b-mcp",
      "args": ["serve"]
    }
  }
}
```

Replace the path with your installation. Your client starts the server; there is no
web UI or HTTP endpoint. Try asking: **“Use 221B to inspect https://example.org.”**

## Tools

| Tool | What it does |
| --- | --- |
| `search_web` | Keyless metasearch through DDGS, or optional Brave API search |
| `search_username` | Find candidate accounts using locally installed Sherlock |
| `inspect_page` | Extract text, links, and email addresses from public HTML/text pages |
| `lookup_domain` | Look up DNS records and available RDAP registration data |
| `search_archives` | Find Wayback captures of an exact URL |
| `export_findings` | Export saved evidence IDs as JSON or Markdown |

Username searches accept `depth`: **`light`** (default, 20 curated sites), **`dev`**
(developer platforms), or **`complete`** (all available Sherlock sites, including adult
sites, with upstream exclusions). An explicit `sites` list overrides the preset.
Allow a client tool timeout above 600 seconds for complete scans.

Results include source URLs, retrieval timestamps, and status information. Username
matches do not prove identity. Coverage varies, sites can block requests, and page
inspection does not render JavaScript.

## Configuration and data

Run `221b-mcp init` to select Brave and save its key in macOS Keychain, Windows
Credential Manager, or Linux Secret Service. Linux needs an available Secret Service
session. Setup fails if the OS store cannot save and read back the key.

For containers, set `BRAVE_API_KEY_FILE` to a mounted UTF-8 file containing the key.
Credential precedence is **secret file → `BRAVE_API_KEY` environment → OS store**.

Choose `provider="brave"` on a call, or set `MCP_221B_SEARCH_PROVIDER=brave`; a key alone does not switch providers.

`221b-mcp doctor` shows configuration, evidence, and log paths. OS-store presence is
reported from setup metadata, without unlocking or verifying the store. Override them with
`MCP_221B_CONFIG`, `MCP_221B_DATA_DIR`, and `MCP_221B_LOG_DIR`. Evidence is kept until
manually removed. Operational logs omit query contents and keys; external sources still
receive requests, and results are returned to your AI client.

## Docker

With Docker running, build and check the image:

```sh
docker build -t 221b-mcp .
docker run --rm 221b-mcp doctor
```

For an MCP client, use `docker` as the command with these arguments:

```text
run --rm -i -v 221b-data:/data 221b-mcp
```

Use `-i` without `-t`. The container runs as a non-root user; the named volume preserves
evidence and logs. Rebuild the image after code changes.

For Brave, mount a secret read-only and pass its path (never bake it into the image):

```sh
docker run --rm -i -v 221b-data:/data \
  --mount type=bind,src=/absolute/path/brave-key,dst=/run/secrets/brave,readonly \
  -e BRAVE_API_KEY_FILE=/run/secrets/brave \
  -e MCP_221B_SEARCH_PROVIDER=brave 221b-mcp
```

The file must be readable by container UID 10001. Mounted files are not encrypted by
221B; protect the host file or use your deployment's secret manager. `secrets/` is excluded
from Git and Docker builds. Host OS credentials are not automatically shared with containers.

## Development

```sh
python -m pip install -e '.[dev,sherlock]'
ruff check .
ruff format --check .
pytest -q
```

`server.py` owns the lifecycle, `tools.py` defines the public tools, and
`tool_handlers/` holds their implementations. `runtime.py` connects handlers to shared
services. Tests cover handlers and a real local MCP handshake without live web requests.
