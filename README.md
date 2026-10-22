# lobbyeasy-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for **LobbyEasy**, a building
lobby / package management app (Next.js + Supabase). It lets an AI assistant answer questions like
"which packages are still waiting in the lobby?".

> Milestone 1: stdio server, two read-only tools over in-memory demo data.

## Run it

```bash
uv sync
uv run lobbyeasy-mcp          # speaks MCP over stdin/stdout
```

## Connect a client

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "lobbyeasy": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/lobbyeasy-mcp", "run", "lobbyeasy-mcp"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add lobbyeasy -- uv --directory /absolute/path/to/lobbyeasy-mcp run lobbyeasy-mcp
```

### Cursor (`.cursor/mcp.json` or `~/.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "lobbyeasy": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/lobbyeasy-mcp", "run", "lobbyeasy-mcp"]
    }
  }
}
```

## Tools

| Tool | What it does |
|---|---|
| `list_pending_packages` | Packages with status `pendente`, newest first |
| `get_package` | One package by id |
