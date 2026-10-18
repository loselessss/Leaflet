import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from pdfeditor.core import Document


class AnnotationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source.pdf"
        self.sidecar = Path(str(self.source) + ".spdf-annotations.json")
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((72, 72), "Original text")
            page.add_text_annot((100, 100), "Original note")
            pdf.new_page()
            pdf.save(self.source)
        self.original = self.source.read_bytes()

    def open(self, **options):
        options.setdefault("read_only", True)
        options.setdefault("annotations_enabled", True)
        doc = Document(str(self.source), **options)
        self.addCleanup(doc.close)
        return doc

    def test_highlight_comments_replay_through_sidecar_and_history(self):
        doc = self.open()
        xref = doc.add_highlight(0, [(70, 58, 165, 78)])
        doc.set_note_text(0, xref, "Check this result")
        doc.save_annotations()
        reopened = self.open()
        marked = next(item for item in reopened.annots(0, include_text=True) if item["kind"] == "Highlight")
        self.assertEqual(marked["text"], "Check this result")
        self.assertEqual(marked["quote"], "Original text")
        reopened.step_annotation_history()
        self.assertEqual(reopened.annots(0)[1]["text"], "")
        reopened.step_annotation_history(forward=True)
        self.assertEqual(reopened.annots(0)[1]["text"], "Check this result")
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_notes_highlights_edits_deletes_round_trip_without_source_changes(self):
        doc = self.open()
        self.assertIsNone(doc.annotation_error)
        original_note = doc.annots(0)[0]["xref"]
        doc.set_note_text(0, original_note, "Revised original")
        added = doc.add_note(1, 80, 80, "새 메모")
        doc.set_note_text(1, added, "Changed note")
        doomed = doc.add_note(1, 110, 110, "Delete me")
        doc.delete_annot(1, doomed)
        doc.add_highlight(0, [(70, 60, 160, 76)])
        self.assertTrue(doc.annotations_dirty)
        doc.save_annotations()
        self.assertFalse(doc.annotations_dirty)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(json.loads(self.sidecar.read_text("utf-8"))["version"], 1)
        again = self.open()
        self.assertIsNone(again.annotation_error)
        self.assertEqual(again.annots(1)[0]["text"], "Changed note")
        self.assertEqual(again.annots(0)[0]["text"], "Revised original")
        self.assertEqual(again.annots(0)[1]["kind"], "Highlight")
        viewer = self.open(annotations_enabled=False)
        self.assertEqual(viewer.annots(1)[0]["text"], "Changed note")
        with self.assertRaises(PermissionError):
            viewer.add_note(0, 20, 20, "blocked")

    def test_body_edits_saves_and_snapshot_injection_remain_blocked(self):
        doc = self.open()
        for method, args in ((doc.rotate_page, (0, 90)),
                             (doc.delete_page, (0,)),
                             (doc.add_bookmark, ("blocked", 0)),
                             (doc.save_as, (str(self.source),)),
                             (doc.restore, (doc.snapshot(),)),
                             (doc.insert_ocr_text, (0, []))):
            with self.subTest(method=method.__name__), self.assertRaises(PermissionError):
                method(*args)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_undo_redo_branch_and_saved_empty_state(self):
        doc = self.open()
        note = doc.add_note(0, 80, 80, "Added")
        doc.set_note_text(0, note, "Edited")
        self.assertTrue(doc.step_annotation_history())
        self.assertEqual(doc.annots(0)[-1]["text"], "Added")
        self.assertTrue(doc.step_annotation_history(True))
        self.assertEqual(doc.annots(0)[-1]["text"], "Edited")
        doc.step_annotation_history()
        doc.add_highlight(0, [(70, 60, 160, 76)])
        self.assertFalse(doc.can_redo_annotation)
        doc.save_annotations()
        self.assertEqual(len(self.open().annots(0)), 3)
        while doc.can_undo_annotation:
            doc.step_annotation_history()
        doc.save_annotations()
        self.assertEqual(len(self.open().annots(0)), 1)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_export_preserves_original_and_does_not_change_source_path(self):
        doc = self.open()
        doc.add_note(0, 70, 90, "Export me")
        target = self.source.with_name("annotated.pdf")
        doc.export_annotated_pdf(target)
        with fitz.open(target) as exported:
            self.assertEqual(len(list(exported[0].annots())), 2)
            self.assertIn("Original text", exported[0].get_text())
        self.assertEqual(doc.path, str(self.source))
        self.assertEqual(self.source.read_bytes(), self.original)
        with self.assertRaises(ValueError):
            doc.export_annotated_pdf(self.source)
        alias = self.source.with_name("hardlink.pdf")
        os.link(self.source, alias)
        with self.assertRaises(ValueError):
            doc.export_annotated_pdf(alias)
        doc.save_annotations()
        before = self.sidecar.read_bytes()
        with self.assertRaises(ValueError):
            doc.export_annotated_pdf(self.sidecar)
        self.assertEqual(self.sidecar.read_bytes(), before)

    def test_concurrent_saves_refuse_to_overwrite_other_window(self):
        first, second = self.open(), self.open()
        first.add_note(0, 80, 80, "First window")
        second.add_note(0, 80, 80, "Second window")
        first.save_annotations()
        saved = self.sidecar.read_bytes()
        with self.assertRaisesRegex(ValueError, "Another window"):
            second.save_annotations()
        self.assertTrue(second.annotations_dirty)
        self.assertEqual(self.sidecar.read_bytes(), saved)

    def test_failed_atomic_save_keeps_previous_file_and_pending_changes(self):
        doc = self.open()
        doc.add_note(0, 80, 80, "Saved")
        doc.save_annotations()
        saved = self.sidecar.read_bytes()
        doc.add_note(0, 90, 90, "Pending")
        with patch("pdfeditor.annotation_store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                doc.save_annotations()
        self.assertTrue(doc.annotations_dirty)
        self.assertEqual(self.sidecar.read_bytes(), saved)
        self.assertEqual(list(self.source.parent.glob("*.tmp")), [])
        self.assertFalse(Path(str(self.sidecar) + ".lock").exists())
        doc.save_annotations()
        self.assertFalse(doc.annotations_dirty)

    def test_corrupt_or_foreign_sidecar_is_preserved_and_viewing_stays_available(self):
        for raw in (b"not json", b'{"format":"unknown"}',
                    b'{"format":"spdf-annotations","version":1,"source_sha256":"other"}'):
            self.sidecar.write_bytes(raw)
            doc = self.open()
            self.assertIsNotNone(doc.annotation_error)
            self.assertFalse(doc.annotations_enabled)
            self.assertTrue(doc.words(0))
            self.assertEqual(len(doc.annots(0)), 1)
            with self.assertRaises(PermissionError):
                doc.save_annotations()
            self.assertEqual(self.sidecar.read_bytes(), raw)

    def test_changed_original_cannot_receive_old_annotations(self):
        doc = self.open()
        doc.add_note(0, 80, 80, "Pending")
        # Simulate an externally changed source without platform-dependent
        # replacement of a PDF currently open in MuPDF on Windows.
        with patch("pdfeditor.annotation_store._digest", return_value="changed"), \
                patch.object(type(self.source), "stat", return_value=type("Stat", (), {
                    "st_size": -1, "st_mtime_ns": -1, "st_ctime_ns": -1})()):
            with self.assertRaisesRegex(ValueError, "original PDF changed"):
                doc.save_annotations()
        self.assertFalse(self.sidecar.exists())

    def test_protected_pdf_and_disabled_annotations_do_not_write_sidecars(self):
        protected = self.source.with_name("protected.pdf")
        with fitz.open(self.source) as pdf:
            pdf.save(protected, encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw="owner", user_pw="reader", permissions=fitz.PDF_PERM_PRINT)
        doc = Document(str(protected), "reader", read_only=True, annotations_enabled=True)
        self.addCleanup(doc.close)
        self.assertIsNotNone(doc.annotation_error)
        self.assertTrue(doc.render(0, 0.1)[3])
        with self.assertRaises(PermissionError):
            doc.add_note(0, 30, 30, "Private note")
        self.assertFalse(Path(str(protected) + ".spdf-annotations.json").exists())
        editable = self.open(read_only=False, annotations_enabled=False)
        editable.rotate_page(0, 90)
        with self.assertRaises(PermissionError):
            editable.add_note(0, 30, 30, "Disabled")


if __name__ == "__main__":
    unittest.main()
