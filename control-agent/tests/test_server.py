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


if __name__ == "__main__":
    unittest.main()
