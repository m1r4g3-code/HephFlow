"""Settings window for HephFlow.

A small, native-looking panel reached from the tray. Saving applies changes
immediately (no restart): the hotkey is re-registered and the model is reloaded
in the background if it changed. Cancel reverts the widgets to current config.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QVBoxLayout, QWidget)

from config import APP_NAME

log = logging.getLogger(__name__)

MODELS = ["tiny", "base", "small", "medium",
          "distil-small.en", "distil-medium.en", "distil-large-v3"]
PASTE_METHODS = ["clipboard", "typewrite"]


class _HotkeyCapture(QObject):
    """Captures the next hotkey on a worker thread (keyboard.read_hotkey blocks)."""
    captured = pyqtSignal(str)

    def run(self) -> None:
        try:
            import keyboard
            hotkey = keyboard.read_hotkey(suppress=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("Hotkey capture failed: %s", exc)
            hotkey = ""
        self.captured.emit(hotkey)


class HotkeyField(QLineEdit):
    """Click to capture: records the next key combination as a hotkey string."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click, then press a key…")
        self._thread: QThread | None = None
        self._worker: _HotkeyCapture | None = None

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self._begin_capture()

    def _begin_capture(self) -> None:
        if self._thread is not None:
            return
        self.setText("Press a key…")
        self._thread = QThread()
        self._worker = _HotkeyCapture()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.captured.connect(self._on_captured)
        self._thread.start()

    def _on_captured(self, hotkey: str) -> None:
        if hotkey:
            self.setText(hotkey)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(1000)
        self._thread = None
        self._worker = None


class SettingsWindow(QWidget):
    # Emitted on Save with the set of changed field names for the app to apply.
    settings_saved = pyqtSignal(set)

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(f"{APP_NAME} Settings")
        self.setFixedWidth(380)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self._build()

    def _build(self) -> None:
        form = QFormLayout()

        self._hotkey = HotkeyField()
        self._model = QComboBox()
        self._model.addItems(MODELS)
        self._language = QLineEdit()
        self._language.setPlaceholderText("blank = auto-detect")
        self._paste = QComboBox()
        self._paste.addItems(PASTE_METHODS)
        self._trailing = QCheckBox("Append a space after pasted text")
        self._enhance = QCheckBox("Enhance audio (noise reduction + clarity)")
        self._sounds = QCheckBox("Play sound effects")
        self._startup = QCheckBox("Launch HephFlow when Windows starts")

        form.addRow("Hotkey:", self._hotkey)
        form.addRow("Model:", self._model)
        form.addRow("Language:", self._language)
        form.addRow("Paste method:", self._paste)
        form.addRow("Trailing space:", self._trailing)
        form.addRow("Audio enhance:", self._enhance)
        form.addRow("Sound effects:", self._sounds)
        form.addRow("Startup:", self._startup)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        buttons.addWidget(save)
        buttons.addWidget(cancel)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(buttons)

    # ------------------------------------------------------------- show/load

    def load_from_config(self) -> None:
        self._hotkey.setText(self._config.hotkey)
        self._model.setCurrentText(self._config.model)
        self._language.setText(self._config.language)
        self._paste.setCurrentText(self._config.paste_method)
        self._trailing.setChecked(self._config.trailing_space)
        self._enhance.setChecked(self._config.enhance_audio)
        self._sounds.setChecked(self._config.sound_effects)
        self._startup.setChecked(self._config.startup_with_windows)

    def open_panel(self) -> None:
        self.load_from_config()
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------- save

    def _on_save(self) -> None:
        changed: set[str] = set()
        cfg = self._config

        new_hotkey = self._hotkey.text().strip() or cfg.hotkey
        if new_hotkey != cfg.hotkey:
            cfg.hotkey = new_hotkey
            changed.add("hotkey")
        if self._model.currentText() != cfg.model:
            cfg.model = self._model.currentText()
            changed.add("model")
        if self._language.text().strip() != cfg.language:
            cfg.language = self._language.text().strip()
            changed.add("language")
        if self._paste.currentText() != cfg.paste_method:
            cfg.paste_method = self._paste.currentText()
            changed.add("paste_method")
        if self._trailing.isChecked() != cfg.trailing_space:
            cfg.trailing_space = self._trailing.isChecked()
            changed.add("trailing_space")
        if self._enhance.isChecked() != cfg.enhance_audio:
            cfg.enhance_audio = self._enhance.isChecked()
            changed.add("enhance_audio")
        if self._sounds.isChecked() != cfg.sound_effects:
            cfg.sound_effects = self._sounds.isChecked()
            changed.add("sound_effects")
        if self._startup.isChecked() != cfg.startup_with_windows:
            cfg.startup_with_windows = self._startup.isChecked()
            changed.add("startup_with_windows")

        cfg.save()
        log.info("Settings saved; changed=%s", changed)
        self.settings_saved.emit(changed)
        self.close()
