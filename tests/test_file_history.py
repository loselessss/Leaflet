import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from pdfeditor import settings
from pdfeditor.app import AppWindow


class FileHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = str(self.root / "entry.pdf")
        self.other = str(self.root / "keep.pdf")
        self.settings_patch = patch.object(settings, "PATH", str(self.root / "settings.json"))
        self.old_patch = patch.object(settings, "_OLD_PATH", str(self.root / "absent.json"))
        self.settings_patch.start()
        self.old_patch.start()
        settings.push_recent(self.other)
        settings.push_recent(self.path)
        settings.add_favorite(self.path)
        settings.add_favorite(self.other)
        self.window = AppWindow()

    def tearDown(self):
        # Failed tabs are disposed on the next event-loop turn, while their
        # shell-owned menus/actions still need to be alive.
        for _ in range(4):
            self.app.processEvents()
        QTest.qWait(25)  # Tab disposal intentionally waits for a 16ms frame.
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.settings_patch.stop()
        self.old_patch.stop()
        self.directory.cleanup()

    def assert_retained(self):
        self.assertIn(self.path, settings.recent_files())
        self.assertIn(self.path, settings.favorites())

    def test_missing_file_is_kept_when_confirmation_declined(self):
        with patch("pdfeditor.file_history.QMessageBox.question", return_value=QMessageBox.No) as question:
            self.window.open_recent(self.path)
        question.assert_called_once()
        self.assertEqual(question.call_args.args[-1], QMessageBox.No)
        self.assert_retained()
        self.assertEqual(self.window._tabs.count(), 0)

    def test_home_page_missing_file_removes_both_entries_only_after_confirmation(self):
        with patch("pdfeditor.file_history.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window._start_page.open_file.emit(self.path)
        self.assertNotIn(self.path, settings.recent_files())
        self.assertNotIn(self.path, settings.favorites())
        self.assertIn(self.other, settings.recent_files())
        self.assertIn(self.other, settings.favorites())
        self.assertEqual(self.window._start_page.recent_list.count(), 1)
        self.assertEqual(self.window._start_page.fav_list.count(), 1)

    def test_corrupt_file_prompts_once_and_never_deletes_original(self):
        original = b"not a PDF"
        Path(self.path).write_bytes(original)
        with patch("pdfeditor.file_history.QMessageBox.question", return_value=QMessageBox.Yes) as question, \
                patch("pdfeditor.app.QMessageBox.critical") as critical:
            self.window.open_recent(self.path)
            self.app.processEvents()
        question.assert_called_once()
        critical.assert_not_called()
        self.assertEqual(Path(self.path).read_bytes(), original)
        self.assertNotIn(self.path, settings.recent_files())
        self.assertNotIn(self.path, settings.favorites())
        self.assertEqual(self.window._tabs.count(), 0)

    def test_permission_failure_can_be_retained_for_retry(self):
        Path(self.path).write_bytes(b"unavailable document")
        with patch("pdfeditor.core.Document", side_effect=PermissionError("access denied")), \
                patch("pdfeditor.file_history.QMessageBox.question", return_value=QMessageBox.No) as question:
            self.window.open_recent(self.path)
            self.app.processEvents()
        question.assert_called_once()
        self.assert_retained()

    def test_cancelled_password_prompt_does_not_offer_removal(self):
        from pdfeditor.core import PasswordRequired
        Path(self.path).write_bytes(b"password document")
        with patch("pdfeditor.core.Document", side_effect=PasswordRequired(self.path)), \
                patch("pdfeditor.app.QInputDialog.getText", return_value=("", False)), \
                patch("pdfeditor.file_history.QMessageBox.question") as question:
            self.window.open_recent(self.path)
            self.app.processEvents()
        question.assert_not_called()
        self.assert_retained()

    def test_ordinary_file_dialog_failure_does_not_offer_list_removal(self):
        Path(self.path).write_bytes(b"not a PDF")
        with patch("pdfeditor.app.QMessageBox.critical") as critical, \
                patch("pdfeditor.file_history.QMessageBox.question") as question:
            self.window.open_in_tab(self.path)
            self.app.processEvents()
        critical.assert_called_once()
        question.assert_not_called()
        self.assert_retained()

    def test_removal_preserves_other_settings(self):
        data = settings._load()
        data["custom"] = {"value": 42}
        settings._save(data)
        settings.remove_file_entry(self.path.upper())
        self.assertEqual(settings._load()["custom"], {"value": 42})
        self.assertNotIn(self.path, settings.recent_files())
        self.assertNotIn(self.path, settings.favorites())

    def test_successful_and_already_open_documents_are_kept(self):
        import pymupdf
        with pymupdf.open() as pdf:
            pdf.new_page()
            pdf.save(self.path)
        with patch("pdfeditor.file_history.QMessageBox.question") as question:
            tab = self.window.open_recent(self.path)
            for _ in range(4):
                self.app.processEvents()
            self.assertIsNotNone(tab.doc)
            self.assertIs(self.window.open_recent(self.path), tab)
        question.assert_not_called()
        self.assert_retained()

    def test_failed_settings_write_keeps_lists_and_original_file(self):
        Path(self.path).write_bytes(b"not a PDF")
        with patch("pdfeditor.file_history.QMessageBox.question", return_value=QMessageBox.Yes), \
                patch("pdfeditor.settings._save", side_effect=OSError("settings busy")), \
                patch("pdfeditor.file_history.QMessageBox.warning") as warning:
            self.window.open_recent(self.path)
            self.app.processEvents()
        warning.assert_called_once()
        self.assert_retained()
        self.assertEqual(Path(self.path).read_bytes(), b"not a PDF")
