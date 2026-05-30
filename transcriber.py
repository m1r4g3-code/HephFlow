"""faster-whisper transcription for HephFlow.

The WhisperModel is loaded once at startup (load_model, blocking — call it from
a worker QThread). Each transcription runs on the global QThreadPool so the Qt
event loop stays responsive. Results come back as thread-safe Qt signals.
"""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

log = logging.getLogger(__name__)


class _TranscribeTask(QRunnable):
    """Runs one transcription on a pool thread and reports via callbacks."""

    def __init__(self, model, audio, language, beam_size,
                 on_done, on_error) -> None:
        super().__init__()
        self._model = model
        self._audio = audio
        self._language = language
        self._beam_size = beam_size
        self._on_done = on_done
        self._on_error = on_error

    def run(self) -> None:
        try:
            segments, _info = self._model.transcribe(
                self._audio,
                language=self._language,
                # Beam search explores several hypotheses per word -> more
                # accurate than greedy. Worth the extra compute for dictation.
                beam_size=self._beam_size,
                # Don't feed prior text back in — each clip is independent, and
                # this avoids runaway repetition on short clips.
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                word_timestamps=False,
            )
            # segments is a lazy generator; consuming it runs the inference.
            text = " ".join(seg.text.strip() for seg in segments).strip()
            self._on_done(text)
        except Exception as exc:  # noqa: BLE001 - report everything to the UI.
            log.exception("Transcription failed")
            self._on_error(str(exc))


class Transcriber(QObject):
    transcription_done = pyqtSignal(str)
    transcription_error = pyqtSignal(str)
    model_ready = pyqtSignal()
    model_error = pyqtSignal(str)

    def __init__(self, model_size: str, language: str | None,
                 beam_size: int = 5, enhance_audio: bool = True,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model_size = model_size
        self._language = language or None
        self._beam_size = max(1, int(beam_size))
        self._enhance_audio = bool(enhance_audio)
        self._model = None
        # Bumped on cancel; an in-flight task whose generation no longer
        # matches is silently dropped (its result is never pasted).
        self._generation = 0

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def model_size(self) -> str:
        return self._model_size

    @property
    def language(self) -> str | None:
        return self._language

    def set_language(self, language: str | None) -> None:
        self._language = language or None

    def load_model(self) -> None:
        """Load the model into RAM. Blocking — call from a worker thread.

        On first ever run faster-whisper downloads the model to the Hugging
        Face cache; with no network this raises. We surface that via
        model_error rather than crashing.
        """
        import os

        from faster_whisper import WhisperModel

        cpu_threads = os.cpu_count() or 4
        try:
            # Prefer GPU when present (fast); fall back to CPU int8, which is
            # the fastest CPU path and uses all available cores.
            try:
                self._model = WhisperModel(
                    self._model_size, device="cuda", compute_type="float16")
                log.info("Whisper model %r loaded on GPU", self._model_size)
            except Exception:
                self._model = WhisperModel(
                    self._model_size, device="cpu", compute_type="int8",
                    cpu_threads=cpu_threads)
                log.info("Whisper model %r loaded on CPU (int8, %d threads)",
                         self._model_size, cpu_threads)
        except Exception as exc:  # noqa: BLE001
            self._model = None
            log.exception("Failed to load Whisper model %r", self._model_size)
            self.model_error.emit(self._friendly_load_error(exc))
            return
        self.model_ready.emit()

    def cancel(self) -> None:
        """Cancel the in-flight transcription: its result will be discarded.

        faster-whisper inference can't be interrupted mid-call, so the compute
        finishes in the background, but its text is never emitted/pasted.
        """
        self._generation += 1

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> None:
        """Queue an async transcription. Results arrive via signals."""
        if self._model is None:
            self.transcription_error.emit("Model not loaded")
            return
        if audio is None or audio.size == 0:
            # Nothing to do (short/silent clip already filtered upstream).
            self.transcription_done.emit("")
            return

        if self._enhance_audio:
            try:
                import enhance
                audio = enhance.enhance(audio, sample_rate)
            except Exception as exc:  # noqa: BLE001 - never block on DSP.
                log.warning("Audio enhancement failed (%s); using raw", exc)
                audio = self._normalize(audio)
        else:
            audio = self._normalize(audio)
        gen = self._generation
        task = _TranscribeTask(
            self._model,
            audio,
            self._language,
            self._beam_size,
            lambda t: self._emit_done(gen, t),
            lambda e: self._emit_error(gen, e),
        )
        QThreadPool.globalInstance().start(task)

    @staticmethod
    def _normalize(audio: np.ndarray) -> np.ndarray:
        """Peak-normalize quiet recordings so Whisper hears them clearly.

        A quiet mic produces low-amplitude audio that Whisper mis-transcribes.
        Scaling the peak up to ~0.95 (only when there's real signal) noticeably
        improves accuracy without distorting loud recordings.
        """
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 1e-4:
            audio = (audio * (0.95 / peak)).astype("float32")
        return audio

    def _emit_done(self, gen: int, text: str) -> None:
        if gen != self._generation:
            log.debug("Dropping cancelled transcription result")
            return
        self.transcription_done.emit(text)

    def _emit_error(self, gen: int, message: str) -> None:
        if gen != self._generation:
            return
        self.transcription_error.emit(message)

    @staticmethod
    def _friendly_load_error(exc: Exception) -> str:
        text = str(exc).lower()
        if any(k in text for k in ("connection", "network", "resolve",
                                   "timed out", "offline", "http")):
            return "Model not cached — internet needed for first run"
        return "Failed to load model"
