import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QCheckBox, QComboBox
from pdfeditor.app import AppWindow
from pdfeditor.preferences_dialog import PreferencesDialog


class PreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_embedded_preferences_keep_renderer_and_startup_hidden(self):
        shell = AppWindow()
        try:
            dialog = PreferencesDialog(shell, lambda: None)
            self.assertEqual(len(dialog.findChildren(QComboBox)), 1)
            self.assertEqual(len(dialog.findChildren(QCheckBox)), 0)
            dialog.close()
        finally:
            shell.close()

    def test_startup_selection_uses_existing_setting_handler(self):
        shell = AppWindow(workspace_mode="reader")
        try:
            with patch.object(shell, "_select_startup_workspace") as select:
                dialog = PreferencesDialog(shell, lambda: None)
                combos = dialog.findChildren(QComboBox)
                startup = next(combo for combo in combos if combo.count() == 2
                               and combo.itemText(0) != "English")
                startup.activated[int].emit(1)
                select.assert_called_once_with("editor")
                dialog.close()
        finally:
            shell.close()
