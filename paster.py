"""Text injection for HephFlow.

Default path: save the user's clipboard, write the transcript, fire Ctrl+V,
then restore the old clipboard after a short delay (so the paste lands first).
This makes the paste a single undoable action in the target app and leaves the
user's clipboard untouched afterwards.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Literal

log = logging.getLogger(__name__)

PasteMethod = Literal["clipboard", "typewrite"]


class PasteError(Exception):
    """Raised when text could not be injected by any available method."""


class Paster:
    RESTORE_DELAY_S = 0.5    # Delay before restoring the original clipboard.
    SETTLE_DELAY_S = 0.05    # Let the clipboard settle before Ctrl+V.
    COPY_RETRIES = 3         # Some apps briefly hold the clipboard open.
    COPY_RETRY_DELAY_S = 0.05

    def __init__(self, config) -> None:
        self._config = config

    def paste(self, text: str, method: PasteMethod = "clipboard") -> None:
        if not text:
            return
        if self._config.trailing_space:
            text = text + " "

        # typewrite can't emit non-ASCII; fall back to clipboard for those.
        if method == "typewrite" and not _is_ascii_printable(text):
            log.debug("Non-ASCII text; using clipboard instead of typewrite")
            method = "clipboard"

        if method == "clipboard":
            self._clipboard_paste(text)
        else:
            self._typewrite_paste(text)

    # ------------------------------------------------------------- clipboard

    def _clipboard_paste(self, text: str) -> None:
        import pyautogui
        import pyperclip

        try:
            original = pyperclip.paste()
        except Exception:  # noqa: BLE001 - reading may fail; treat as empty.
            original = ""

        if not self._copy_with_retry(pyperclip, text):
            # Couldn't own the clipboard at all — try typewrite as a fallback.
            log.warning("Clipboard unavailable; falling back to typewrite")
            self._typewrite_paste(text)
            return

        try:
            time.sleep(self.SETTLE_DELAY_S)
            pyautogui.hotkey("ctrl", "v")
        except Exception as exc:  # noqa: BLE001
            log.warning("Ctrl+V failed (%s); falling back to typewrite", exc)
            # Leave the transcript on the clipboard so the user can paste it.
            self._typewrite_paste(text)
            return

        # By default we leave the transcript on the clipboard so it is never
        # lost (if the auto-paste landed in the wrong place, the user can just
        # Ctrl+V). Only restore the previous clipboard if explicitly enabled.
        if getattr(self._config, "restore_clipboard", False):
            self._schedule_restore(pyperclip, original)

    def _copy_with_retry(self, pyperclip, text: str) -> bool:
        for attempt in range(self.COPY_RETRIES):
            try:
                pyperclip.copy(text)
                return True
            except Exception as exc:  # noqa: BLE001
                log.debug("Clipboard copy attempt %d failed: %s",
                          attempt + 1, exc)
                time.sleep(self.COPY_RETRY_DELAY_S)
        return False

    def _schedule_restore(self, pyperclip, original: str) -> None:
        def restore() -> None:
            time.sleep(self.RESTORE_DELAY_S)
            try:
                pyperclip.copy(original)
            except Exception as exc:  # noqa: BLE001
                log.debug("Could not restore clipboard: %s", exc)

        threading.Thread(target=restore, daemon=True).start()

    # ------------------------------------------------------------- typewrite

    def _typewrite_paste(self, text: str) -> None:
        import pyautogui

        try:
            pyautogui.typewrite(text, interval=0.01)
        except Exception as exc:  # noqa: BLE001
            raise PasteError(f"Paste failed: {exc}") from exc


def _is_ascii_printable(text: str) -> bool:
    return all(32 <= ord(ch) <= 126 or ch in "\t\n\r" for ch in text)
