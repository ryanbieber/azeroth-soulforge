import unittest
from uuid import uuid4

from soulforge.providers import SecretCipher
from soulforge.server import SoulStore
from soulforge.world import WorldRepository, companion_roles, select_dungeon_group


class WorldRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SoulStore(":memory:")
        self.worlds = WorldRepository(self.store, "http://ollama:11434", "local-model")

    def test_fresh_world_is_immutable_and_binds_complementary_party(self) -> None:
        request = {"seed_prompt": "A rain-soaked fresh realm where old promises matter.",
                   "faction": "alliance", "player_role": "dps"}
        bots = [
            {"guid": "10", "name": "Tank", "race": 1, "class": 1, "level": 1},
            {"guid": "11", "name": "Healer", "race": 3, "class": 5, "level": 1},
            {"guid": "12", "name": "Mage", "race": 7, "class": 8, "level": 1},
            {"guid": "13", "name": "Rogue", "race": 4, "class": 4, "level": 1},
        ]
        world = self.worlds.activate_world(
            request,
            {"premise": "Rain binds every promise.", "starting_tensions": ["The road is unsafe."],
             "initial_plans": [{"title": "Missing caravan", "hint": "No wagon arrived.",
                                "after_played_minutes": 1}]},
            bots,
            [],
        )
        self.assertEqual(world["seed_prompt"], request["seed_prompt"])
        self.assertEqual([item["role"] for item in self.worlds.companions()],
                         ["tank", "healer", "dps", "dps"])
        self.assertEqual(self.worlds.rumors()[0]["hint"], "No wagon arrived.")
        self.worlds.record_presence(1, 1800)
        due = self.worlds.claim_due_plan()
        self.assertEqual(due["title"], "Missing caravan")
        self.worlds.finish_plan(due["id"], "The caravan never reached the gates.")
        self.assertEqual(self.worlds.memories()[0]["kind"], "narrative_event")
        with self.assertRaisesRegex(ValueError, "active world"):
            self.worlds.create_forge_job("A second sufficiently detailed fresh world prompt.", "horde", "tank")

    def test_provider_keys_are_never_returned_and_usage_is_normalized(self) -> None:
        cipher = SecretCipher("a-test-installation-master-key")
        saved = self.worlds.save_provider({
            "id": "paid", "name": "Paid AI", "kind": "openai",
            "base_url": "https://api.example.invalid", "input_cost_micros": 2_000_000,
            "output_cost_micros": 10_000_000,
        }, cipher.encrypt("super-secret-api-key"))
        self.assertTrue(saved["has_secret"])
        self.assertNotIn("secret_ciphertext", saved)
        private = self.worlds.provider("paid", include_secret=True)
        self.assertEqual(cipher.decrypt(private["secret_ciphertext"]), "super-secret-api-key")
        self.worlds.record_usage("director", private, "model", {
            "input_tokens": 1000, "cached_input_tokens": 0, "reasoning_tokens": 0,
            "output_tokens": 100, "total_tokens": 1100,
        }, 25, True)
        summary = self.worlds.usage_summary()
        self.assertEqual(summary["total_tokens"], 1100)
        self.assertEqual(summary["estimated_cost_micros"], 3000)
        self.assertEqual(len(summary["series"]), 24)
        self.assertEqual(summary["series"][-1]["input_tokens"], 1000)
        self.assertEqual(summary["series"][-1]["output_tokens"], 100)
        self.assertEqual(summary["series"][-1]["requests"], 1)

    def test_kill_switch_and_optional_cap_persist(self) -> None:
        defaults = self.worlds.ai_state()
        self.assertEqual(defaults["ambient_reply_percent"], 25)
        self.assertEqual(defaults["ambient_cooldown_seconds"], 5)
        self.assertTrue(defaults["current_events_enabled"])
        self.assertEqual(defaults["current_events_percent"], 15)
        state = self.worlds.save_ai_state({"enabled": False, "monthly_cap_micros": 500_000,
                                           "auto_stop_minutes": 15, "ambient_enabled": True,
                                           "ambient_reply_percent": 7, "ambient_cooldown_seconds": 45,
                                           "current_events_enabled": True,
                                           "current_events_percent": 20,
                                           "current_events_feed_url":
                                           "https://feeds.bbci.co.uk/news/world/rss.xml"})
        self.assertFalse(state["enabled"])
        self.assertEqual(state["monthly_cap_micros"], 500_000)
        self.assertEqual(state["auto_stop_minutes"], 15)
        self.assertEqual(state["ambient_reply_percent"], 7)
        self.assertEqual(state["ambient_cooldown_seconds"], 45)
        self.assertEqual(state["current_events_percent"], 20)
        with self.assertRaisesRegex(ValueError, "supported BBC News"):
            self.worlds.save_ai_state({"current_events_feed_url": "https://127.0.0.1/feed"})
        self.assertEqual(self.worlds.routes()["ambient"]["model"], "qwen3:1.7b")
        self.assertEqual(self.worlds.routes()["ambient"]["max_tokens"], 96)
        self.assertEqual(self.worlds.routes()["social"]["model"], "qwen3:1.7b")
        self.assertEqual(self.worlds.routes()["social"]["max_tokens"], 160)

    def test_group_selection_respects_faction(self) -> None:
        self.assertEqual(companion_roles("tank"), ["healer", "dps", "dps", "dps"])
        with self.assertRaisesRegex(ValueError, "alliance tank"):
            select_dungeon_group([
                {"guid": "1", "name": "Orc", "race": 2, "class": 1},
            ], "alliance", "dps")

    def test_dialogue_reads_canon_and_uses_bounded_memory_compaction(self) -> None:
        world = self.worlds.activate_world(
            {"seed_prompt": "A fresh realm where the autumn moon never wanes.",
             "faction": "alliance", "player_role": "dps"},
            {"premise": "The autumn moon watches every oath.",
             "starting_tensions": ["A bell rings beneath Goldshire."], "initial_plans": []},
            [
                {"guid": "10", "name": "Tank", "race": 1, "class": 1},
                {"guid": "11", "name": "Healer", "race": 3, "class": 5},
                {"guid": "12", "name": "Mage", "race": 7, "class": 8},
                {"guid": "13", "name": "Rogue", "race": 4, "class": 4},
            ],
            [],
        )
        event = {
            "event_id": str(uuid4()), "realm_id": "azeroth-soulforge",
            "actor": {"guid": "1", "name": "Owner"},
            "participants": [{"guid": "10", "name": "Tank"}],
            "channel": "whisper", "text": "Did you hear the bell?",
            "trace": {"trace_id": str(uuid4())},
        }
        prompt = self.store.build_prompt(event)
        self.assertIsNotNone(prompt)
        self.assertIn("The autumn moon watches every oath", prompt[2])
        self.assertIn("A bell rings beneath Goldshire", prompt[2])
        self.assertIn("exact words Tank would type into the WoW chat box", prompt[2])

        self.store.complete(event, "I heard it under the road stones.")
        pending = self.store.pending("azeroth-soulforge", 10)
        self.assertEqual(pending[0]["channel"], "whisper")
        self.assertEqual(pending[0]["recipient_guid"], "1")
        self.assertEqual(len(self.worlds.memory_candidates(world["id"])), 1)
        self.assertFalse([item for item in self.worlds.memories() if item["kind"] == "conversation"])

        for index in range(40):
            event["event_id"] = str(uuid4())
            event["trace"]["trace_id"] = str(uuid4())
            event["text"] = f"Transient exchange {index}"
            self.store.complete(event, f"Transient answer {index}")
        connection = self.store.connect()
        personal_count = connection.execute(
            "SELECT COUNT(*) AS count FROM memories WHERE realm_id=? AND bot_guid=?",
            ("azeroth-soulforge", "10"),
        ).fetchone()["count"]
        self.store.close(connection)
        self.assertEqual(personal_count, 60)
        candidates = self.worlds.memory_candidates(world["id"])
        self.assertEqual(len(candidates), 12)

        connection = self.store.connect()
        connection.executemany(
            """INSERT INTO world_memories(world_id,kind,text,importance,created_at)
               VALUES(?,'relationship',?,1,'2026-08-29T00:00:00Z')""",
            [(world["id"], f"Old distilled fact {index}") for index in range(405)],
        )
        connection.commit()
        self.store.close(connection)
        self.worlds.finish_memory_compaction(
            world["id"], [item["id"] for item in candidates],
            [{"kind": "relationship", "text": "Owner trusts Tank's hearing.", "importance": 4}],
        )
        self.assertEqual(self.worlds.memory_candidates(world["id"]), [])
        self.assertIn("Owner trusts Tank", self.worlds.memories()[0]["text"])
        connection = self.store.connect()
        distilled_count = connection.execute(
            """SELECT COUNT(*) AS count FROM world_memories WHERE world_id=?
               AND kind NOT IN ('founding','narrative_event')""",
            (world["id"],),
        ).fetchone()["count"]
        self.store.close(connection)
        self.assertEqual(distilled_count, 400)

    def test_proactive_world_event_is_queued_for_bridge_delivery(self) -> None:
        self.store.enqueue_proactive("plan-1", "azeroth-soulforge", "10", "1", "The road has changed.")
        pending = self.store.pending("azeroth-soulforge", 10)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["text"], "The road has changed.")

    def test_social_state_is_bounded_and_relationship_deltas_are_clamped(self) -> None:
        self._activate_test_world()
        self.worlds.apply_social_updates([{
            "source_guid": "10", "target_guid": "11", "mood": "Fired Up!", "energy": 150,
            "trust_delta": 99, "respect_delta": -99, "irritation_delta": 3,
            "rivalry_delta": 2, "summary": "Tank admired the rescue.",
        }])
        social = self.worlds.social_context()
        self.assertEqual(social["states"][0]["mood"], "firedup")
        self.assertEqual(social["states"][0]["energy"], 100)
        relation = social["relationships"][0]
        self.assertEqual(relation["trust"], 55)
        self.assertEqual(relation["respect"], 45)
        self.assertEqual(relation["irritation"], 3)
        self.assertTrue(self.worlds.claim_reaction("event-1", "10", 3, "boss.kill", 0))
        self.assertFalse(self.worlds.claim_reaction("event-1", "10", 3, "boss.kill", 0))

    def test_session_reflection_uses_bounded_event_summaries_and_callbacks(self) -> None:
        self._activate_test_world()
        transition = self.worlds.record_presence(1)
        session_id = transition["started"]
        for index in range(100):
            self.worlds.record_session_event({
                "event_id": str(uuid4()), "event_type": "quest.complete",
                "actor": {"name": "Owner"}, "text": f"Quest {index} completed",
                "context": {"zone_name": "Elwynn Forest"},
            })
        self.assertEqual(len(self.worlds.session_candidates(session_id)), 80)
        ended = self.worlds.record_presence(0)
        self.assertEqual(ended, {"ended": session_id})
        self.worlds.finish_session_reflection(session_id, {
            "summary": "The party protected Elwynn and left one lead unfinished.",
            "memories": [{"text": "The party protected Elwynn.", "importance": 4}] * 5,
            "unresolved": ["Return to the mine"],
            "callbacks": [{"bot_guid": "10", "topic": "the mine",
                           "text": "The mine still needs attention", "zone_name": "Elwynn Forest"}],
        })
        social = self.worlds.social_context()
        self.assertIn("protected Elwynn", social["reflection"]["summary"])
        self.assertEqual(len([m for m in self.worlds.memories() if m["kind"] == "session_reflection"]), 3)
        self.assertEqual(self.worlds.session_candidates(session_id), [])
        callback = self.worlds.claim_callback()
        self.assertEqual(callback["bot_guid"], "10")
        self.assertEqual(self.worlds.claim_callback()["id"], callback["id"])
        self.assertIsNone(self.worlds.claim_callback())

    def _activate_test_world(self) -> dict:
        return self.worlds.activate_world(
            {"seed_prompt": "A sufficiently detailed fresh realm for social tests.",
             "faction": "alliance", "player_role": "dps"},
            {"premise": "The road remembers.", "initial_plans": []},
            [
                {"guid": "10", "name": "Tank", "race": 1, "class": 1},
                {"guid": "11", "name": "Healer", "race": 3, "class": 5},
                {"guid": "12", "name": "Mage", "race": 7, "class": 8},
                {"guid": "13", "name": "Rogue", "race": 4, "class": 4},
            ], [],
        )


if __name__ == "__main__":
    unittest.main()
