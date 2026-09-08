# 221B

Local MCP tools for public-source investigations, packaged as `221b-mcp`.
Requires Python 3.11 or newer.

```sh
python -m pip install '.[sherlock]'
221b-mcp doctor
221b-mcp serve
```

The server uses stdio and is launched by an MCP client. Keyless search is the default;
run `221b-mcp init` to configure optional Brave API search.

The Python module is `mcp_221b`. Environment settings use the `MCP_221B_` prefix.
Default configuration and evidence paths use `221b-mcp`; `doctor` prints these paths.
Existing data from earlier installations is not moved automatically.

For development, install `.[dev,sherlock]` and run `pytest`.
