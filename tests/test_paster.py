"""T-03: Paster clipboard save/restore, trailing space, fallbacks.

pyperclip and pyautogui are replaced with fakes via sys.modules so the test
needs no real clipboard or GUI.
"""

import os
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeClipboard:
    def __init__(self) -> None:
        self.value = "ORIGINAL"
        self.copies: list[str] = []

    def paste(self) -> str:
        return self.value

    def copy(self, text: str) -> None:
        self.value = text
        self.copies.append(text)


class FakeAutoGui:
    def __init__(self) -> None:
        self.hotkeys: list[tuple] = []
        self.typed: list[str] = []

    def hotkey(self, *keys) -> None:
        self.hotkeys.append(keys)

    def typewrite(self, text, interval=0.0) -> None:
        self.typed.append(text)


class _Cfg:
    def __init__(self, trailing_space=True, restore_clipboard=False) -> None:
        self.trailing_space = trailing_space
        self.restore_clipboard = restore_clipboard


class PasterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clip = FakeClipboard()
        self.gui = FakeAutoGui()
        sys.modules["pyperclip"] = self.clip  # module-like duck typing
        sys.modules["pyautogui"] = self.gui
        # Import after patching so the lazy `import pyperclip` picks up fakes.
        if "paster" in sys.modules:
            del sys.modules["paster"]
        import paster
        self.paster_mod = paster

    def tearDown(self) -> None:
        sys.modules.pop("pyperclip", None)
        sys.modules.pop("pyautogui", None)

    def test_clipboard_paste_fires_ctrl_v(self) -> None:
        p = self.paster_mod.Paster(_Cfg(trailing_space=False))
        p.paste("hello", "clipboard")
        self.assertIn("hello", self.clip.copies)
        self.assertIn(("ctrl", "v"), self.gui.hotkeys)

    def test_trailing_space_appended(self) -> None:
        p = self.paster_mod.Paster(_Cfg(trailing_space=True))
        p.paste("hello", "clipboard")
        self.assertEqual(self.clip.copies[0], "hello ")

    def test_no_trailing_space(self) -> None:
        p = self.paster_mod.Paster(_Cfg(trailing_space=False))
        p.paste("hello", "clipboard")
        self.assertEqual(self.clip.copies[0], "hello")

    def test_clipboard_restored_after_delay_when_enabled(self) -> None:
        p = self.paster_mod.Paster(
            _Cfg(trailing_space=False, restore_clipboard=True))
        p.RESTORE_DELAY_S = 0.05  # speed up the test
        p.paste("hello", "clipboard")
        self.assertEqual(self.clip.value, "hello")   # transcript present now
        time.sleep(0.2)
        self.assertEqual(self.clip.value, "ORIGINAL")  # restored

    def test_transcript_kept_on_clipboard_by_default(self) -> None:
        # Default: restore_clipboard=False -> transcript stays so it's never lost
        p = self.paster_mod.Paster(_Cfg(trailing_space=False))
        p.paste("hello", "clipboard")
        time.sleep(0.2)
        self.assertEqual(self.clip.value, "hello")   # NOT restored

    def test_typewrite_method(self) -> None:
        p = self.paster_mod.Paster(_Cfg(trailing_space=False))
        p.paste("hello", "typewrite")
        self.assertEqual(self.gui.typed, ["hello"])

    def test_typewrite_falls_back_to_clipboard_for_unicode(self) -> None:
        p = self.paster_mod.Paster(_Cfg(trailing_space=False))
        p.paste("café", "typewrite")
        # Unicode -> clipboard path used instead of typewrite.
        self.assertIn("café", self.clip.copies)
        self.assertEqual(self.gui.typed, [])

    def test_empty_text_noop(self) -> None:
        p = self.paster_mod.Paster(_Cfg(trailing_space=True))
        p.paste("", "clipboard")
        self.assertEqual(self.clip.copies, [])


if __name__ == "__main__":
    unittest.main()
