import unittest

from whisperflow_local.recovery import RecoveryStore


class RecoveryTests(unittest.TestCase):
    def test_recovery_is_memory_only_and_expires(self):
        now = [100.0]
        store = RecoveryStore(ttl_seconds=10, clock=lambda: now[0])
        item = store.add("words", "focus changed")
        self.assertEqual(store.list()[0], item)
        now[0] = 111
        self.assertEqual(store.list(), ())

    def test_delete_all(self):
        store = RecoveryStore()
        store.add("one", "failed")
        store.delete_all()
        self.assertEqual(store.list(), ())


if __name__ == "__main__":
    unittest.main()
