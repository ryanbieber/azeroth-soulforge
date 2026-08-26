from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
