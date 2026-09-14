import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QDialogButtonBox
from pdfeditor.update_dialog import UpdateDialog


class UpdateDialogLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_update_dialog_has_aligned_actions_and_readable_progress(self):
        update = SimpleNamespace(
            version="1.17.1", release_notes="Update notes\n" * 20,
            release_url="https://github.com/loselessss/sPDF/releases",
            asset=SimpleNamespace(name="sPDF_Setup_1.17.1.exe",
                                  size=150000000, sha256="a" * 64))
        dialog = UpdateDialog(SimpleNamespace(current_version="1.17.0"), update)
        dialog.show()
        self.app.processEvents()
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertEqual(len(buttons.buttons()), 3)
        self.assertIn(dialog.release_button, buttons.buttons())
        self.assertGreaterEqual(dialog.layout().spacing(), 14)
        self.assertEqual(dialog.notes.document().documentMargin(), 14)
        self.assertEqual(dialog.release_button.y(), dialog.install_button.y())
        dialog._on_progress(SimpleNamespace(total_bytes=100, completed_bytes=22,
                                           bytes_per_second=0))
        self.assertFalse(dialog.progress.isTextVisible())
        self.assertTrue(dialog.status.text().startswith("22%"))
        for button in buttons.buttons():
            self.assertGreaterEqual(button.height(), 36)
        dialog.close()
