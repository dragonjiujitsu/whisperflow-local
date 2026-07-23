from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from .history import HistoryStore
from .recovery import RecoveryStore


class RecoveryWindow(QWidget):
    def __init__(self, store: RecoveryStore, history: HistoryStore | None = None) -> None:
        super().__init__(); self.store = store; self.history = history
        self.setWindowTitle("WhisperFlow Local — Local Data")
        self.setMinimumSize(560, 390)
        layout = QVBoxLayout(self); layout.setContentsMargins(20, 18, 20, 18); layout.setSpacing(9)
        title = QLabel("Your local dictations")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        note = QLabel("Recovery stays in memory and expires automatically. History exists only when you explicitly enable it.")
        note.setWordWrap(True); layout.addWidget(note)
        tabs = QTabWidget(); layout.addWidget(tabs, 1)
        recovery_page = QWidget(); recovery_layout = QVBoxLayout(recovery_page)
        self.items = QListWidget(); self.items.setWordWrap(True)
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.items.setSpacing(4)
        recovery_layout.addWidget(self.items)
        copy = QPushButton("Copy selected result"); copy.clicked.connect(self.copy_selected)
        clear = QPushButton("Clear recovery"); clear.clicked.connect(self.clear)
        recovery_layout.addWidget(copy); recovery_layout.addWidget(clear)
        tabs.addTab(recovery_page, "Recovery")
        history_page = QWidget(); history_layout = QVBoxLayout(history_page)
        self.history_items = QListWidget(); self.history_items.setWordWrap(True)
        self.history_items.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        history_layout.addWidget(self.history_items)
        export = QPushButton("Export history…"); export.clicked.connect(self.export_history)
        delete = QPushButton("Delete all history"); delete.clicked.connect(self.delete_history)
        history_layout.addWidget(export); history_layout.addWidget(delete)
        tabs.addTab(history_page, "History")
        self.refresh()

    def refresh(self) -> None:
        self.items.clear()
        for item in self.store.list():
            preview = item.text.replace("\n", " ")[:180]
            row = QListWidgetItem(f"{preview}\nCouldn’t insert: {item.reason}")
            row.setSizeHint(QSize(0, 76)); row.setData(32, item.item_id); self.items.addItem(row)
        self.history_items.clear()
        if self.history is None or not self.history.enabled:
            self.history_items.addItem("History is off. Enable it in Settings → Privacy.")
        else:
            for entry in reversed(self.history.list()):
                row = QListWidgetItem(entry.text.replace("\n", " ")[:240])
                row.setSizeHint(QSize(0, 54)); row.setData(32, entry.entry_id)
                self.history_items.addItem(row)

    def copy_selected(self) -> None:
        row = self.items.currentItem()
        if row is None: return
        match = next((item for item in self.store.list() if item.item_id == row.data(32)), None)
        if match is not None: QApplication.clipboard().setText(match.text)

    def clear(self) -> None:
        self.store.delete_all(); self.refresh()

    def export_history(self) -> None:
        if self.history is None or not self.history.enabled: return
        filename, _ = QFileDialog.getSaveFileName(self, "Export local history", "whisperflow-history.json", "JSON (*.json)")
        if filename: self.history.export_to(Path(filename))

    def delete_history(self) -> None:
        if self.history is not None: self.history.delete_all()
        self.refresh()
