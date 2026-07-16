#!/usr/bin/env python3
"""Generate 'Nightwaves' — the built-in demo ambience for The Kingdom of Nye.

Fully original synthesis (no samples), so it's ours to release CC0. Evokes a 3 a.m.
shortwave dial: colored-noise static that fades like tuning, detuned carriers beating
against each other, sparse numbers-station blips, and a low rumble. Deterministic
(seed 1140 — the K.O.N call sign) so the asset is reproducible.

    python3 make_nightwaves.py   # -> nye-nightwaves.wav  (then encode to mp3 with ffmpeg)
"""

import wave
from pathlib import Path

import numpy as np

SR = 44100
DUR = 78.0
HERE = Path(__file__).resolve().parent
rng = np.random.default_rng(1140)


def norm(x):
    m = np.max(np.abs(x))
    return x / m if m > 0 else x


def colored_noise(n, beta):
    """1/f**beta noise via spectral shaping (beta≈1 pink, 2 brown)."""
    wn = rng.standard_normal(n)
    spec = np.fft.rfft(wn)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1]
    spec = spec / (freqs ** (beta / 2.0))
    return norm(np.fft.irfft(spec, n=n))


def carrier(t, f, drift_hz, t0, dur, amp):
    """A slow sine that fades in/out and wanders in pitch — a shortwave whistle."""
    env = np.clip(np.sin(np.pi * np.clip((t - t0) / dur, 0, 1)), 0, 1)
    wander = drift_hz * np.cumsum(np.sin(2 * np.pi * 0.02 * t)) / SR
    return amp * env * np.sin(2 * np.pi * (f * t + wander))


def build():
    n = int(SR * DUR)
    t = np.arange(n) / SR

    # static bed: pink-ish noise, amplitude-modulated like a hand turning the dial
    am = 0.5 + 0.5 * np.sin(2 * np.pi * 0.03 * t + 1.5 * np.sin(2 * np.pi * 0.011 * t))
    static = colored_noise(n, 1.6) * (0.10 + 0.13 * am)

    # detuned carriers — the 437/442 pair beats at ~5 Hz for that eerie heterodyne
    car = np.zeros(n)
    car += carrier(t, 437, 20, 6, 22, 0.060)
    car += carrier(t, 442, 18, 6, 22, 0.050)
    car += carrier(t, 880, 30, 34, 18, 0.035)
    car += carrier(t, 311, 12, 50, 24, 0.045)

    # numbers-station blips: sparse single tones in loose triplets
    blips = np.zeros(n)
    beep = int(SR * 0.28)
    env_b = np.hanning(beep)
    for bt in (14.0, 14.5, 15.0, 41.0, 41.6, 42.2, 42.8, 63.0, 63.5):
        i = int(bt * SR)
        if i + beep < n:
            blips[i:i + beep] += 0.055 * env_b * np.sin(2 * np.pi * 620 * np.arange(beep) / SR)

    sub = 0.03 * np.sin(2 * np.pi * 47 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t))

    mix = norm(static + car + blips + sub) * 0.9
    fade = int(SR * 2.5)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)

    # stereo width: a few-sample offset + a touch of independent per-side static
    left = norm(mix + 0.03 * colored_noise(n, 1.6) * am) * 0.85
    right = norm(np.roll(mix, 7) + 0.03 * colored_noise(n, 1.6) * am) * 0.85
    pcm = (np.clip(np.stack([left, right], axis=1), -1, 1) * 32767).astype("<i2")

    out = HERE / "nye-nightwaves.wav"
    with wave.open(str(out), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {out} ({DUR:.0f}s)")


if __name__ == "__main__":
    build()
