"""System tray icon and context menu for HephFlow.

The app has no main window; the tray is the primary surface. Icon color
reflects state (idle/recording/error), and the right-click menu exposes
Settings, Pause/Resume, About, and Quit.
"""

from __future__ import annotations

import logging
import os
import sys

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon
from PyQt6.QtCore import pyqtSignal

from config import APP_NAME

log = logging.getLogger(__name__)

VERSION = "1.0.0"
GITHUB_URL = "https://github.com/"  # Placeholder; update for release.


def _asset(name: str) -> str:
    """Resolve an asset path, honoring a PyInstaller bundle dir."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(
        os.path.abspath(sys.argv[0])) or ".")
    return os.path.join(base, "assets", name)


class TrayIcon(QSystemTrayIcon):
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    pause_toggled = pyqtSignal(bool)  # True == now paused.

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paused = False
        self._icon_idle = QIcon(_asset("icon_idle.ico"))
        self._icon_recording = QIcon(_asset("icon_recording.png"))
        self._icon_error = QIcon(_asset("icon_error.png"))

        self.setIcon(self._icon_idle)
        self.setToolTip(f"{APP_NAME} — Ready")
        self._build_menu()
        self.activated.connect(self._on_activated)

    def _build_menu(self) -> None:
        menu = QMenu()
        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self.settings_requested.emit)

        self._pause_action = QAction("Pause", menu)
        self._pause_action.triggered.connect(self._toggle_pause)

        about_action = QAction("About", menu)
        about_action.triggered.connect(self._show_about)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_requested.emit)

        menu.addAction(settings_action)
        menu.addAction(self._pause_action)
        menu.addSeparator()
        menu.addAction(about_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.setContextMenu(menu)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.settings_requested.emit()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._pause_action.setText("Resume" if self._paused else "Pause")
        if self._paused:
            self.setToolTip(f"{APP_NAME} — Paused")
        else:
            self.setToolTip(f"{APP_NAME} — Ready")
        self.pause_toggled.emit(self._paused)

    def _show_about(self) -> None:
        QMessageBox.about(
            None,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> v{VERSION}<br><br>"
            "Local-first push-to-talk speech-to-text.<br>"
            "Offline. No account. Owned by you.<br><br>"
            f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>',
        )

    # ------------------------------------------------------------- state

    def set_state(self, state: str) -> None:
        """state is the app state string (RECORDING/ERROR/IDLE/...)."""
        if state == "RECORDING":
            self.setIcon(self._icon_recording)
            self.setToolTip(f"{APP_NAME} — Recording…")
        elif state == "ERROR":
            self.setIcon(self._icon_error)
            self.setToolTip(f"{APP_NAME} — Error")
        elif state == "IDLE":
            self.setIcon(self._icon_error if self._paused else self._icon_idle)
            self.setToolTip(
                f"{APP_NAME} — {'Paused' if self._paused else 'Ready'}")
        # TRANSCRIBING / DONE: keep current icon.

    def set_tooltip(self, text: str) -> None:
        self.setToolTip(f"{APP_NAME} — {text}")
