"""Configuration persistence for HephFlow.

The Config dataclass mirrors config.json. Loading never raises: a missing,
corrupt, or partially-broken file falls back to defaults so the app always
starts. Saving is atomic (temp file + os.replace) so a crash mid-write cannot
corrupt the existing config.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields

log = logging.getLogger(__name__)

APP_NAME = "HephFlow"

# Valid choices used for light validation in __post_init__.
_VALID_MODELS = {"tiny", "base", "small", "medium",
                 "distil-small.en", "distil-medium.en", "distil-large-v3"}
_VALID_PASTE = {"clipboard", "typewrite"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


@dataclass
class Config:
    hotkey: str = "right alt"
    # Default engine: distilled medium, English-only — near-medium accuracy at
    # base-like speed on CPU. Change `model` to a multilingual one (e.g. "small")
    # and clear `language` to dictate in other languages.
    model: str = "distil-medium.en"
    language: str = "en"
    # Decoding beam width. 5 = accurate (beam search), 1 = fast (greedy).
    beam_size: int = 5
    paste_method: str = "clipboard"
    trailing_space: bool = True
    # When False (default), the transcript is left on the clipboard after
    # pasting so it can never be lost — if the auto-paste lands in the wrong
    # place, the user can click anywhere and Ctrl+V. When True, the previous
    # clipboard contents are restored shortly after pasting.
    restore_clipboard: bool = False
    # Run the voice-enhancement DSP (high-pass, noise gate, EQ, compression)
    # before transcription. Improves accuracy, especially with a noisy mic.
    enhance_audio: bool = True
    # Play subtle UI sound cues on start / done / error.
    sound_effects: bool = True
    startup_with_windows: bool = False
    # [x, y] of the pill's top-left, or [None, None] for default position.
    pill_position: list = field(default_factory=lambda: [None, None])
    log_level: str = "WARNING"

    # Path this config was loaded from / will be saved to. Not serialized.
    _path: str = field(default="config.json", repr=False, compare=False)

    def __post_init__(self) -> None:
        """Coerce/repair field values without ever raising."""
        if not isinstance(self.hotkey, str) or not self.hotkey.strip():
            self.hotkey = "right alt"

        if self.model not in _VALID_MODELS:
            log.warning("Invalid model %r, defaulting to 'small'", self.model)
            self.model = "small"

        if not isinstance(self.language, str):
            self.language = ""

        try:
            self.beam_size = max(1, min(10, int(self.beam_size)))
        except (TypeError, ValueError):
            self.beam_size = 5

        if self.paste_method not in _VALID_PASTE:
            log.warning("Invalid paste_method %r, defaulting to 'clipboard'",
                        self.paste_method)
            self.paste_method = "clipboard"

        self.trailing_space = bool(self.trailing_space)
        self.restore_clipboard = bool(self.restore_clipboard)
        self.enhance_audio = bool(self.enhance_audio)
        self.sound_effects = bool(self.sound_effects)
        self.startup_with_windows = bool(self.startup_with_windows)

        self.pill_position = self._normalize_position(self.pill_position)

        if self.log_level not in _VALID_LOG_LEVELS:
            self.log_level = "WARNING"

    @staticmethod
    def _normalize_position(value) -> list:
        """Return a clean [x, y] list (ints) or [None, None]."""
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return [None, None]
        x, y = value
        if x is None or y is None:
            return [None, None]
        try:
            return [int(x), int(y)]
        except (TypeError, ValueError):
            return [None, None]

    @property
    def language_or_none(self) -> str | None:
        """Empty language string means auto-detect (None for faster-whisper)."""
        return self.language.strip() or None

    @property
    def has_pill_position(self) -> bool:
        return self.pill_position[0] is not None and self.pill_position[1] is not None

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, path: str = "config.json") -> "Config":
        """Load config from JSON, falling back to defaults on any error.

        If the file is missing it is created with defaults. If it is corrupt
        it is regenerated with defaults (a warning is logged).
        """
        if not os.path.exists(path):
            cfg = cls(_path=path)
            cfg.save()
            return cfg

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("config root is not an object")
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log.warning("Config at %s unreadable (%s); regenerating defaults",
                        path, exc)
            cfg = cls(_path=path)
            cfg.save()
            return cfg

        # Keep only known fields; unknown keys are ignored, missing keys default.
        known = {f.name for f in fields(cls) if not f.name.startswith("_")}
        filtered = {k: v for k, v in data.items() if k in known}
        cfg = cls(_path=path, **filtered)
        return cfg

    # ------------------------------------------------------------------ save

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_path", None)
        return d

    def save(self) -> None:
        """Atomically write config to disk; also sync the autostart registry."""
        path = self._path
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            log.error("Failed to save config to %s: %s", path, exc)
            return

        # Keep the Windows "Run" registry key in sync with the setting.
        try:
            _set_autostart(self.startup_with_windows)
        except OSError as exc:
            log.warning("Could not update autostart registry: %s", exc)


# ---------------------------------------------------------------------------
# Windows autostart (HKCU Run key). No admin required for HKCU.
# ---------------------------------------------------------------------------

def _autostart_command() -> str:
    """Command Windows runs at login to launch HephFlow."""
    if getattr(sys, "frozen", False):
        # Packaged exe: launch the exe directly.
        return f'"{sys.executable}"'
    # Dev / source run: python main.py with absolute paths.
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else "main.py"
    return f'"{sys.executable}" "{script}"'


def _set_autostart(enabled: bool) -> None:
    """Add or remove the HephFlow entry from the HKCU Run key."""
    if sys.platform != "win32":
        return
    import winreg

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0,
                        winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                              _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
