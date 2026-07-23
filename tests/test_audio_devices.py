from __future__ import annotations

import unittest

import numpy as np

from whisperflow_local.audio import input_device_names
from whisperflow_local.stt import audio_rejection_reason


class AudioDeviceTests(unittest.TestCase):
    def test_input_devices_are_filtered_and_deduplicated(self) -> None:
        devices = [
            {"name": "Display", "max_input_channels": 0},
            {"name": "Studio Mic", "max_input_channels": 2},
            {"name": "Studio Mic", "max_input_channels": 1},
            {"name": "MacBook Mic", "max_input_channels": 1},
        ]
        self.assertEqual(
            input_device_names(lambda: devices),
            ["Studio Mic", "MacBook Mic"],
        )

    def test_rejection_reason_distinguishes_silence_from_short_audio(self) -> None:
        cfg = {"min_duration_s": 0.4, "min_rms": 0.005}
        quiet = np.full(16000, 0.001, dtype=np.float32)
        short = np.full(1600, 0.1, dtype=np.float32)
        speech = np.full(16000, 0.02, dtype=np.float32)

        self.assertEqual(audio_rejection_reason(quiet, 16000, cfg), "no_input_signal")
        self.assertEqual(audio_rejection_reason(short, 16000, cfg), "too_short")
        self.assertEqual(audio_rejection_reason(speech, 16000, cfg), "")


if __name__ == "__main__":
    unittest.main()
