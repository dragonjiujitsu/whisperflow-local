from __future__ import annotations

import unittest

from whisperflow_local.hotkey import HotkeyListener, NativeChord, parse_hotkey


class FakeBackend:
    def __init__(self) -> None:
        self.chord = None
        self.callback = None
        self.unregister_count = 0

    def register(self, chord, callback) -> None:
        self.chord = chord
        self.callback = callback

    def unregister(self) -> None:
        self.unregister_count += 1


class HotkeyTests(unittest.TestCase):
    def test_parses_default_mac_hotkey(self) -> None:
        self.assertEqual(
            parse_hotkey("<cmd>+<shift>+<space>"),
            NativeChord(key_code=49, modifiers=(1 << 8) | (1 << 9)),
        )

    def test_listener_registers_callback_and_unregisters_once(self) -> None:
        backend = FakeBackend()
        activations = []
        listener = HotkeyListener(
            "<cmd>+<shift>+<space>", lambda: activations.append(True), backend
        )
        listener.start()
        backend.callback()
        listener.stop()
        listener.stop()
        self.assertEqual(activations, [True])
        self.assertEqual(backend.unregister_count, 1)

    def test_unsupported_key_fails_before_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported hotkey key"):
            HotkeyListener("<cmd>+<shift>+x", lambda: None, FakeBackend())


if __name__ == "__main__":
    unittest.main()
