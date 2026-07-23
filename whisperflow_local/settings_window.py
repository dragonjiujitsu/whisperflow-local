"""Native settings for capture, writing, local data, and privacy."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QFileDialog, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from . import autostart
from .audio import input_device_names
from .history import HistoryStore
from .paths import AppPaths
from .settings import SettingsError, SettingsStore
from .vocabulary import VocabularyData, VocabularyStore


class SettingsWindow(QWidget):
    def __init__(self, defaults_path: Path, paths: AppPaths | None = None) -> None:
        super().__init__()
        self.paths = paths or AppPaths.discover()
        self.store = SettingsStore(defaults_path, self.paths)
        self.vocabulary_store = VocabularyStore(self.paths.support / "vocabulary.json")
        self.setWindowTitle("WhisperFlow Local — Settings")
        self.setMinimumSize(620, 500)
        self.setStyleSheet("""
            QWidget { font-size: 13px; }
            QLabel#sectionTitle { font-size: 17px; font-weight: 600; }
            QTabWidget::pane { border: 1px solid #d8d8dc; border-radius: 8px; }
            QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {
                border: 1px solid #c9c9ce; border-radius: 6px; padding: 6px;
            }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(8)
        heading = QLabel("Make dictation yours")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        intro = QLabel("Everything here stays on this Mac. Transcript history is off by default.")
        intro.setStyleSheet("color: #66666d;")
        root.addWidget(intro)

        tabs = QTabWidget()
        tabs.addTab(self._capture_tab(), "Capture")
        tabs.addTab(self._writing_tab(), "Writing")
        tabs.addTab(self._privacy_tab(), "Privacy")
        root.addWidget(tabs, 1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        controls = QHBoxLayout()
        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.load_values)
        save_button = QPushButton("Save changes")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save_values)
        controls.addStretch()
        controls.addWidget(reload_button)
        controls.addWidget(save_button)
        root.addLayout(controls)
        self.load_values()

    def _capture_tab(self) -> QWidget:
        page = QWidget(); form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16); form.setVerticalSpacing(10)
        self.hotkey = QLineEdit()
        self.max_seconds = QSpinBox(); self.max_seconds.setRange(1, 3600)
        self.input_device = QComboBox()
        self.refresh_input_devices = QPushButton("Refresh")
        self.refresh_input_devices.clicked.connect(self._refresh_input_devices)
        self.insert_mode = QComboBox(); self.insert_mode.addItems(["paste", "type"])
        self.performance_profile = QComboBox(); self.performance_profile.addItems(["instant", "quality"])
        self.overlay = QCheckBox("Show the recording pill")
        self.sound = QCheckBox("Play start, stop, and error sounds")
        self.auto_submit = QCheckBox("Press Enter after insertion")
        self.auto_submit.setToolTip("Off by default. Enable only for intentional automatic submission.")
        form.addRow("Global hotkey", self.hotkey)
        device_row = QHBoxLayout(); device_row.addWidget(self.input_device, 1)
        device_row.addWidget(self.refresh_input_devices)
        form.addRow("Input device", device_row)
        form.addRow("Maximum recording", self.max_seconds)
        form.addRow("Speed / quality", self.performance_profile)
        form.addRow("Insertion mode", self.insert_mode)
        form.addRow("", self.overlay); form.addRow("", self.sound); form.addRow("", self.auto_submit)
        return page

    def _writing_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page); form = QFormLayout()
        layout.setContentsMargins(16, 16, 16, 16); layout.setSpacing(7)
        self.writing_mode = QComboBox(); self.writing_mode.addItems(["natural", "polished", "verbatim", "email"])
        form.addRow("Default writing mode", self.writing_mode)
        layout.addLayout(form)
        label = QLabel("Personal vocabulary — one term per line")
        layout.addWidget(label)
        self.vocabulary = QPlainTextEdit(); self.vocabulary.setPlaceholderText("Kaden\nMLX\nWhisperFlow Local")
        layout.addWidget(self.vocabulary)
        label = QLabel("Deterministic replacements — one ‘heard = written’ pair per line")
        layout.addWidget(label)
        self.replacements = QPlainTextEdit(); self.replacements.setPlaceholderText("caden = Kaden")
        layout.addWidget(self.replacements)
        label = QLabel("Per-app modes — one ‘bundle.id = mode’ pair per line")
        layout.addWidget(label)
        self.per_app_modes = QPlainTextEdit()
        self.per_app_modes.setMaximumHeight(86)
        self.per_app_modes.setPlaceholderText("com.apple.mail = email")
        layout.addWidget(self.per_app_modes)
        controls = QHBoxLayout()
        import_button = QPushButton("Import vocabulary…"); import_button.clicked.connect(self.import_vocabulary)
        export_button = QPushButton("Export vocabulary…"); export_button.clicked.connect(self.export_vocabulary)
        controls.addWidget(import_button); controls.addWidget(export_button); controls.addStretch()
        layout.addLayout(controls)
        return page

    def _privacy_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16); layout.setSpacing(10)
        copy = QLabel("By default, completed dictations are never written to disk. Failed insertion recovery lives only in memory for 15 minutes.")
        copy.setWordWrap(True); layout.addWidget(copy)
        self.history_enabled = QCheckBox("Keep local dictation history")
        self.retention_days = QSpinBox(); self.retention_days.setRange(1, 365); self.retention_days.setSuffix(" days")
        form = QFormLayout(); form.addRow("", self.history_enabled); form.addRow("Retention", self.retention_days)
        layout.addLayout(form)
        self.launch_at_login = QCheckBox("Launch WhisperFlow Local when I log in")
        layout.addWidget(self.launch_at_login)
        delete_history = QPushButton("Delete all retained history")
        delete_history.clicked.connect(self.delete_history)
        delete_vocabulary = QPushButton("Delete vocabulary and replacements")
        delete_vocabulary.clicked.connect(self.delete_vocabulary)
        layout.addWidget(delete_history); layout.addWidget(delete_vocabulary); layout.addStretch()
        return page

    def load_values(self) -> None:
        try:
            value = self.store.load(); personal = value.get("personalization", {})
            self.hotkey.setText(value["hotkey"]["combo"])
            self.max_seconds.setValue(int(value["audio"]["max_seconds"]))
            self._populate_input_devices(
                str(value["audio"].get("input_device") or "")
            )
            self.insert_mode.setCurrentText(value["insert"]["mode"])
            self.performance_profile.setCurrentText(value.get("performance", {}).get("profile", "instant"))
            self.writing_mode.setCurrentText(personal.get("writing_mode", "natural"))
            self.overlay.setChecked(bool(value["overlay"]["enabled"]))
            self.sound.setChecked(bool(value["sound"]["enabled"]))
            self.auto_submit.setChecked(bool(value["insert"]["press_enter_after"]))
            self.history_enabled.setChecked(bool(value.get("history", {}).get("enabled", False)))
            self.retention_days.setValue(int(value.get("history", {}).get("retention_days", 7)))
            self.launch_at_login.setChecked(autostart.is_installed())
            vocabulary = self.vocabulary_store.load()
            self.vocabulary.setPlainText("\n".join(vocabulary.terms))
            self.replacements.setPlainText("\n".join(f"{a} = {b}" for a, b in vocabulary.replacements))
            self.per_app_modes.setPlainText("\n".join(
                f"{bundle_id} = {mode}" for bundle_id, mode in sorted(personal.get("per_app_modes", {}).items())
            ))
            self.status.setText("")
        except (OSError, ValueError, SettingsError) as exc:
            self.status.setText(f"Could not load settings: {exc}")

    def save_values(self) -> None:
        try:
            replacements = []
            for line in self.replacements.toPlainText().splitlines():
                if not line.strip(): continue
                if "=" not in line: raise SettingsError(f"Replacement needs ‘=’: {line}")
                source, target = line.split("=", 1); replacements.append((source.strip(), target.strip()))
            terms = tuple(line.strip() for line in self.vocabulary.toPlainText().splitlines() if line.strip())
            per_app_modes = {}
            for line in self.per_app_modes.toPlainText().splitlines():
                if not line.strip(): continue
                if "=" not in line: raise SettingsError(f"Per-app mode needs ‘=’: {line}")
                bundle_id, mode = (part.strip() for part in line.split("=", 1))
                if mode not in {"natural", "polished", "verbatim", "email"}:
                    raise SettingsError(f"Unknown writing mode for {bundle_id}: {mode}")
                per_app_modes[bundle_id] = mode
            overrides = {
                "hotkey": {"combo": self.hotkey.text().strip()},
                "audio": {"max_seconds": self.max_seconds.value(), "input_device": str(self.input_device.currentData() or "")},
                "performance": {"profile": self.performance_profile.currentText()},
                "personalization": {"writing_mode": self.writing_mode.currentText(), "per_app_modes": per_app_modes},
                "history": {"enabled": self.history_enabled.isChecked(), "retention_days": self.retention_days.value()},
                "insert": {"mode": self.insert_mode.currentText(), "press_enter_after": self.auto_submit.isChecked()},
                "overlay": {"enabled": self.overlay.isChecked()}, "sound": {"enabled": self.sound.isChecked()},
            }
            self.store.save_overrides(overrides)
            self.vocabulary_store.save(VocabularyData(terms, tuple(replacements)))
            if self.launch_at_login.isChecked(): autostart.install()
            else: autostart.uninstall()
            self.status.setText("Saved locally. Restart to apply hotkey and model profile changes.")
        except (OSError, ValueError, SettingsError) as exc:
            self.status.setText(f"Could not save settings: {exc}")

    def _populate_input_devices(self, selected: str = "") -> None:
        self.input_device.clear()
        self.input_device.addItem("System default", "")
        for name in input_device_names():
            self.input_device.addItem(name, name)
        index = self.input_device.findData(selected)
        if selected and index < 0:
            self.input_device.addItem(f"Unavailable — {selected}", selected)
            index = self.input_device.count() - 1
        self.input_device.setCurrentIndex(max(0, index))

    def _refresh_input_devices(self) -> None:
        selected = str(self.input_device.currentData() or "")
        self._populate_input_devices(selected)
        self.status.setText("Microphone list refreshed.")

    def delete_history(self) -> None:
        HistoryStore(self.paths.support / "history.json", enabled=True).delete_all()
        self.status.setText("All retained history was deleted.")

    def delete_vocabulary(self) -> None:
        self.vocabulary_store.delete_all(); self.vocabulary.clear(); self.replacements.clear()
        self.status.setText("Vocabulary and replacements were deleted.")

    def import_vocabulary(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Import vocabulary", "", "JSON (*.json)")
        if not filename: return
        try:
            self.vocabulary_store.import_from(Path(filename)); self.load_values()
            self.status.setText("Vocabulary and replacements imported.")
        except (OSError, ValueError) as exc:
            self.status.setText(f"Could not import vocabulary: {exc}")

    def export_vocabulary(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "Export vocabulary", "whisperflow-vocabulary.json", "JSON (*.json)")
        if not filename: return
        try:
            self.vocabulary_store.export_to(Path(filename))
            self.status.setText("Vocabulary and replacements exported.")
        except OSError as exc:
            self.status.setText(f"Could not export vocabulary: {exc}")
