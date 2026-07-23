import unittest

import numpy as np

from whisperflow_local.audio_ring import AudioChunkRing


class AudioChunkRingTests(unittest.TestCase):
    def test_preallocated_ring_drops_oldest_under_pressure(self):
        ring = AudioChunkRing(2, 4)
        ring.try_write(1, np.array([1, 1], dtype=np.float32))
        ring.try_write(2, np.array([2, 2], dtype=np.float32))
        ring.try_write(3, np.array([3, 3], dtype=np.float32))
        self.assertEqual(ring.dropped, 1)
        self.assertEqual(ring.read()[0], 2)
        sequence, audio = ring.read()
        self.assertEqual(sequence, 3)
        np.testing.assert_array_equal(audio, [3, 3])
        self.assertIsNone(ring.read())


if __name__ == "__main__":
    unittest.main()
