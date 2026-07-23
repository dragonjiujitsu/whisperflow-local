from PySide6.QtCore import Qt

from whisperflow_local.overlay import voice_pill_window_flags


def test_voice_pill_is_an_independent_nonactivating_window() -> None:
    flags = voice_pill_window_flags()

    assert flags & Qt.WindowType_Mask == Qt.Window
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.WindowDoesNotAcceptFocus
