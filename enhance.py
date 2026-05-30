"""Voice enhancement DSP for HephFlow (numpy-only, no extra deps).

Run on the recorded clip just before transcription to improve clarity and
signal-to-noise — which is what actually lifts Whisper accuracy. It cannot turn
a cheap mic into a studio mic (physics), but it makes the captured speech much
cleaner:

    high-pass (kill rumble)  ->  spectral noise gate (suppress steady noise)
    ->  presence EQ (lift consonants)  ->  soft compression  ->  peak normalize

Everything is vectorized FFT/array math, so a 30 s clip processes in a few ms.
"""

from __future__ import annotations

import numpy as np

N_FFT = 512
HOP = 128


def enhance(audio: np.ndarray, sr: int = 16000) -> np.ndarray:
    """Return a cleaned, leveled copy of `audio` (float32, mono)."""
    if audio is None or audio.size < N_FFT:
        return audio
    x = audio.astype(np.float32).reshape(-1)

    x = _highpass(x, sr, cutoff=85.0)
    x = _spectral_enhance(x, sr)
    x = _compress(x)
    x = _normalize(x)
    return x.astype(np.float32)


# ---------------------------------------------------------------- high-pass

def _highpass(x: np.ndarray, sr: int, cutoff: float, numtaps: int = 101) -> np.ndarray:
    """Windowed-sinc FIR high-pass (removes hum/rumble below `cutoff`)."""
    if numtaps % 2 == 0:
        numtaps += 1
    fc = cutoff / sr
    n = np.arange(numtaps) - (numtaps - 1) / 2
    # Low-pass prototype, then spectral-invert to high-pass.
    lp = np.sinc(2 * fc * n) * np.hanning(numtaps)
    lp /= np.sum(lp)
    hp = -lp
    hp[(numtaps - 1) // 2] += 1.0
    return np.convolve(x, hp.astype(np.float32), mode="same").astype(np.float32)


# ------------------------------------------------- spectral gate + presence

def _frames(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    if len(x) < n_fft:
        return np.empty((0, n_fft), dtype=np.float32)
    num = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(num)[:, None]
    return x[idx]


def _spectral_enhance(x: np.ndarray, sr: int) -> np.ndarray:
    """Spectral-subtraction noise gate with a gentle presence boost.

    The steady noise floor is estimated per frequency bin as a low percentile
    of magnitude across time, then subtracted (Wiener-style soft mask). A mild
    boost around 2-5 kHz sharpens consonants.
    """
    win = np.hanning(N_FFT).astype(np.float32)
    frames = _frames(x, N_FFT, HOP)
    if frames.shape[0] == 0:
        return x

    spec = np.fft.rfft(frames * win, axis=1)
    mag = np.abs(spec)
    phase = np.angle(spec)

    # Per-bin noise floor = 15th percentile over time (assumes noise is the
    # quiet, stationary component present across the clip).
    noise = np.percentile(mag, 15, axis=0, keepdims=True)

    # Soft spectral-subtraction gain, oversubtracted a bit, floored so we
    # attenuate rather than null (avoids "musical noise").
    over = 1.5
    floor = 0.12
    gain = (mag - over * noise) / (mag + 1e-8)
    gain = np.clip(gain, floor, 1.0)
    # Smooth the gain over time to further reduce artifacts.
    gain = _smooth_time(gain, k=3)

    # Presence EQ: gentle lift in the speech-consonant band.
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / sr)
    presence = 1.0 + 0.35 * np.exp(-((freqs - 3500.0) ** 2) / (2 * 1500.0 ** 2))
    gain = gain * presence[None, :]

    clean = np.fft.irfft(mag * gain * np.exp(1j * phase), n=N_FFT, axis=1)
    return _overlap_add(clean.astype(np.float32), win, len(x))


def _smooth_time(g: np.ndarray, k: int) -> np.ndarray:
    if g.shape[0] < k or k < 2:
        return g
    kernel = np.ones(k, dtype=np.float32) / k
    return np.apply_along_axis(
        lambda m: np.convolve(m, kernel, mode="same"), 0, g)


def _overlap_add(frames: np.ndarray, win: np.ndarray, length: int) -> np.ndarray:
    out = np.zeros(length + N_FFT, dtype=np.float32)
    norm = np.zeros(length + N_FFT, dtype=np.float32)
    win_sq = win ** 2
    for i in range(frames.shape[0]):
        s = i * HOP
        out[s:s + N_FFT] += frames[i] * win
        norm[s:s + N_FFT] += win_sq
    norm[norm < 1e-6] = 1.0
    return (out / norm)[:length]


# ----------------------------------------------------- compression + level

def _compress(x: np.ndarray, threshold: float = 0.15, ratio: float = 3.0,
              sr: int = 16000) -> np.ndarray:
    """Soft-knee downward compression to even out loud/quiet speech."""
    env = _envelope(np.abs(x), sr)
    over = np.maximum(env - threshold, 0.0)
    # Target gain reduces the part above threshold by `ratio`.
    gain = (threshold + over / ratio) / (env + 1e-8)
    gain = np.minimum(gain, 1.0)
    return (x * gain).astype(np.float32)


def _envelope(absx: np.ndarray, sr: int, window_s: float = 0.03) -> np.ndarray:
    """Vectorized smoothed peak envelope (moving average of |x|)."""
    w = max(1, int(window_s * sr))
    kernel = np.ones(w, dtype=np.float32) / w
    return np.convolve(absx, kernel, mode="same").astype(np.float32)


def _normalize(x: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 1e-4:
        x = x * (target_peak / peak)
    return x.astype(np.float32)
