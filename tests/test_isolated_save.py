import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import fitz

from pdfeditor.core import Document
from pdfeditor.document_snapshot import DocumentSnapshot, cleanup_snapshots, file_revision
from pdfeditor.save_transaction import destination_lock


class IsolatedSaveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "source.pdf")
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 72), "Original")
            pdf.save(self.path)
        self.original = Path(self.path).read_bytes()

    def document(self, **kwargs):
        document = Document(self.path, isolated=True, **kwargs)
        self.addCleanup(document.close)
        return document

    def test_stale_writer_cannot_overwrite_newer_save(self):
        first, second = self.document(), self.document()
        first.add_text_box(0, (72, 100), "First")
        second.add_text_box(0, (72, 120), "Second")
        first.save_as(self.path)
        saved = Path(self.path).read_bytes()
        with self.assertRaisesRegex(OSError, "another writer"):
            second.save_as(self.path)
        self.assertEqual(Path(self.path).read_bytes(), saved)
        self.assertIn("Second", second._doc[0].get_text())
        with fitz.open(self.path) as pdf:
            self.assertIn("First", pdf[0].get_text())
            self.assertNotIn("Second", pdf[0].get_text())

    @unittest.skipUnless(os.name == "nt", "Windows file sharing")
    def test_real_external_file_handle_blocks_replace_without_losing_edits(self):
        editor, reader = self.document(), self.document(read_only=True)
        editor.add_text_box(0, (72, 100), "Pending")
        with open(self.path, "rb") as external_handle:
            with self.assertRaises(PermissionError):
                editor.save_as(self.path)
            self.assertEqual(external_handle.read(), self.original)
        self.assertIn("Pending", editor._doc[0].get_text())
        self.assertNotIn("Pending", reader._doc[0].get_text())
        editor.save_as(self.path)
        self.assertTrue(reader.render(0, .2)[3])

    def test_backup_failure_preserves_original_previous_backup_and_edits(self):
        editor = self.document()
        backup = Path(self.path + ".bak")
        backup.write_bytes(b"previous backup")
        editor.add_text_box(0, (72, 100), "Pending")
        with patch("pdfeditor.save_transaction.shutil.copyfileobj", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                editor.save_as(self.path)
        self.assertEqual(Path(self.path).read_bytes(), self.original)
        self.assertEqual(backup.read_bytes(), b"previous backup")
        self.assertIn("Pending", editor._doc[0].get_text())

    def test_busy_writer_lock_fails_without_waiting(self):
        editor = self.document()
        with destination_lock(self.path):
            with self.assertRaises(OSError):
                editor.save_as(self.path)
        self.assertEqual(Path(self.path).read_bytes(), self.original)
        editor.save_as(self.path)

    def test_success_cleans_backup_in_both_save_paths(self):
        for isolated in (False, True):
            with self.subTest(isolated=isolated):
                editor = Document(self.path, isolated=isolated)
                try:
                    editor.add_text_box(0, (72, 100), "Saved")
                    editor.save_as(self.path)
                    self.assertFalse(Path(self.path + ".bak").exists())
                    with fitz.open(self.path) as saved:
                        self.assertIn("Saved", saved[0].get_text())
                finally:
                    editor.close()

    def test_replace_failure_preserves_backup_in_both_save_paths(self):
        real_replace = os.replace
        def fail_pdf_replace(source, target):
            if os.fspath(target) == self.path:
                raise PermissionError("destination busy")
            return real_replace(source, target)
        for isolated in (False, True):
            with self.subTest(isolated=isolated):
                editor = Document(self.path, isolated=isolated)
                try:
                    editor.add_text_box(0, (72, 100), "Pending")
                    with patch("pdfeditor.core.os.replace", side_effect=fail_pdf_replace):
                        with self.assertRaises(PermissionError):
                            editor.save_as(self.path)
                    self.assertEqual(Path(self.path).read_bytes(), self.original)
                    self.assertEqual(Path(self.path + ".bak").read_bytes(), self.original)
                    self.assertIn("Pending", editor._doc[0].get_text())
                finally:
                    editor.close()

    def test_backup_disabled_preserves_existing_backup(self):
        backup = Path(self.path + ".bak")
        backup.write_bytes(b"keep this backup")
        self.document().save_as(self.path, backup=False)
        self.assertEqual(backup.read_bytes(), b"keep this backup")

    def test_backup_cleanup_failure_does_not_report_save_failure(self):
        editor = self.document()
        editor.add_text_box(0, (72, 100), "Saved")
        real_unlink = os.unlink
        def fail_backup_unlink(path, *args, **kwargs):
            if os.fspath(path) == self.path + ".bak":
                raise PermissionError("backup busy")
            return real_unlink(path, *args, **kwargs)
        with patch("pdfeditor.save_transaction.os.unlink", side_effect=fail_backup_unlink):
            editor.save_as(self.path)
        self.assertEqual(Path(self.path + ".bak").read_bytes(), self.original)
        with fitz.open(self.path) as saved:
            self.assertIn("Saved", saved[0].get_text())

    @unittest.skipUnless(os.name == "nt", "Windows delete-on-close locks")
    def test_lock_cleanup_on_success_and_exception(self):
        sidecar = Path(self.path + ".spdf-save.lock")
        sidecar.write_bytes(b"legacy lock")
        with destination_lock(self.path):
            self.assertTrue(sidecar.exists())
        self.assertFalse(sidecar.exists())
        with self.assertRaises(RuntimeError):
            with destination_lock(self.path):
                raise RuntimeError("save failed")
        self.assertFalse(sidecar.exists())

    @unittest.skipUnless(os.name == "nt", "Windows delete-on-close locks")
    def test_crashed_writer_releases_and_deletes_lock(self):
        code = ("import sys; from pdfeditor.save_transaction import destination_lock; "
                "lock = destination_lock(sys.argv[1]); lock.__enter__(); "
                "print('locked', flush=True); sys.stdin.read()")
        child = subprocess.Popen([sys.executable, "-c", code, self.path],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(child.stdout.readline().strip(), b"locked")
            with self.assertRaises(OSError):
                with destination_lock(self.path):
                    self.fail("another process owns the lock")
            child.kill()  # Only our disposable test worker, never a user's app.
            child.wait(timeout=10)
            # Windows may finish kernel handle teardown just after process exit.
            deadline = time.monotonic() + 3
            while Path(self.path + ".spdf-save.lock").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(Path(self.path + ".spdf-save.lock").exists())
            with destination_lock(self.path):
                pass
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            child.stdin.close()
            child.stdout.close()

    def test_private_snapshot_preserves_encryption_and_cleans_up(self):
        protected = str(Path(self.directory.name) / "protected.pdf")
        with fitz.open(self.path) as pdf:
            pdf.save(protected, encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw="owner", user_pw="reader")
        doc = Document(protected, "owner", isolated=True)
        private = Path(doc._snapshot.path)
        with fitz.open(private) as pdf:
            self.assertTrue(pdf.needs_pass)
        doc.save_as(protected)
        with fitz.open(protected) as pdf:
            self.assertTrue(pdf.needs_pass)
        doc.close()
        self.assertFalse(private.exists())

    def test_failed_cleanup_is_retried_without_escaping_callback(self):
        copy = DocumentSnapshot(self.path)
        with patch.object(copy.directory, "cleanup", side_effect=PermissionError("busy")):
            copy.close()
        self.assertTrue(Path(copy.path).exists())
        cleanup_snapshots()
        self.assertFalse(Path(copy.path).exists())
