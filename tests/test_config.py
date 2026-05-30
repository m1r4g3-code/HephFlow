"""T-04: Config persistence and resilience."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config.json")

    def test_missing_file_creates_defaults(self) -> None:
        cfg = Config.load(self.path)
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(cfg.hotkey, "right alt")
        self.assertEqual(cfg.model, "distil-medium.en")

    def test_missing_field_defaults(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"hotkey": "f13"}, fh)  # everything else absent
        cfg = Config.load(self.path)
        self.assertEqual(cfg.hotkey, "f13")
        self.assertEqual(cfg.model, "distil-medium.en")   # defaulted
        self.assertTrue(cfg.trailing_space)               # defaulted

    def test_corrupt_json_regenerates(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not valid json ")
        cfg = Config.load(self.path)               # must not raise
        self.assertEqual(cfg.model, "distil-medium.en")
        # File should now be valid JSON again.
        with open(self.path, "r", encoding="utf-8") as fh:
            json.load(fh)

    def test_invalid_values_coerced(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"model": "gigantic", "paste_method": "telepathy",
                       "log_level": "LOUD"}, fh)
        cfg = Config.load(self.path)
        self.assertEqual(cfg.model, "small")
        self.assertEqual(cfg.paste_method, "clipboard")
        self.assertEqual(cfg.log_level, "WARNING")

    def test_pill_position_null_normalized(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"pill_position": [None, None]}, fh)
        cfg = Config.load(self.path)
        self.assertFalse(cfg.has_pill_position)
        cfg.pill_position = [100, 200]
        self.assertTrue(cfg.has_pill_position)

    def test_language_or_none(self) -> None:
        cfg = Config.load(self.path)
        cfg.language = ""
        self.assertIsNone(cfg.language_or_none)
        cfg.language = "en"
        self.assertEqual(cfg.language_or_none, "en")

    def test_roundtrip_save_load(self) -> None:
        cfg = Config.load(self.path)
        cfg.hotkey = "ctrl+shift+space"
        cfg.model = "tiny"
        cfg.pill_position = [10, 20]
        cfg.save()
        reloaded = Config.load(self.path)
        self.assertEqual(reloaded.hotkey, "ctrl+shift+space")
        self.assertEqual(reloaded.model, "tiny")
        self.assertEqual(reloaded.pill_position, [10, 20])


if __name__ == "__main__":
    unittest.main()
