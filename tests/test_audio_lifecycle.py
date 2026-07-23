from __future__ import annotations

import queue
import unittest
from unittest.mock import patch

import numpy as np

from whisperflow_local.app import start_audio_session, stop_audio_session
from whisperflow_local.audio import Recorder
from whisperflow_local.sound import play_tone


class FakeRecorder:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def start(self) -> None:
        self.events.append("input:start")

    def stop(self) -> np.ndarray:
        self.events.append("input:stop")
        return np.array([0.25], dtype=np.float32)


class AudioLifecycleTests(unittest.TestCase):
    def test_cues_never_overlap_the_microphone_stream(self) -> None:
        events = []
        recorder = FakeRecorder(events)
        cue = lambda: events.append("cue")

        start_audio_session(recorder, cue)
        audio = stop_audio_session(recorder, cue)

        self.assertEqual(
            events, ["cue", "input:start", "input:stop", "cue"]
        )
        np.testing.assert_array_equal(audio, np.array([0.25], dtype=np.float32))

    def test_tone_waits_until_portaudio_closes_its_output_stream(self) -> None:
        with patch("whisperflow_local.sound.sd.play") as play:
            play_tone(920, 10, 0.05)
        self.assertTrue(play.call_args.kwargs["blocking"])

    def test_deadline_releases_microphone_without_audio_callbacks(self) -> None:
        events = []

        class Stream:
            def abort(self) -> None:
                events.append("abort")

            def close(self) -> None:
                events.append("close")

        recorder = Recorder(
            {
                "sample_rate": 16000,
                "channels": 1,
                "max_seconds": 1,
                "input_device": "",
            },
            queue.Queue(),
            on_overflow=lambda: events.append("overflow"),
        )
        recorder._stream = Stream()
        recorder._deadline_reached()

        self.assertEqual(events, ["abort", "close", "overflow"])
        self.assertTrue(recorder.overflowed)


if __name__ == "__main__":
    unittest.main()
