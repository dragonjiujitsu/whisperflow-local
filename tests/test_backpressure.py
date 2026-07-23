import unittest

import numpy as np

from whisperflow_local.streaming import BoundedAudioQueue


class BackpressureTests(unittest.TestCase):
    def test_queue_drops_oldest_and_never_blocks_when_full(self):
        chunks = BoundedAudioQueue(capacity=2)
        for sequence in range(5):
            self.assertTrue(chunks.submit(sequence, np.array([sequence], dtype=np.float32)))
        first, _ = chunks.get()
        chunks.done()
        second, _ = chunks.get()
        chunks.done()
        self.assertEqual((first, second), (3, 4))
        self.assertEqual(chunks.stats().submitted, 5)
        self.assertEqual(chunks.stats().dropped, 3)
        self.assertEqual(chunks.stats().peak_queue, 2)


if __name__ == "__main__":
    unittest.main()
