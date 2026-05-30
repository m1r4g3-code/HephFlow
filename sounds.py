"""Lightweight async sound cues for HephFlow.

Uses winsound (Windows stdlib) to play short WAV files without blocking the Qt
thread. Silently no-ops on non-Windows or if a file/sound device is missing.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)


def _asset(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(
        os.path.abspath(sys.argv[0])) or ".")
    return os.path.join(base, "assets", name)


class SoundPlayer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and sys.platform == "win32"
        self._start = _asset("snd_start.wav")
        self._done = _asset("snd_done.wav")
        self._error = _asset("snd_error.wav")

    def _play(self, path: str) -> None:
        if not self.enabled or not os.path.exists(path):
            return
        try:
            import winsound
            # ASYNC = non-blocking, NODEFAULT = silence if file missing.
            winsound.PlaySound(
                path,
                winsound.SND_FILENAME | winsound.SND_ASYNC
                | winsound.SND_NODEFAULT,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("Sound playback failed: %s", exc)

    def play_start(self) -> None:
        self._play(self._start)

    def play_done(self) -> None:
        self._play(self._done)

    def play_error(self) -> None:
        self._play(self._error)
