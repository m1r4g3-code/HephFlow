"""Headless smoke test: import every module and build the Qt objects.

Exercises wiring that does not need a mic or the Whisper model:
  - all modules import
  - QApplication + Recorder/Transcriber/Paster/Pill/Tray/Settings construct
  - the App state fan-out reaches the pill and tray without error

Run:  python tests/smoke_test.py
Exits non-zero on any failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use the offscreen platform so no real window is shown.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    import config
    import recorder
    import transcriber
    import paster
    import pill
    import tray
    import settings

    cfg = config.Config.load(os.path.join(os.path.dirname(__file__),
                                          "_smoke_config.json"))

    rec = recorder.Recorder()
    txr = transcriber.Transcriber(cfg.model, cfg.language_or_none)
    pst = paster.Paster(cfg)
    flo = pill.FloatingPill(cfg)
    try_ = tray.TrayIcon()
    setw = settings.SettingsWindow(cfg)

    # Drive the pill through every state — must not raise.
    for state in ("recording", "transcribing", "done", "error"):
        flo.set_state(state, "test message")
    flo.set_amplitude(0.5)

    # Tray state changes.
    for state in ("RECORDING", "TRANSCRIBING", "ERROR", "IDLE"):
        try_.set_state(state)

    # Settings load from config.
    setw.load_from_config()

    # Clean up the temp config file.
    try:
        os.remove(os.path.join(os.path.dirname(__file__), "_smoke_config.json"))
    except OSError:
        pass

    print("SMOKE OK: imports + Qt construction + state fan-out succeeded")
    # Don't enter the event loop; we only validated construction.
    _ = (rec, txr, pst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
