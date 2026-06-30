"""Soft, non-blocking audio cues — a gentle sine with raised-cosine fades so
there's no harsh click/onset (unlike winsound.Beep's square wave)."""
from __future__ import annotations

import numpy as np
import sounddevice as sd

_SR = 44100


def play_tone(freq: float, ms: int, volume: float) -> None:
    n = int(_SR * ms / 1000)
    if n <= 0:
        return
    t = np.linspace(0, ms / 1000.0, n, endpoint=False)
    wave = np.sin(2 * np.pi * freq * t)
    # raised-cosine fade in/out (40% of the tone) to keep it soft
    fade = max(1, int(n * 0.4))
    ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fade)))
    env = np.ones(n)
    env[:fade] *= ramp
    env[-fade:] *= ramp[::-1]
    out = (wave * env * volume).astype(np.float32)
    try:
        sd.play(out, _SR)  # non-blocking; own output stream
    except Exception:
        pass
