import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from pdfeditor.core import Document


class ReaderAnnotationDocumentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "reader.pdf"
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((72, 72), "Original body text")
            page.add_text_annot((100, 100), "Existing note")
            pdf.new_page()
            pdf.save(self.source)
        self.original = self.source.read_bytes()

    def open(self, path=None, password=None):
        document = Document(str(path or self.source), password, read_only=True,
                            annotations_enabled=True, annotations_in_pdf=True)
        self.addCleanup(document.close)
        return document

    def test_reader_saves_notes_highlights_and_deletions_into_original(self):
        document = self.open()
        document.set_note_text(0, document.annots(0)[0]["xref"], "Revised note")
        document.add_highlight(0, [(70, 60, 160, 76)])
        removed = document.add_note(1, 100, 100, "Remove me")
        document.delete_annot(1, removed)
        document.add_note(1, 70, 90, "새 메모")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertTrue(document.annotations_dirty)
        document.save_reader_pdf(str(self.source))
        self.assertFalse(document.annotations_dirty)
        reopened = self.open()
        self.assertEqual(reopened.annots(0)[0]["text"], "Revised note")
        self.assertEqual(reopened.annots(0)[1]["kind"], "Highlight")
        self.assertEqual([item["text"] for item in reopened.annots(1)], ["새 메모"])
        self.assertIn("Original body text", reopened._doc[0].get_text())
        self.assertFalse(Path(str(self.source) + ".spdf-annotations.json").exists())
        self.assertFalse(Path(str(self.source) + ".bak").exists())
        self.assertFalse(Path(str(self.source) + ".spdf-save.lock").exists())

    def test_undo_redo_after_save_replays_original_without_duplicates(self):
        document = self.open()
        note = document.add_note(1, 80, 90, "Added")
        document.set_note_text(1, note, "Edited")
        document.save_reader_pdf(str(self.source))
        self.assertTrue(document.step_annotation_history())
        self.assertEqual(document.annots(1)[0]["text"], "Added")
        document.save_reader_pdf(str(self.source))
        self.assertTrue(document.step_annotation_history(True))
        self.assertEqual(document.annots(1)[0]["text"], "Edited")
        document.save_reader_pdf(str(self.source))
        self.assertEqual(len(self.open().annots(1)), 1)
        document.step_annotation_history()
        document.step_annotation_history()
        document.save_reader_pdf(str(self.source))
        self.assertEqual(self.open().annots(1), [])

    def test_save_as_switches_destination_and_preserves_undo_baseline(self):
        document = self.open()
        document.add_note(1, 80, 90, "Copy note")
        target = self.source.with_name("copy.pdf")
        document.save_reader_pdf(str(target))
        self.assertEqual(document.path, str(target))
        self.assertEqual(self.source.read_bytes(), self.original)
        document.step_annotation_history()
        document.save_reader_pdf(document.path)
        self.assertEqual(self.open(target).annots(1), [])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_replace_failure_preserves_source_pending_edits_and_dirty_state(self):
        document = self.open()
        document.add_note(1, 80, 90, "Pending")
        with patch("pdfeditor.core.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                document.save_reader_pdf(str(self.source))
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(document.annots(1)[0]["text"], "Pending")
        self.assertTrue(document.annotations_dirty)
        document.save_reader_pdf(str(self.source))
        self.assertFalse(document.annotations_dirty)

    def test_stale_reader_cannot_overwrite_another_save(self):
        first = self.open()
        second = self.open()
        first.add_note(1, 80, 90, "First")
        second.add_note(1, 100, 110, "Second")
        first.save_reader_pdf(str(self.source))
        with self.assertRaises(OSError):
            second.save_reader_pdf(str(self.source))
        self.assertTrue(second.annotations_dirty)
        self.assertEqual(self.open().annots(1)[0]["text"], "First")
        target = self.source.with_name("second.pdf")
        second.save_reader_pdf(str(target))
        self.assertEqual(self.open(target).annots(1)[0]["text"], "Second")

    def test_body_edits_and_embedded_original_saves_stay_blocked(self):
        document = self.open()
        for method, args in ((document.rotate_page, (0, 90)),
                             (document.delete_page, (0,)),
                             (document.save_as, (str(self.source),)),
                             (document.restore, (document.snapshot(),))):
            with self.subTest(method=method.__name__), self.assertRaises(PermissionError):
                method(*args)
        embedded = Document(str(self.source), read_only=True, annotations_enabled=True)
        self.addCleanup(embedded.close)
        with self.assertRaises(PermissionError):
            embedded.save_reader_pdf(str(self.source))
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_encryption_is_preserved_and_annotation_permission_is_respected(self):
        for allow_annotations in (True, False):
            target = self.source.with_name("allowed.pdf" if allow_annotations else "blocked.pdf")
            with fitz.open(self.source) as pdf:
                pdf.save(target, encryption=fitz.PDF_ENCRYPT_AES_256,
                         owner_pw="owner", user_pw="reader",
                         permissions=fitz.PDF_PERM_ANNOTATE if allow_annotations else 0)
            document = self.open(target, "reader")
            if not allow_annotations:
                self.assertFalse(document.annotations_enabled)
                with self.assertRaises(PermissionError):
                    document.add_note(1, 70, 90, "Blocked")
                with self.assertRaises(PermissionError):
                    document.save_reader_pdf(str(target))
                continue
            document.add_note(1, 70, 90, "Encrypted note")
            document.save_reader_pdf(str(target))
            reopened = self.open(target, "reader")
            self.assertTrue(reopened.password_protected)
            self.assertEqual(reopened.annots(1)[0]["text"], "Encrypted note")
            self.assertFalse(Path(str(target) + ".spdf-annotations.json").exists())
