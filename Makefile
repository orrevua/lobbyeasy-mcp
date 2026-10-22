.PHONY: setup test lint demo
setup:
	uv sync
test:
	uv run pytest
lint:
	uv run ruff check . && uv run ruff format --check .
demo:
	uv run lobbyeasy-mcp
