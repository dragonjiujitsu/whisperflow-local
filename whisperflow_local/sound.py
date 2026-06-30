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


def play_error(freq: float, volume: float) -> None:
    """Distinct failure cue: two short low buzzes. Signals 'nothing was pasted'
    (empty STT, paste aborted, timeout) so the user is never left guessing."""
    n = int(_SR * 0.30)
    if n <= 0:
        return
    t = np.linspace(0, 0.30, n, endpoint=False)
    tone = np.sin(2 * np.pi * freq * t)
    gap_a, gap_b = int(n * 0.42), int(n * 0.58)
    env = np.ones(n)
    env[gap_a:gap_b] = 0.0                       # silent gap -> two distinct buzzes
    fade = max(1, int(n * 0.06))
    ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fade)))
    env[:fade] *= ramp
    env[-fade:] *= ramp[::-1]
    out = (tone * env * volume * 1.4).astype(np.float32)  # a touch louder than the soft cues
    try:
        sd.play(out, _SR)
    except Exception:
        pass
