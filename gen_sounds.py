"""Generate HephFlow's UI sound effects into assets/. Run once.

Deep, bassy, felt cues — designed to read as low/sub even on laptop speakers
that can't reproduce real sub-bass. Techniques:

  * DEEP fundamentals (~80-165 Hz) rendered with strong HARMONICS so the brain
    perceives the low pitch via the "missing fundamental" effect (how phones
    fake bass on tiny speakers)
  * a fast downward PITCH-DROP on the attack = the sub-kick "thump" you feel
  * soft attack + exponential decay (no clicks), warm low-pass, subtle reverb
  * consonant tuning; ascending low 5th for "done" = deep but resolving

  snd_start.wav  - deep sub "thump" when recording starts
  snd_done.wav   - warm rising low bass (A2->E3) when text is pasted
  snd_error.wav  - low descending sub when something fails
"""

from __future__ import annotations

import os
import wave

import numpy as np

ASSETS = "assets"
SR = 44100
RNG = np.random.default_rng(7)


def _lowpass(x: np.ndarray, cutoff: float, numtaps: int = 127) -> np.ndarray:
    fc = cutoff / SR
    n = np.arange(numtaps) - (numtaps - 1) / 2
    h = np.sinc(2 * fc * n) * np.hanning(numtaps)
    h /= np.sum(h)
    return np.convolve(x, h, mode="same")


def _deep_tone(freq: float, dur: float, *, harmonics=(1.0, 0.6, 0.32, 0.16),
               decay=0.20, attack=0.005, punch=1.6, punch_t=0.035) -> np.ndarray:
    """A deep tone built from harmonics of a low fundamental.

    The harmonics let small speakers convey the low pitch (missing fundamental).
    `punch` sweeps the pitch down at the start for a sub-kick thump.
    """
    n = int(dur * SR)
    t = np.arange(n) / SR
    # Pitch envelope: starts higher, drops to the fundamental fast (the thump).
    pitch = freq * (1.0 + (punch - 1.0) * np.exp(-t / punch_t))
    base_phase = 2 * np.pi * np.cumsum(pitch) / SR

    sig = np.zeros(n)
    for k, amp in enumerate(harmonics, start=1):
        # Higher harmonics decay faster (natural), keeping low weight in the tail.
        sig += amp * np.sin(base_phase * k) * np.exp(-t / (decay / (0.6 + 0.4 * k)))
    sig /= sum(harmonics)

    a = max(1, int(attack * SR))
    env = np.ones(n)
    env[:a] = np.sin(np.linspace(0, np.pi / 2, a))
    sig *= env
    # A faint sub layer at the true fundamental for headphones/real speakers.
    sub = 0.5 * np.sin(2 * np.pi * freq * t) * np.exp(-t / decay) * env
    return sig + sub


def _click(dur=0.006, cutoff=2200, gain=0.10) -> np.ndarray:
    """Tiny low-passed transient so the attack has body on small speakers."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    return _lowpass(RNG.standard_normal(n) * np.exp(-t / (dur * 0.4)),
                    cutoff) * gain


def _reverb(x: np.ndarray, decay=0.11, mix=0.13, cutoff=3500) -> np.ndarray:
    n = int(decay * SR * 3)
    t = np.arange(n) / SR
    ir = _lowpass(RNG.standard_normal(n) * np.exp(-t / decay), cutoff)
    ir /= np.max(np.abs(ir)) + 1e-9
    wet = np.convolve(x, ir)[: len(x)]
    wet /= np.max(np.abs(wet)) + 1e-9
    peak = np.max(np.abs(x)) + 1e-9
    return x * (1 - mix) + wet * mix * peak


def _note(freq, dur, **kw) -> np.ndarray:
    tone = _deep_tone(freq, dur, **kw)
    cl = _click()
    tone[: len(cl)] += cl
    return tone


def _compose(notes, *, cutoff=3200) -> np.ndarray:
    total = max(int(off * SR) + len(s) for off, s in notes) + 1
    out = np.zeros(total)
    for off, s in notes:
        i = int(off * SR)
        out[i:i + len(s)] += s
    out = _reverb(out)
    out = _lowpass(out, cutoff)                          # warm/dark
    out = out / (np.max(np.abs(out)) + 1e-9) * 0.38      # bass needs a little level
    f = min(len(out), int(0.012 * SR))
    out[-f:] *= np.linspace(1.0, 0.0, f)
    return out


def _save(name: str, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(os.path.join(ASSETS, name), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# Low note frequencies (Hz).
E2, G2, A2, C3, D3, E3 = 82.41, 98.00, 110.0, 130.81, 146.83, 164.81
A1, D2 = 55.0, 73.42


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)

    # Start: one deep sub thump — short, felt.
    _save("snd_start.wav", _compose([
        (0.0, _note(A2, 0.26, decay=0.16, punch=1.8)),
    ]))

    # Done: rising low perfect fifth (A2 -> E3) — deep but resolving.
    _save("snd_done.wav", _compose([
        (0.0, _note(A2, 0.34, decay=0.22, punch=1.5)),
        (0.10, _note(E3, 0.46, decay=0.30, punch=1.4)),
    ]))

    # Error: low descending sub (G2 -> D2) — soft, not harsh.
    _save("snd_error.wav", _compose([
        (0.0, _note(G2, 0.30, decay=0.20, punch=1.5)),
        (0.10, _note(D2, 0.40, decay=0.26, punch=1.4)),
    ]))

    print(f"Sounds written to {os.path.abspath(ASSETS)}")


if __name__ == "__main__":
    main()
