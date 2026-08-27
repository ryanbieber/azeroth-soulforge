from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = spec_from_file_location("soulforge_control", Path(__file__).parents[1] / "server.py")
control = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(control)


class ControlSettingsTests(unittest.TestCase):
    def test_config_values_are_replaced_without_touching_other_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = control.CONFIG_DIR
            control.CONFIG_DIR = Path(directory)
            try:
                path = control.CONFIG_DIR / "modules" / "playerbots.conf"
                path.parent.mkdir()
                path.write_text("Other.Setting = 7\nAiPlayerbot.MinRandomBots = 50\n", encoding="utf-8")
                control.write_config_value("modules/playerbots.conf", "AiPlayerbot.MinRandomBots", 75)
                self.assertEqual(
                    control.read_config_value("modules/playerbots.conf", "AiPlayerbot.MinRandomBots", 0), 75
                )
                self.assertIn("Other.Setting = 7", path.read_text(encoding="utf-8"))
            finally:
                control.CONFIG_DIR = original

    def test_auction_house_character_must_be_logged_out_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = control.CONFIG_DIR
            control.CONFIG_DIR = Path(directory)
            try:
                path = control.CONFIG_DIR / "modules" / "mod_ahbot.conf"
                path.parent.mkdir()
                path.write_text(
                    "AuctionHouseBot.Account = 0\nAuctionHouseBot.GUID = 0\n"
                    "AuctionHouseBot.EnableSeller = 0\nAuctionHouseBot.EnableBuyer = 0\n"
                    "AuctionHouseBot.ItemsPerCycle = 200\n",
                    encoding="utf-8",
                )
                with patch.object(control, "mysql", return_value="42\tAuctioneer\t7\tOWNER\t1\n"):
                    with self.assertRaisesRegex(ValueError, "log out"):
                        control.update_auction_house_settings({
                            "auction_house_character_guid": "42", "auction_house_seller": True,
                        })
            finally:
                control.CONFIG_DIR = original

    def test_realm_name_rejects_sql_metacharacters(self) -> None:
        with self.assertRaises(ValueError):
            control.update_realm_name("Realm'; DROP TABLE realmlist; --")

    def test_realm_type_updates_gameplay_and_realm_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = control.CONFIG_DIR
            control.CONFIG_DIR = Path(directory)
            try:
                path = control.CONFIG_DIR / "worldserver.conf"
                path.write_text("GameType = 0\n", encoding="utf-8")
                with patch.object(control, "mysql") as mysql:
                    control.update_realm_type("pvp")
                self.assertEqual(control.realm_type(), "pvp")
                self.assertIn("GameType = 1", path.read_text(encoding="utf-8"))
                mysql.assert_called_once_with("UPDATE realmlist SET icon=1 WHERE id=1;", "acore_auth")
            finally:
                control.CONFIG_DIR = original

    def test_realm_type_rejects_unknown_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "realm_type must be one of"):
            control.update_realm_type("ffa")

    def test_grouped_xp_rate_accepts_decimals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = control.CONFIG_DIR
            control.CONFIG_DIR = Path(directory)
            try:
                path = control.CONFIG_DIR / "worldserver.conf"
                keys = control.RATE_SETTING_KEYS["xp_rate"][1]
                path.write_text("\n".join(f"{key} = 1" for key in keys) + "\n", encoding="utf-8")
                control.update_rate_setting("xp_rate", 2.5)
                for key in keys:
                    self.assertEqual(control.read_config_value("worldserver.conf", key, 1.0), 2.5)
            finally:
                control.CONFIG_DIR = original

    def test_rate_rejects_boolean_and_out_of_range_values(self) -> None:
        for value in (True, 0, 10.1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "xp_rate must be between"):
                control.update_rate_setting("xp_rate", value)
        with self.assertRaisesRegex(ValueError, "profession_skill_rate must be between"):
            control.update_rate_setting("profession_skill_rate", 2.5)

    def test_random_bot_ceiling_is_two_thousand(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = control.CONFIG_DIR
            control.CONFIG_DIR = Path(directory)
            try:
                path = control.CONFIG_DIR / "modules" / "playerbots.conf"
                path.parent.mkdir()
                path.write_text(
                    "AiPlayerbot.MinRandomBots = 50\nAiPlayerbot.MaxRandomBots = 50\n",
                    encoding="utf-8",
                )
                control.update_setting("random_bots", 2000)
                self.assertEqual(
                    control.read_config_value("modules/playerbots.conf", "AiPlayerbot.MinRandomBots", 0),
                    2000,
                )
                with self.assertRaisesRegex(ValueError, "random_bots must be between"):
                    control.update_setting("random_bots", 2001)
            finally:
                control.CONFIG_DIR = original

    def test_roster_flags_personal_characters_as_player_added_companions(self) -> None:
        with patch.object(
            control,
            "mysql",
            return_value=(
                "101\tWorldbot\t19\t1\t1\t1\trndbot1\t0\n"
                "202\tWife\t1\t2\t7\t0\tCARNufex\t1\n"
            ),
        ):
            bots = control.list_bots()
        self.assertFalse(bots[0]["player_added"])
        self.assertTrue(bots[1]["player_added"])

    def test_auction_house_requires_a_character_before_enabling(self) -> None:
        with self.assertRaisesRegex(ValueError, "choose a dedicated"):
            control.update_auction_house_settings({
                "auction_house_character_guid": "0", "auction_house_seller": True,
            })

    def test_auction_house_character_and_modes_are_written_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = control.CONFIG_DIR
            control.CONFIG_DIR = Path(directory)
            try:
                path = control.CONFIG_DIR / "modules" / "mod_ahbot.conf"
                path.parent.mkdir()
                path.write_text(
                    "AuctionHouseBot.Account = 0\nAuctionHouseBot.GUID = 0\n"
                    "AuctionHouseBot.EnableSeller = 0\nAuctionHouseBot.EnableBuyer = 0\n"
                    "AuctionHouseBot.ItemsPerCycle = 200\n",
                    encoding="utf-8",
                )
                with patch.object(control, "mysql", return_value="42\tAuctioneer\t7\tOWNER\t0\n"):
                    changed = control.update_auction_house_settings({
                        "auction_house_character_guid": "42", "auction_house_seller": True,
                        "auction_house_buyer": False, "auction_house_items_per_cycle": 125,
                    })
                self.assertTrue(changed)
                text = path.read_text(encoding="utf-8")
                self.assertIn("AuctionHouseBot.Account = 7", text)
                self.assertIn("AuctionHouseBot.GUID = 42", text)
                self.assertIn("AuctionHouseBot.EnableSeller = 1", text)
                self.assertIn("AuctionHouseBot.ItemsPerCycle = 125", text)
            finally:
                control.CONFIG_DIR = original


if __name__ == "__main__":
    unittest.main()
