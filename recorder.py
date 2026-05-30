"""Microphone capture for HephFlow.

Recorder wraps a sounddevice InputStream. The PortAudio callback runs on a
real-time audio thread and must NOT touch Qt objects, so it only appends a
copy of each block to an in-memory list. A QTimer on the Qt thread samples the
most recent block to drive the waveform visualizer at ~30fps.

start()/stop() are decorated as pyqtSlot so they can be invoked across threads
via QMetaObject.invokeMethod(..., QueuedConnection) from the keyboard listener.
"""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)


class RecorderError(Exception):
    """Raised when the microphone cannot be opened."""


class Recorder(QObject):
    SAMPLE_RATE = 16000      # Whisper expects 16 kHz mono.
    CHANNELS = 1
    DTYPE = "float32"
    BLOCKSIZE = 512          # ~32 ms per callback at 16 kHz.
    MIN_DURATION_S = 0.3     # Clips shorter than this are discarded (tap guard).
    MAX_DURATION_S = 120.0   # Auto-stop ceiling.
    LEVEL_INTERVAL_MS = 33   # ~30 fps waveform updates.

    recording_started = pyqtSignal()
    # (audio, sample_rate) — audio is empty if the clip was too short / silent.
    recording_stopped = pyqtSignal(np.ndarray, int)
    audio_level_update = pyqtSignal(float)
    # Emitted when the mic cannot be opened; carries a human-readable message.
    recorder_error = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self._stream = None  # sd.InputStream, created lazily on start().

        # Level timer lives on the Qt thread this object is affined to.
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(self.LEVEL_INTERVAL_MS)
        self._level_timer.timeout.connect(self._emit_level)

        # Hard ceiling so a stuck key doesn't record forever.
        self._max_timer = QTimer(self)
        self._max_timer.setSingleShot(True)
        self._max_timer.setInterval(int(self.MAX_DURATION_S * 1000))
        self._max_timer.timeout.connect(self.stop)

    # ------------------------------------------------------------------ audio

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        # Real-time thread: no Qt, no logging beyond a flag. indata is a view
        # into PortAudio's buffer, so we MUST copy before keeping it.
        if status:
            # Overflows are non-fatal; they just mean a dropped block.
            log.debug("Audio stream status: %s", status)
        if self._recording:
            self._chunks.append(indata.copy())

    @pyqtSlot()
    def start(self) -> None:
        """Open the mic and begin accumulating audio. Safe to call on Qt thread."""
        if self._recording:
            return
        import sounddevice as sd

        self._chunks = []
        try:
            self._stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                blocksize=self.BLOCKSIZE,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as exc:  # sd.PortAudioError and friends.
            self._stream = None
            msg = self._friendly_error(exc)
            log.error("Failed to start recording: %s", exc)
            self.recorder_error.emit(msg)
            return

        self._recording = True
        self._level_timer.start()
        self._max_timer.start()
        self.recording_started.emit()

    @pyqtSlot()
    def stop(self) -> None:
        """Stop the mic and emit the captured audio (or empty if too short)."""
        if not self._recording:
            return
        self._recording = False
        self._level_timer.stop()
        self._max_timer.stop()

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                log.warning("Error closing audio stream: %s", exc)
            finally:
                self._stream = None

        if self._chunks:
            audio = np.concatenate(self._chunks).reshape(-1).astype("float32")
        else:
            audio = np.zeros(0, dtype="float32")
        self._chunks = []

        duration = len(audio) / self.SAMPLE_RATE
        if duration < self.MIN_DURATION_S:
            log.debug("Discarding short clip (%.3fs)", duration)
            # Emit empty so the orchestrator silently returns to IDLE.
            self.audio_level_update.emit(0.0)
            self.recording_stopped.emit(np.zeros(0, dtype="float32"),
                                        self.SAMPLE_RATE)
            return

        self.recording_stopped.emit(audio, self.SAMPLE_RATE)

    # ------------------------------------------------------------------ level

    def _emit_level(self) -> None:
        if not self._chunks:
            self.audio_level_update.emit(0.0)
            return
        block = self._chunks[-1]
        rms = float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0
        # Perceptual curve: sqrt makes quiet speech visible while loud speech
        # still saturates near 1.0 — gives the waveform real, lively reactivity.
        level = min(1.0, (rms ** 0.5) * 3.4)
        self.audio_level_update.emit(level)

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        text = str(exc).lower()
        if "invalid" in text and "device" in text:
            return "No mic detected"
        if "device unavailable" in text or "unanticipated host error" in text:
            return "Mic unavailable"
        return "No mic detected"
