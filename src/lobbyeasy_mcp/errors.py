"""User-facing errors.

Every message is written for the *model* that called the tool: say what went wrong
and what to do next (which tool to call, which argument to change). The MCP SDK
turns an exception raised inside a tool into a result with `isError: true`, so the
model sees the text and can recover on its own instead of the conversation dying.
"""


class LobbyError(Exception):
    """Base class for errors whose message is safe and useful to show the caller."""


class NotFoundError(LobbyError):
    pass


class InvalidInputError(LobbyError):
    pass


class PermissionDeniedError(LobbyError):
    pass


class ConflictError(LobbyError):
    """The request is valid but the current state forbids it (e.g. already withdrawn)."""
