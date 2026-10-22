"""Resident notifications. Stubbed: nothing leaves the process.

LobbyEasy itself has no notifications yet (its spec lists them as out of scope).
`Notifier` is the seam where a WhatsApp Cloud API / Twilio / e-mail sender would go;
`StubNotifier` records what *would* have been sent so tests and demos can inspect it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from lobbyeasy_mcp.pii import mask_phone

log = logging.getLogger("lobbyeasy_mcp.notifier")


@dataclass(frozen=True)
class SentNotification:
    provider_id: str
    to: str
    message: str
    sent_at: datetime
    channel: str


class Notifier(Protocol):
    channel: str

    async def send(self, to: str, message: str) -> SentNotification: ...


class StubNotifier:
    channel = "stub"

    def __init__(self) -> None:
        self.outbox: list[SentNotification] = []

    async def send(self, to: str, message: str) -> SentNotification:
        sent = SentNotification(
            provider_id=f"stub-{uuid.uuid4().hex[:12]}",
            to=to,
            message=message,
            sent_at=datetime.now(UTC),
            channel=self.channel,
        )
        self.outbox.append(sent)
        log.info("stub notification to %s (%d chars)", mask_phone(to), len(message))
        return sent
