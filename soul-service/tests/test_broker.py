from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from soulforge import Broker, DuplicateStatus, Event, Reply, Trace, UnknownReply
from soulforge.models import TraceOrigin


class BrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 25, tzinfo=timezone.utc)
        self.event = Event(
            event_id=uuid4(),
            realm_id="local-realm",
            event_type="chat.whisper",
            occurred_at=self.now,
            actor_guid="1",
            trace=Trace(uuid4(), TraceOrigin.HUMAN, 0),
        )
        self.broker = Broker()

    def make_reply(self, **overrides: object) -> Reply:
        values = {
            "reply_id": uuid4(),
            "source_event_id": self.event.event_id,
            "realm_id": "local-realm",
            "bot_guid": "2",
            "text": "I remember our promise.",
            "created_at": self.now,
            "expires_at": self.now + timedelta(seconds=60),
            "trace": Trace(self.event.trace.trace_id, TraceOrigin.GENERATED, 1),
        }
        values.update(overrides)
        return Reply(**values)  # type: ignore[arg-type]

    def test_event_ingestion_is_idempotent(self) -> None:
        self.assertEqual(self.broker.accept_event(self.event), DuplicateStatus.ACCEPTED)
        self.assertEqual(self.broker.accept_event(self.event), DuplicateStatus.DUPLICATE)

    def test_reused_event_id_with_changed_payload_is_rejected(self) -> None:
        self.broker.accept_event(self.event)
        changed = Event(
            event_id=self.event.event_id,
            realm_id=self.event.realm_id,
            event_type="boss.kill",
            occurred_at=self.now,
            actor_guid="1",
            trace=self.event.trace,
        )
        with self.assertRaises(ValueError):
            self.broker.accept_event(changed)

    def test_replies_are_filtered_by_realm_expiry_and_acknowledgement(self) -> None:
        self.broker.accept_event(self.event)
        live = self.make_reply()
        expired = self.make_reply(expires_at=self.now + timedelta(seconds=1))
        other_realm = self.make_reply(realm_id="other-realm")
        self.broker.enqueue_reply(live)
        self.broker.enqueue_reply(expired)
        self.broker.enqueue_reply(other_realm)

        observed = self.broker.pending_replies(
            "local-realm", now=self.now + timedelta(seconds=2)
        )
        self.assertEqual(observed, [live])

        self.broker.acknowledge(live.reply_id)
        self.assertEqual(
            self.broker.pending_replies("local-realm", now=self.now + timedelta(seconds=2)),
            [],
        )
        self.broker.acknowledge(live.reply_id)

    def test_reply_requires_known_source_event(self) -> None:
        with self.assertRaises(ValueError):
            self.broker.enqueue_reply(self.make_reply())

    def test_unknown_acknowledgement_is_rejected(self) -> None:
        with self.assertRaises(UnknownReply):
            self.broker.acknowledge(uuid4())

    def test_trace_hop_limit_is_enforced(self) -> None:
        with self.assertRaises(ValueError):
            Trace(uuid4(), TraceOrigin.GENERATED, 2)


if __name__ == "__main__":
    unittest.main()
