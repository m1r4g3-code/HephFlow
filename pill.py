"""Floating pill overlay for HephFlow — sleek, Apple-style, glassmorphic.

A frameless, always-on-top, non-focus-stealing capsule. On Windows it uses the
DWM acrylic blur-behind for a real frosted-glass look (with a painted
translucent fallback). It shows recording / transcribing / done / error with a
smooth scrolling waveform, an iOS-style spinner, and an animated checkmark.

It must never take focus from whatever the user is typing into — hence the
Win32 WS_EX_NOACTIVATE style applied in showEvent.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time

from PyQt6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation,
                          QRect, Qt, QTimer, pyqtSignal, pyqtSlot)
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

log = logging.getLogger(__name__)

# States.
S_RECORDING = "recording"
S_TRANSCRIBING = "transcribing"
S_DONE = "done"
S_ERROR = "error"

PILL_W = 158            # Compact, WhisperFlow-sized.
PILL_H = 36
CORNER_RADIUS = 18      # Full pill.
BOTTOM_MARGIN = 48
NUM_BARS = 30           # Dense, fine waveform bars.
STOP_BTN_R = 9
STOP_HIT_PAD = 6        # Extra forgiving padding around the stop button.

# Snappy, modern timings — quick confirm then gone.
DONE_HOLD_MS = 170
DONE_FADE_MS = 160
ERROR_HOLD_MS = 1400
ERROR_FADE_MS = 220

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


class FloatingPill(QWidget):
    cancel_requested = pyqtSignal()

    def __init__(self, config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._state = S_RECORDING
        self._message = ""
        self._amplitude = 0.0
        self._level = 0.0                       # smoothed amplitude
        self._wave_phase = 0.0                  # traveling-wave phase (flow)
        self._phase = 0.0                       # spinner/pulse phase
        self._done_progress = 0.0               # checkmark draw-in 0..1
        self._record_start = 0.0
        self._drag_offset: QPoint | None = None
        self._fade: QPropertyAnimation | None = None
        self._acrylic = False

        self.setFixedSize(PILL_W, PILL_H)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._anim = QTimer(self)
        self._anim.setInterval(33)              # ~30 fps — smooth, modern
        self._anim.timeout.connect(self._tick)

    # ------------------------------------------------------------- placement

    def place_default(self) -> None:
        if self._config.has_pill_position:
            x, y = self._config.pill_position
            self.move(int(x), int(y))
            return
        from PyQt6.QtWidgets import QApplication
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - PILL_W) // 2
            y = geo.y() + geo.height() - PILL_H - BOTTOM_MARGIN
            self.move(x, y)

    # ------------------------------------------------------------- public API

    @pyqtSlot(str, str)
    def set_state(self, state: str, message: str = "") -> None:
        if state == S_RECORDING:
            self._enter_recording()
        elif state == S_TRANSCRIBING:
            self._enter_transcribing()
        elif state == S_DONE:
            self._enter_done()
        elif state == S_ERROR:
            self._enter_error(message)
        # else (IDLE/unknown): ignore so a DONE/ERROR fade isn't interrupted.

    @pyqtSlot(float)
    def set_amplitude(self, value: float) -> None:
        self._amplitude = max(0.0, min(1.0, value))

    @pyqtSlot()
    def dismiss(self) -> None:
        self._cancel_fade()
        self._anim.stop()
        self.hide()

    # ------------------------------------------------------------- states

    def _cancel_fade(self) -> None:
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        self.setWindowOpacity(1.0)

    def _enter_recording(self) -> None:
        self._cancel_fade()
        self._state = S_RECORDING
        self._level = 0.0
        self._wave_phase = 0.0
        self._record_start = time.monotonic()
        self.place_default()
        if not self.isVisible():
            self.show()
        self._anim.start()
        self.update()

    def _enter_transcribing(self) -> None:
        self._cancel_fade()
        self._state = S_TRANSCRIBING
        self._phase = 0.0
        if not self.isVisible():
            self.show()
        self._anim.start()
        self.update()

    def _enter_done(self) -> None:
        self._cancel_fade()
        self._state = S_DONE
        self._done_progress = 0.0
        if not self.isVisible():
            self.place_default()
            self.show()
        self._anim.start()                      # animate the checkmark draw-in
        self.update()
        QTimer.singleShot(DONE_HOLD_MS, lambda: self._start_fade(DONE_FADE_MS))

    def _enter_error(self, message: str) -> None:
        self._cancel_fade()
        self._state = S_ERROR
        self._message = message or "Error"
        self._anim.stop()
        if not self.isVisible():
            self.place_default()
            self.show()
        self.update()
        QTimer.singleShot(ERROR_HOLD_MS, lambda: self._start_fade(ERROR_FADE_MS))

    def _start_fade(self, duration_ms: int) -> None:
        if not self.isVisible():
            return
        self._anim.stop()
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(duration_ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.finished.connect(self._on_fade_done)
        self._fade.start()

    def _on_fade_done(self) -> None:
        self.hide()
        self.setWindowOpacity(1.0)
        self._fade = None

    # ------------------------------------------------------------- animation

    def _tick(self) -> None:
        self._phase += 0.13
        if self._state == S_RECORDING:
            # Smooth the live level; advance the traveling-wave phase so the
            # bars continuously flow (and grow louder with your voice).
            self._level += (self._amplitude - self._level) * 0.62
            self._wave_phase += 0.5
        elif self._state == S_DONE:
            self._done_progress = min(1.0, self._done_progress + 0.22)
        self.update()

    # ------------------------------------------------------------- painting

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Matte black, flat and opaque — no sheen, no blur. Editorial.
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, w - 1.0, h - 1.0,
                            CORNER_RADIUS, CORNER_RADIUS)
        p.fillPath(path, QColor(14, 14, 15))

        # Hairline edge so the pill reads cleanly on light backgrounds.
        pen = QPen(QColor(255, 255, 255, 26))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)

        if self._state == S_RECORDING:
            self._paint_recording(p)
        elif self._state == S_TRANSCRIBING:
            self._paint_transcribing(p)
        elif self._state == S_DONE:
            self._paint_done(p)
        elif self._state == S_ERROR:
            self._paint_error(p)
        p.end()

    def _paint_recording(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        cy = h / 2

        # Pulsing red record dot.
        import math
        pulse = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(self._phase * 2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0xFF, 0x45, 0x3A, int(255 * pulse)))
        p.drawEllipse(QPointF(14, cy), 3.5, 3.5)

        # Duration counter — small, letter-spaced, editorial.
        elapsed = int(time.monotonic() - self._record_start)
        label = f"{elapsed // 60}:{elapsed % 60:02d}"
        p.setPen(QColor(210, 210, 214, 200))
        tf = QFont("Segoe UI", 8)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        p.setFont(tf)
        timer_rect = QRect(w - 38, 0, 28, h)
        p.drawText(timer_rect, int(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter), label)

        # Flowing, audio-reactive waveform (WhisperFlow/Siri-style): a traveling
        # wave whose height grows with your voice, tapered at the edges so it
        # reads as one organic wave. Always a gentle idle ripple; speaking
        # swells it dramatically.
        import math
        x0, x1 = 24.0, float(w - 42)
        max_h = h * 0.60
        n = NUM_BARS
        step = (x1 - x0) / n
        bar_w = max(2, int(step * 0.58))
        rad = bar_w / 2
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            # Two superposed traveling waves give a livelier, less regular flow.
            travel = (0.5 + 0.5 * math.sin(self._wave_phase - i * 0.45)) \
                * (0.6 + 0.4 * math.sin(self._wave_phase * 0.7 + i * 0.2))
            taper = math.sin(math.pi * (i + 0.5) / n) ** 0.6   # soft edge taper
            amp = (0.14 + 0.86 * self._level) * taper * (0.45 + 0.55 * travel)
            bh = max(2.5, amp * max_h)
            x = x0 + i * step
            alpha = int(165 + 80 * travel)
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawRoundedRect(QRect(int(x), int(cy - bh / 2),
                                    bar_w, int(bh)), int(rad), int(rad))

    def _paint_transcribing(self, p: QPainter) -> None:
        h = self.height()
        cy = h / 2
        cx = 17.0
        r = 6.5
        arc_rect = QRect(int(cx - r), int(cy - r), int(2 * r), int(2 * r))

        # Faint full-circle track.
        track = QPen(QColor(255, 255, 255, 40))
        track.setWidthF(2.0)
        p.setPen(track)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Bright rotating arc (the spinner head) with rounded caps.
        arc = QPen(QColor(245, 245, 248, 235))
        arc.setWidthF(2.2)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arc)
        start = int(-self._phase * 130 * 16) % (360 * 16)
        p.drawArc(arc_rect, start, 100 * 16)

        # Label — light weight, letter-spaced, editorial.
        p.setPen(QColor(220, 220, 224, 225))
        lf = QFont("Segoe UI", 8)
        lf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        p.setFont(lf)
        rect = QRect(30, 0, self.width() - 30 - (STOP_BTN_R * 2 + 14), h)
        p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter), "Transcribing")

        self._paint_stop_button(p)

    def _paint_done(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        # Soft green halo.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0x32, 0xD7, 0x4B, 36))
        p.drawEllipse(QPointF(cx, cy), 15, 15)

        # Animated checkmark: two segments drawn in by progress.
        a = QPointF(cx - 9, cy + 1)
        b = QPointF(cx - 2, cy + 7)
        c = QPointF(cx + 10, cy - 7)
        pen = QPen(QColor(0x3D, 0xDC, 0x57))
        pen.setWidthF(3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        prog = self._done_progress
        if prog <= 0.5:
            t = prog / 0.5
            p.drawLine(a, QPointF(a.x() + (b.x() - a.x()) * t,
                                  a.y() + (b.y() - a.y()) * t))
        else:
            t = (prog - 0.5) / 0.5
            p.drawLine(a, b)
            p.drawLine(b, QPointF(b.x() + (c.x() - b.x()) * t,
                                  b.y() + (c.y() - b.y()) * t))

    def _paint_error(self, p: QPainter) -> None:
        h = self.height()
        cy = h / 2
        x = 17
        pen = QPen(QColor(0xFF, 0x45, 0x3A))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(x - 5, cy - 5), QPointF(x + 5, cy + 5))
        p.drawLine(QPointF(x - 5, cy + 5), QPointF(x + 5, cy - 5))
        p.setPen(QColor(220, 220, 224, 230))
        ef = QFont("Segoe UI", 8)
        ef.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        p.setFont(ef)
        rect = QRect(30, 0, self.width() - 38, h)
        p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter),
                   _elide(self._message, 18))

    # ------------------------------------------------------------- stop button

    def _stop_button_center(self) -> QPointF:
        return QPointF(self.width() - STOP_BTN_R - 12, self.height() / 2)

    def _stop_button_rect(self) -> QRect:
        c = self._stop_button_center()
        r = STOP_BTN_R + STOP_HIT_PAD       # forgiving hit area
        return QRect(int(c.x() - r), int(c.y() - r), r * 2, r * 2)

    def _paint_stop_button(self, p: QPainter) -> None:
        c = self._stop_button_center()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawEllipse(c, float(STOP_BTN_R), float(STOP_BTN_R))
        s = 7.0
        p.setBrush(QColor(0xFF, 0x45, 0x3A))
        p.drawRoundedRect(QRect(int(c.x() - s / 2), int(c.y() - s / 2),
                                int(s), int(s)), 2, 2)

    # ------------------------------------------------------------- focus guard

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if sys.platform == "win32":
            self._apply_noactivate()
        # OS blur (acrylic/blur-behind) is intentionally OFF: it forces a GPU
        # recomposite on every repaint and lags weak integrated GPUs badly.
        # We render a clean near-solid dark glass that repaints cheaply instead.
        self._acrylic = False

    def _apply_noactivate(self) -> None:
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE,
                                  ex | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW)
        except Exception as exc:  # noqa: BLE001
            log.debug("Could not apply WS_EX_NOACTIVATE: %s", exc)

    def _enable_acrylic(self) -> bool:
        """Enable DWM acrylic blur-behind with rounded corners. Returns success."""
        try:
            hwnd = int(self.winId())

            class ACCENT_POLICY(ctypes.Structure):
                _fields_ = [("AccentState", ctypes.c_int),
                            ("AccentFlags", ctypes.c_int),
                            ("GradientColor", ctypes.c_uint),
                            ("AnimationId", ctypes.c_int)]

            class WCA_DATA(ctypes.Structure):
                _fields_ = [("Attribute", ctypes.c_int),
                            ("Data", ctypes.c_void_p),
                            ("SizeOfData", ctypes.c_size_t)]

            # Smooth Gaussian blur (Aero glass), not the noisy acrylic frost.
            ACCENT_ENABLE_BLURBEHIND = 3
            WCA_ACCENT_POLICY = 19
            accent = ACCENT_POLICY()
            accent.AccentState = ACCENT_ENABLE_BLURBEHIND
            accent.AccentFlags = 0
            accent.GradientColor = 0x5C26262E       # AABBGGRR light cool tint
            data = WCA_DATA()
            data.Attribute = WCA_ACCENT_POLICY
            data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
            data.SizeOfData = ctypes.sizeof(accent)
            fn = ctypes.windll.user32.SetWindowCompositionAttribute
            ok = fn(hwnd, ctypes.byref(data))
            if not ok:
                return False
            # Round the (rectangular) acrylic region to match the pill.
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                0, 0, self.width() + 1, self.height() + 1,
                CORNER_RADIUS * 2, CORNER_RADIUS * 2)
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
            return True
        except Exception as exc:  # noqa: BLE001
            log.debug("Acrylic blur unavailable: %s", exc)
            return False

    # ------------------------------------------------------------- dragging

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._state == S_TRANSCRIBING \
                    and self._stop_button_rect().contains(event.position().toPoint()):
                self.cancel_requested.emit()
                event.accept()
                return
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None \
                and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            pos = self.pos()
            self._config.pill_position = [pos.x(), pos.y()]
            self._config.save()
            self._drag_offset = None
            event.accept()


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
