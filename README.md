<div align="center">

# HephFlow

**Local-first, push-to-talk speech-to-text for Windows.**

Hold a hotkey, speak, release — your words are transcribed on-device and pasted
at the cursor in any application. No cloud. No account. No subscription.

</div>

---

## Overview

HephFlow is the open, offline answer to tools like WhisperFlow and Superwhisper:
a floating pill UI, push-to-talk recording, local Whisper transcription, and
instant paste — running entirely on your machine. Your audio never leaves the
device.

- 🎙️ **Push-to-talk** — hold a global hotkey, speak, release.
- ⚡ **Fast & accurate** — `distil-medium.en` by default (near-`medium`
  accuracy at a fraction of the cost), with greedy/beam decoding and full
  multi-core CPU inference.
- 🔒 **100% offline** — after the one-time model download, no network is used.
- 🧠 **Voice enhancement** — a built-in DSP stage (high-pass, spectral noise
  gate, presence EQ, compression) cleans your mic signal to boost accuracy.
- 🪟 **Floating pill** — a compact, matte, non-focus-stealing overlay with a
  live, voice-reactive waveform.
- 🔊 **Tactile sound cues** — subtle, synthesized start/done/error tones.
- 🛟 **Never lose a transcript** — the text stays on your clipboard after
  pasting, so a mis-aimed paste is always recoverable with `Ctrl+V`.
- ⚙️ **Live settings** — change hotkey, model, language, and more with no
  restart.

---

## How it works

```
[hotkey down] ──► RECORDING ──[hotkey up]──► TRANSCRIBING ──► paste ──► IDLE
                     │                              │
                 mic capture                 faster-whisper
                 (16 kHz mono)              (+ voice enhancement)
```

1. Hold the hotkey (default: **Right Alt**) and speak.
2. Release. The pill shows a live waveform, then a spinner while it transcribes.
3. The text is pasted at your cursor and the pill snaps away.

Press **Ctrl+Z** right after a paste to undo it as a single action, or **Ctrl+V**
to paste again — the transcript is kept on the clipboard.

---

## Requirements

| | |
|---|---|
| **OS** | Windows 10 (22H2+) or Windows 11 |
| **Python** | 3.10 – 3.13 (to run from source) |
| **RAM** | 4 GB+ (the model uses ~300 MB–1 GB depending on size) |
| **GPU** | Not required — CPU inference. (Optional NVIDIA CUDA path.) |
| **Other** | A microphone; Microsoft Visual C++ Redistributable 2019+ |

---

## Install & run (from source)

```powershell
git clone https://github.com/m1r4g3-code/HephFlow.git
cd HephFlow
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python generate_icons.py   # one-time: builds tray icons
python gen_sounds.py       # one-time: builds sound effects
python main.py
```

### First-run model download

The default model (`distil-medium.en`, ~750 MB) is **not** bundled. On first use
faster-whisper downloads it to the HuggingFace cache
(`%USERPROFILE%\.cache\huggingface\hub`). This is a one-time download; afterwards
HephFlow is fully offline. You can pick a smaller model (`tiny`/`base`/`small`)
in Settings if you prefer a lighter footprint.

---

## Standalone executable

A single-file build is produced with PyInstaller:

```powershell
pip install pyinstaller
pyinstaller pressflow.spec
```

Output: `dist/HephFlow.exe`. The model still downloads (or is reused from cache)
on first run. See [`pressflow.spec`](pressflow.spec) for the bundling details.

---

## Usage

- **Tray icon** — grey mic (idle), red mic (recording), yellow triangle (error).
- **Right-click the tray** → Settings · Pause/Resume · About · Quit.
- **Double-click the tray** → open Settings.
- **Drag the pill** anywhere; its position is remembered.
- **Stop button** — click the square on the pill to cancel a transcription.

---

## Settings

All changes apply immediately — no restart.

| Setting | Notes |
|---|---|
| **Hotkey** | Click the field, then press a key (default: Right Alt) |
| **Model** | `tiny` / `base` / `small` / `medium` / `distil-*` |
| **Language** | ISO code (`en`, `fr`, …); blank = auto-detect |
| **Paste method** | `clipboard` (default) or `typewrite` |
| **Trailing space** | Append a space after the transcript |
| **Audio enhance** | Noise reduction + clarity DSP before transcription |
| **Sound effects** | Subtle start/done/error cues |
| **Startup** | Launch HephFlow when Windows starts |

Config lives in `config.json` next to the app — human-readable and
hand-editable. Corrupt or missing config is regenerated with defaults.

---

## Architecture

| Module | Responsibility |
|---|---|
| `main.py` | Orchestrator + state machine, hotkey listener, signal wiring |
| `recorder.py` | Mic capture (sounddevice), 30 fps level metering |
| `transcriber.py` | faster-whisper inference on a worker pool |
| `enhance.py` | Voice-enhancement DSP (numpy: HPF, noise gate, EQ, compressor) |
| `paster.py` | Clipboard inject + Ctrl+V, with typewrite fallback |
| `pill.py` | Floating overlay (matte pill, reactive waveform, spinner) |
| `tray.py` | System tray icon + menu |
| `settings.py` | Settings window |
| `sounds.py` / `gen_sounds.py` | Sound playback / synthesis |
| `config.py` | Config dataclass + atomic JSON persistence |

Threading: a global keyboard listener (its own thread) marshals onto the Qt
event loop; recording runs on PortAudio's callback thread; transcription runs on
`QThreadPool`. All cross-thread communication uses Qt signals/slots.

---

## Troubleshooting

- **Hotkey does nothing** — some antivirus tools flag the `keyboard` library as a
  key logger. Add an exclusion for HephFlow.
- **Paste fails in an elevated app** (Task Manager, an admin terminal) — Windows
  blocks input across that security boundary unless HephFlow is also run as
  administrator.
- **First transcription is slow** — the model loads into RAM at startup (a few
  seconds); subsequent transcriptions are fast.
- **Logs** — see `pressflow.log` next to the app (set `log_level` to `DEBUG` in
  `config.json` for verbose output).

---

## Roadmap

- DeepFilterNet neural noise suppression (optional)
- Spoken formatting commands ("new line", "comma")
- Transcript history in the tray
- Microphone picker in Settings
- GPU (CUDA) inference path

---

## License

Released under the MIT License. See [`LICENSE`](LICENSE).

---

<div align="center">
Built with faster-whisper · PyQt6 · sounddevice — offline, and owned by you.
</div>
