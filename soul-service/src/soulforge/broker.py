"""Idempotent inbox and acknowledged outbox behavior.

This in-memory adapter defines semantics for the scaffold. The production
adapter will persist the same operations transactionally in SQLite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from uuid import UUID

from .models import Event, Reply


class DuplicateStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


class UnknownReply(KeyError):
    pass


class Broker:
    def __init__(self) -> None:
        self._events: dict[UUID, Event] = {}
        self._replies: dict[UUID, Reply] = {}
        self._acknowledged: set[UUID] = set()
        self._lock = RLock()

    def accept_event(self, event: Event) -> DuplicateStatus:
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is not None:
                if existing != event:
                    raise ValueError("event_id was reused with a different payload")
                return DuplicateStatus.DUPLICATE
            self._events[event.event_id] = event
            return DuplicateStatus.ACCEPTED

    def enqueue_reply(self, reply: Reply) -> None:
        with self._lock:
            if reply.source_event_id not in self._events:
                raise ValueError("reply source event is unknown")
            existing = self._replies.get(reply.reply_id)
            if existing is not None and existing != reply:
                raise ValueError("reply_id was reused with a different payload")
            self._replies[reply.reply_id] = reply

    def pending_replies(
        self, realm_id: str, *, now: datetime | None = None, limit: int = 20
    ) -> list[Reply]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        candidate = now or datetime.now(timezone.utc)
        with self._lock:
            pending = [
                reply
                for reply_id, reply in self._replies.items()
                if reply.realm_id == realm_id
                and reply_id not in self._acknowledged
                and not reply.is_expired(candidate)
            ]
        return sorted(pending, key=lambda item: (item.created_at, str(item.reply_id)))[:limit]

    def acknowledge(self, reply_id: UUID) -> None:
        with self._lock:
            if reply_id not in self._replies:
                raise UnknownReply(str(reply_id))
            self._acknowledged.add(reply_id)
