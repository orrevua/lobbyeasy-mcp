# Record the README GIF:  vhs docs/demo.tape   (https://github.com/charmbracelet/vhs)
Output docs/demo.gif
Set Shell "bash"
Set FontSize 15
Set Width 1200
Set Height 720
Set TypingSpeed 35ms
Set Theme "Catppuccin Mocha"

Type "# lobbyeasy-mcp: talk to the lobby through MCP (demo data, no DB needed)"
Enter
Sleep 1s
Type "uv run python scripts/demo.py | head -60"
Enter
Sleep 6s
Type "LOBBY_ENABLE_WRITES=true LOBBY_ROLE=porteiro uv run lobbyeasy-mcp --version"
Enter
Sleep 2s
# Better still: record a Claude Code session after `claude mcp add lobbyeasy -- uvx lobbyeasy-mcp`
# asking "Quais encomendas estão esperando há mais tempo?" and replace docs/demo.gif.
