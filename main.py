"""HephFlow — local-first push-to-talk speech-to-text for Windows.

Hold the hotkey, speak, release: the transcript is pasted at the cursor.

This module wires the pieces together and owns the state machine:

    IDLE -> RECORDING -> TRANSCRIBING -> IDLE
    (ERROR is reachable from RECORDING/TRANSCRIBING, then returns to IDLE)

Threading: the keyboard listener runs on its own daemon thread, so its
callbacks marshal onto the Qt thread via QMetaObject.invokeMethod before
touching any Qt object. Model loading runs on a worker QThread; transcription
runs on the global QThreadPool. Everything else lives on the Qt event loop.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from PyQt6.QtCore import (QMetaObject, QObject, Qt, QThread, pyqtSignal,
                          pyqtSlot)
from PyQt6.QtWidgets import QApplication

from config import APP_NAME, Config
from paster import Paster, PasteError
from recorder import Recorder
from sounds import SoundPlayer
from transcriber import Transcriber

log = logging.getLogger("hephflow")

# Application states.
IDLE = "IDLE"
RECORDING = "RECORDING"
TRANSCRIBING = "TRANSCRIBING"

CONFIG_PATH = "config.json"
LOG_PATH = "pressflow.log"
FALLBACK_HOTKEY = "f13"


# ---------------------------------------------------------------------------
# Model loading worker (runs load_model() off the Qt thread).
# ---------------------------------------------------------------------------

class _ModelLoader(QObject):
    finished = pyqtSignal()

    def __init__(self, transcriber: Transcriber) -> None:
        super().__init__()
        self._transcriber = transcriber

    @pyqtSlot()
    def run(self) -> None:
        self._transcriber.load_model()  # emits model_ready / model_error
        self.finished.emit()


# ---------------------------------------------------------------------------
# Global hotkey listener (push-to-talk). Bridges the keyboard library's daemon
# thread to Qt-side callbacks.
# ---------------------------------------------------------------------------

class HotkeyListener:
    """Registers a single-key push-to-talk hotkey with a fallback.

    keyboard's on_press_key auto-repeats while held; the App state machine
    ignores repeats by only acting on transitions.
    """

    def __init__(self, on_down, on_up) -> None:
        self._on_down = on_down
        self._on_up = on_up
        self._hooked: list = []
        self.active_hotkey: str | None = None

    def register(self, hotkey: str) -> str:
        """Register hotkey; fall back to F13 on conflict/error. Returns the
        hotkey actually registered."""
        import keyboard

        for candidate in (hotkey, FALLBACK_HOTKEY):
            try:
                self._unregister(keyboard)
                h_down = keyboard.on_press_key(candidate, self._down_cb,
                                               suppress=False)
                h_up = keyboard.on_release_key(candidate, self._up_cb,
                                               suppress=False)
                self._hooked = [h_down, h_up]
                self.active_hotkey = candidate
                if candidate != hotkey:
                    log.warning("Hotkey %r unavailable; using %r",
                                hotkey, candidate)
                else:
                    log.info("Registered hotkey %r", candidate)
                return candidate
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not register hotkey %r: %s", candidate, exc)
        self.active_hotkey = None
        return ""

    def _down_cb(self, _event) -> None:
        self._on_down()

    def _up_cb(self, _event) -> None:
        self._on_up()

    def _unregister(self, keyboard) -> None:
        for handle in self._hooked:
            try:
                keyboard.unhook(handle)
            except (KeyError, ValueError):
                pass
        self._hooked = []

    def unregister(self) -> None:
        import keyboard
        self._unregister(keyboard)
        self.active_hotkey = None


# ---------------------------------------------------------------------------
# Application orchestrator.
# ---------------------------------------------------------------------------

class App(QObject):
    # (state, message) — drives pill + tray in later milestones.
    state_changed = pyqtSignal(str, str)
    # 0..1 mic amplitude for the waveform visualizer.
    amplitude_changed = pyqtSignal(float)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._state = IDLE
        self._paused = False

        self._recorder = Recorder()
        self._transcriber = Transcriber(config.model, config.language_or_none,
                                        config.beam_size, config.enhance_audio)
        self._paster = Paster(config)
        self._sounds = SoundPlayer(config.sound_effects)
        self._hotkeys = HotkeyListener(self._key_down, self._key_up)

        self._model_thread: QThread | None = None
        self._model_loader: _ModelLoader | None = None

        self._wire_signals()

    # ------------------------------------------------------------- wiring

    def _wire_signals(self) -> None:
        self._recorder.recording_started.connect(self._on_recording_started)
        self._recorder.recording_stopped.connect(self._on_recording_stopped)
        self._recorder.audio_level_update.connect(self.amplitude_changed)
        self._recorder.recorder_error.connect(self._on_recorder_error)

        self._transcriber.transcription_done.connect(self._on_transcription_done)
        self._transcriber.transcription_error.connect(self._on_transcription_error)
        self._transcriber.model_error.connect(self._on_model_error)

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        self._load_model_async()
        registered = self._hotkeys.register(self._config.hotkey)
        if registered:
            log.info("HephFlow ready. Hold %r to dictate.", registered)
        else:
            log.error("No hotkey could be registered.")

    def shutdown(self) -> None:
        self._hotkeys.unregister()
        if self._model_thread is not None:
            self._model_thread.quit()
            self._model_thread.wait(2000)

    def _load_model_async(self) -> None:
        self._set_state(IDLE, "Loading model...")
        self._model_thread = QThread()
        self._model_loader = _ModelLoader(self._transcriber)
        self._model_loader.moveToThread(self._model_thread)
        self._model_thread.started.connect(self._model_loader.run)
        self._transcriber.model_ready.connect(self._on_model_ready)
        self._model_loader.finished.connect(self._model_thread.quit)
        self._model_thread.start()

    # ------------------------------------------------------------- hotkey CBs
    # These run on the keyboard daemon thread; marshal to the Qt thread.

    def _key_down(self) -> None:
        QMetaObject.invokeMethod(self, "_handle_key_down",
                                 Qt.ConnectionType.QueuedConnection)

    def _key_up(self) -> None:
        QMetaObject.invokeMethod(self, "_handle_key_up",
                                 Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _handle_key_down(self) -> None:
        if self._paused or self._state != IDLE:
            return
        if not self._transcriber.is_ready:
            log.debug("Model not ready; ignoring keypress")
            return
        self._set_state(RECORDING)
        self._recorder.start()

    @pyqtSlot()
    def _handle_key_up(self) -> None:
        if self._state != RECORDING:
            return
        self._recorder.stop()  # emits recording_stopped

    # ------------------------------------------------------------- recorder

    @pyqtSlot()
    def _on_recording_started(self) -> None:
        # State already RECORDING; this confirms the stream is live.
        self._set_state(RECORDING)
        self._sounds.play_start()

    @pyqtSlot(object, int)
    def _on_recording_stopped(self, audio, sample_rate) -> None:
        if audio is None or getattr(audio, "size", 0) == 0:
            # Too short / silent — back to idle silently.
            self._set_state(IDLE)
            return
        self._set_state(TRANSCRIBING)
        self._transcriber.transcribe(audio, sample_rate)

    @pyqtSlot(str)
    def _on_recorder_error(self, message: str) -> None:
        self._set_state("ERROR", message)
        self._sounds.play_error()
        self._set_state(IDLE)

    # ------------------------------------------------------------- transcriber

    @pyqtSlot(str)
    def _on_transcription_done(self, text: str) -> None:
        text = text.strip()
        if not text:
            self._set_state(IDLE)
            return
        log.info("Transcribed: %s", text)
        try:
            self._paster.paste(text, self._config.paste_method)
            self._set_state("DONE")
            self._sounds.play_done()
        except PasteError as exc:
            log.error("Paste failed: %s", exc)
            self._set_state("ERROR", "Paste failed — check clipboard")
            self._sounds.play_error()
        self._set_state(IDLE)

    @pyqtSlot(str)
    def _on_transcription_error(self, message: str) -> None:
        log.error("Transcription error: %s", message)
        self._set_state("ERROR", "Transcription failed")
        self._sounds.play_error()
        self._set_state(IDLE)

    # ------------------------------------------------------------- model

    @pyqtSlot()
    def _on_model_ready(self) -> None:
        log.info("Model ready.")
        self._set_state(IDLE, "")

    @pyqtSlot(str)
    def _on_model_error(self, message: str) -> None:
        log.error("Model load error: %s", message)
        self._set_state("ERROR", message)

    # ------------------------------------------------------------- pause

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        log.info("Hotkey %s", "paused" if paused else "resumed")

    @pyqtSlot()
    def cancel_transcription(self) -> None:
        """User pressed stop: discard the in-flight transcription, no paste.

        Always cancels (drops the pending result) even if the state just moved,
        so a click that lands right as transcription finishes still suppresses
        the paste.
        """
        self._transcriber.cancel()
        log.info("Transcription cancelled by user")
        if self._state == TRANSCRIBING:
            self._set_state(IDLE)

    # ------------------------------------------------------------- settings

    @pyqtSlot(set)
    def apply_settings(self, changed: set) -> None:
        """Apply changed settings live (no restart)."""
        if not changed:
            return
        if "hotkey" in changed:
            registered = self._hotkeys.register(self._config.hotkey)
            log.info("Hotkey re-registered as %r", registered)
        if "language" in changed:
            self._transcriber.set_language(self._config.language_or_none)
        if "sound_effects" in changed:
            self._sounds.enabled = (self._config.sound_effects
                                    and sys.platform == "win32")
        if "enhance_audio" in changed and "model" not in changed:
            self._transcriber._enhance_audio = self._config.enhance_audio
        if "model" in changed:
            self._reload_model_async()

    def _reload_model_async(self) -> None:
        """Swap in a freshly-loaded model. Guarded against running mid-record."""
        if self._state != IDLE:
            log.info("Deferring model reload until idle")
        self._set_state(IDLE, "Loading model...")
        # Replace the transcriber and reload on a worker thread.
        self._transcriber.transcription_done.disconnect(self._on_transcription_done)
        self._transcriber.transcription_error.disconnect(self._on_transcription_error)
        self._transcriber.model_error.disconnect(self._on_model_error)

        self._transcriber = Transcriber(self._config.model,
                                        self._config.language_or_none,
                                        self._config.beam_size,
                                        self._config.enhance_audio)
        self._transcriber.transcription_done.connect(self._on_transcription_done)
        self._transcriber.transcription_error.connect(self._on_transcription_error)
        self._transcriber.model_error.connect(self._on_model_error)
        self._load_model_async()

    # ------------------------------------------------------------- state

    def _set_state(self, state: str, message: str = "") -> None:
        self._state = state if state in (IDLE, RECORDING, TRANSCRIBING) \
            else self._state
        log.debug("State -> %s %s", state, message)
        self.state_changed.emit(state, message)

    @property
    def config(self) -> Config:
        return self._config

    @property
    def recorder(self) -> Recorder:
        return self._recorder

    @property
    def transcriber(self) -> Transcriber:
        return self._transcriber

    @property
    def hotkeys(self) -> HotkeyListener:
        return self._hotkeys


# ---------------------------------------------------------------------------
# Logging + entry point.
# ---------------------------------------------------------------------------

def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name, logging.WARNING)
    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=5_000_000, backupCount=1, encoding="utf-8")
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Mirror to console during source runs (not in --noconsole builds).
    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)


def main() -> int:
    # Run from the executable/script directory so config.json + logs land there.
    os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])) or ".")

    config = Config.load(CONFIG_PATH)
    _setup_logging(config.log_level)
    log.info("Starting %s", APP_NAME)

    # High-DPI crispness for the pill (Milestone 2). Must precede QApplication.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(APP_NAME)
    qt_app.setQuitOnLastWindowClosed(False)

    app = App(config)

    # --- UI surfaces -------------------------------------------------------
    from pill import FloatingPill
    from settings import SettingsWindow
    from tray import TrayIcon

    pill = FloatingPill(config)
    tray = TrayIcon()
    settings = SettingsWindow(config)

    # State fan-out: drive the pill (lowercase states) and tray (uppercase),
    # and surface loading/error messages in the tray tooltip.
    state_to_pill = {
        RECORDING: "recording",
        TRANSCRIBING: "transcribing",
        "DONE": "done",
        "ERROR": "error",
    }

    def on_state(state: str, message: str) -> None:
        pill_state = state_to_pill.get(state, "")
        if pill_state:
            pill.set_state(pill_state, message)
        tray.set_state(state)
        if message:
            tray.set_tooltip(message)

    app.state_changed.connect(on_state)
    app.amplitude_changed.connect(pill.set_amplitude)

    # Stop button on the pill cancels the in-flight transcription.
    pill.cancel_requested.connect(app.cancel_transcription)
    pill.cancel_requested.connect(pill.dismiss)

    tray.settings_requested.connect(settings.open_panel)
    tray.quit_requested.connect(qt_app.quit)
    tray.pause_toggled.connect(app.set_paused)
    settings.settings_saved.connect(app.apply_settings)

    tray.show()
    app.start()

    qt_app.aboutToQuit.connect(app.shutdown)
    return qt_app.exec()


if __name__ == "__main__":
    sys.exit(main())
