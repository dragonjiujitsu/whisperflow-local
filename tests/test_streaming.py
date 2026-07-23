from __future__ import annotations

import time
import unittest

import numpy as np

from whisperflow_local.streaming import StablePrefixReconciler, StreamingSession


class FakeBackend:
    name = "fake"

    def transcribe_window(self, audio, sample_rate, sequence, cancelled=None):
        return {1: "hello brave", 2: "hello bright world"}[sequence]

    def transcribe(self, audio, sample_rate, cancelled=None):
        return "hello bright world"


class StreamingTests(unittest.TestCase):
    def test_revised_suffix_never_retracts_published_stable_prefix(self):
        reconciler = StablePrefixReconciler()
        first = reconciler.update("hello brave", 1, 1)
        second = reconciler.update("hello bright world", 2, 2)
        third = reconciler.update("hello bright world today", 3, 3)
        self.assertEqual(first.stable_text, "")
        self.assertEqual(second.stable_text, "hello")
        self.assertEqual(third.stable_text, "hello bright world")

    def test_final_batch_transcript_is_authoritative(self):
        events = []
        session = StreamingSession(FakeBackend(), 16_000, events.append)
        session.start()
        session.submit(1, np.ones(16_000, dtype=np.float32))
        session.submit(2, np.ones(32_000, dtype=np.float32))
        time.sleep(0.05)
        result = session.finalize(np.ones(48_000, dtype=np.float32), 3)
        self.assertIsNotNone(result)
        self.assertTrue(result.final)
        self.assertEqual(result.text, "hello bright world")
        self.assertEqual(events[-1], result)

    def test_cancel_rejects_new_audio(self):
        session = StreamingSession(FakeBackend(), 16_000, lambda event: None)
        session.start()
        session.cancel()
        self.assertFalse(session.submit(1, np.ones(10, dtype=np.float32)))


if __name__ == "__main__":
    unittest.main()
