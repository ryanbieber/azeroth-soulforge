"""Transport-neutral domain records used by the initial service scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID


class TraceOrigin(str, Enum):
    HUMAN = "human"
    GENERATED = "generated"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Trace:
    trace_id: UUID
    origin: TraceOrigin
    hop_count: int

    def __post_init__(self) -> None:
        if not 0 <= self.hop_count <= 1:
            raise ValueError("hop_count must be zero or one")


@dataclass(frozen=True, slots=True)
class Event:
    event_id: UUID
    realm_id: str
    event_type: str
    occurred_at: datetime
    actor_guid: str
    trace: Trace

    def __post_init__(self) -> None:
        _validate_realm(self.realm_id)
        _validate_guid(self.actor_guid)
        _validate_aware(self.occurred_at)


@dataclass(frozen=True, slots=True)
class Reply:
    reply_id: UUID
    source_event_id: UUID
    realm_id: str
    bot_guid: str
    text: str
    created_at: datetime
    expires_at: datetime
    trace: Trace

    def __post_init__(self) -> None:
        _validate_realm(self.realm_id)
        _validate_guid(self.bot_guid)
        _validate_aware(self.created_at)
        _validate_aware(self.expires_at)
        if not self.text or len(self.text) > 1024:
            raise ValueError("reply text must contain 1 to 1024 characters")
        if self.expires_at <= self.created_at:
            raise ValueError("reply must expire after it is created")
        if self.trace.origin is not TraceOrigin.GENERATED:
            raise ValueError("reply traces must have generated origin")

    def is_expired(self, now: datetime | None = None) -> bool:
        candidate = now or datetime.now(timezone.utc)
        _validate_aware(candidate)
        return candidate >= self.expires_at


def _validate_realm(value: str) -> None:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if not 1 <= len(value) <= 64 or any(char not in allowed for char in value):
        raise ValueError("invalid realm_id")


def _validate_guid(value: str) -> None:
    if not value.isascii() or not value.isdigit() or value.startswith("0") or len(value) > 20:
        raise ValueError("GUID must be a positive decimal string of at most 20 digits")


def _validate_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
