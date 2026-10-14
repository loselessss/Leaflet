import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz

from pdfeditor.core import Document
from pdfeditor.save_options_core import has_illustrator_editing_data


class IllustratorSaveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def fixture(self, *, indirect_piece=False, indirect_entry=False, suffix=".pdf"):
        path = self.root / ("source" + suffix)
        with fitz.open() as pdf:
            for number in range(3):
                pdf.new_page(width=240, height=300).insert_text(
                    (20, 40), "Page %s" % (number + 1))
            pdf.set_metadata({"title": "Keep title", "creator": "Adobe Illustrator"})
            pdf.embfile_add("keep.txt", b"Keep attachment")
            pdf[0].add_text_annot((180, 180), "Keep note")
            pdf.add_ocg("Keep PDF layer")
            private = pdf.get_new_xref()
            pdf.update_object(private, "<<>>")
            pdf.update_stream(private, b"Original Illustrator artboards 1, 2, 3")
            entry = "<< /LastModified (D:20261014000000) /Private %s 0 R >>" % private
            if indirect_entry:
                entry_ref = pdf.get_new_xref()
                pdf.update_object(entry_ref, entry)
                entry = "%s 0 R" % entry_ref
            piece = "<< /Illustrator %s /OtherApp << /Private (Keep other app) >> >>" % entry
            if indirect_piece:
                piece_ref = pdf.get_new_xref()
                pdf.update_object(piece_ref, piece)
                piece = "%s 0 R" % piece_ref
            for owner in (pdf.pdf_catalog(), pdf[0].xref, pdf[2].xref):
                pdf.xref_set_key(owner, "PieceInfo", piece)
            pdf.save(path)
        return path

    def open(self, path, **options):
        doc = Document(str(path), **options)
        self.addCleanup(doc.close)
        return doc

    def test_page_deletion_strips_direct_and_indirect_data_preserving_pdf_content(self):
        for isolated in (False, True):
            for indirect_piece in (False, True):
                for indirect_entry in (False, True):
                    with self.subTest(isolated=isolated, piece=indirect_piece, entry=indirect_entry):
                        source = self.fixture(indirect_piece=indirect_piece,
                                              indirect_entry=indirect_entry)
                        original = source.read_bytes()
                        doc = self.open(source, isolated=isolated)
                        doc.delete_page(1)
                        before = [page.get_pixmap().samples for page in doc._doc]
                        target = self.root / ("copy-%s-%s-%s.pdf" % (
                            isolated, indirect_piece, indirect_entry))
                        doc.save_as(target)
                        with fitz.open(target) as saved:
                            self.assertEqual(len(saved), 2)
                            self.assertFalse(has_illustrator_editing_data(saved))
                            self.assertEqual([page.get_pixmap().samples for page in saved], before)
                            self.assertEqual(saved.metadata["title"], "Keep title")
                            self.assertEqual(saved.embfile_get("keep.txt"), b"Keep attachment")
                            self.assertEqual(next(saved[0].annots()).info["content"], "Keep note")
                            self.assertTrue(saved.get_ocgs())
                            for owner in (saved.pdf_catalog(), saved[0].xref, saved[1].xref):
                                self.assertEqual(saved.xref_get_key(
                                    owner, "PieceInfo/OtherApp/Private")[1], "Keep other app")
                            self.assertNotIn(b"Original Illustrator artboards", saved.tobytes(deflate=False))
                        self.assertEqual(source.read_bytes(), original)
                        self.assertFalse(has_illustrator_editing_data(doc._doc))
                        doc.close()

    def test_unedited_pdf_copy_keeps_original_illustrator_data(self):
        source = self.fixture(indirect_piece=True, indirect_entry=True)
        doc = self.open(source, isolated=True)
        self.assertFalse(doc._doc.is_dirty)
        target = self.root / "unedited.pdf"
        doc.save_as(target)
        with fitz.open(target) as saved:
            self.assertTrue(has_illustrator_editing_data(saved))

    def test_explicit_compatibility_cleans_even_unedited_copy(self):
        source = self.fixture()
        original = source.read_bytes()
        doc = self.open(source, isolated=True)
        before = [page.get_pixmap().samples for page in doc._doc]
        target = self.root / "compatible.pdf"
        doc.save_as(target, illustrator_compatible=True)
        with fitz.open(target) as saved:
            self.assertFalse(has_illustrator_editing_data(saved))
            self.assertEqual([page.get_pixmap().samples for page in saved], before)
        self.assertEqual(source.read_bytes(), original)

    def test_opt_out_preserves_illustrator_data_independently_of_cleanup(self):
        for isolated in (False, True):
            for same_path in (False, True):
                with self.subTest(isolated=isolated, same_path=same_path):
                    source = self.fixture(indirect_piece=True, indirect_entry=True)
                    doc = self.open(source, isolated=isolated)
                    doc.delete_page(1)
                    before = [page.get_pixmap().samples for page in doc._doc]
                    target = source if same_path else self.root / "preserved.pdf"
                    doc.save_as(target, illustrator_compatible=False, remove_metadata=True)
                    with fitz.open(target) as saved:
                        self.assertEqual(len(saved), 2)
                        self.assertTrue(has_illustrator_editing_data(saved))
                        self.assertEqual(saved.metadata["title"], "")
                        self.assertEqual([page.get_pixmap().samples for page in saved], before)
                    self.assertTrue(has_illustrator_editing_data(doc._doc))
                    doc.save_as(target, illustrator_compatible=True)
                    with fitz.open(target) as saved:
                        self.assertFalse(has_illustrator_editing_data(saved))
                    doc.close()

    def test_reader_compatibility_choice_does_not_change_body_or_permission_policy(self):
        source = self.fixture()
        doc = self.open(source, read_only=True, annotations_enabled=True,
                        annotations_in_pdf=True)
        doc.add_note(1, 70, 100, "Reader note")
        doc.save_reader_pdf(str(source), illustrator_compatible=False)
        with fitz.open(source) as saved:
            self.assertTrue(has_illustrator_editing_data(saved))
            self.assertEqual(next(saved[1].annots()).info["content"], "Reader note")
        doc.save_reader_pdf(str(source), illustrator_compatible=True)
        with fitz.open(source) as saved:
            self.assertFalse(has_illustrator_editing_data(saved))
        with self.assertRaises(PermissionError):
            doc.save_as(self.root / "blocked.pdf", illustrator_compatible=True)

    def test_snapshot_before_save_does_not_forget_modified_pdf_state(self):
        source = self.fixture()
        doc = self.open(source, isolated=True)
        doc.delete_page(1)
        doc.snapshot()
        target = self.root / "after-snapshot.pdf"
        doc.save_as(target)
        with fitz.open(target) as saved:
            self.assertEqual(len(saved), 2)
            self.assertFalse(has_illustrator_editing_data(saved))

    def test_modified_ai_export_preserves_ai_source(self):
        source = self.fixture(suffix=".ai")
        original = source.read_bytes()
        doc = self.open(source, isolated=True)
        doc.delete_pages([1, 2])
        target = self.root / "export.pdf"
        doc.save_as(target)
        with fitz.open(target) as saved:
            self.assertEqual(len(saved), 1)
            self.assertFalse(has_illustrator_editing_data(saved))
        self.assertEqual(source.read_bytes(), original)

    def test_same_path_failure_preserves_pending_data_then_retry_cleans_it(self):
        replace = os.replace
        for isolated in (False, True):
            with self.subTest(isolated=isolated):
                source = self.fixture(indirect_piece=True, indirect_entry=True)
                original = source.read_bytes()
                doc = self.open(source, isolated=isolated)
                doc.delete_page(1)
                def fail_destination(temporary, target):
                    if os.path.abspath(target) == os.path.abspath(source):
                        raise PermissionError("locked destination")
                    return replace(temporary, target)
                with patch("pdfeditor.core.os.replace", side_effect=fail_destination):
                    with self.assertRaises(PermissionError):
                        doc.save_as(source)
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(doc.page_count, 2)
                self.assertTrue(has_illustrator_editing_data(doc._doc))
                doc.save_as(source)
                with fitz.open(source) as saved:
                    self.assertEqual(len(saved), 2)
                    self.assertFalse(has_illustrator_editing_data(saved))
                doc.close()

    def test_restored_and_transferred_edits_cannot_resurrect_original_artboards(self):
        source = self.fixture()
        doc = self.open(source, isolated=True)
        doc.delete_page(1)
        edited_snapshot = doc.snapshot()
        doc.delete_page(1)
        doc.restore(edited_snapshot)
        self.assertFalse(doc._doc.is_dirty)
        target = self.root / "restored.pdf"
        doc.save_as(target)
        transferred = Document.from_snapshot(str(source), edited_snapshot)
        self.addCleanup(transferred.close)
        transferred.save_as(self.root / "transferred.pdf")
        for path in (target, self.root / "transferred.pdf"):
            with fitz.open(path) as saved:
                self.assertEqual(len(saved), 2)
                self.assertFalse(has_illustrator_editing_data(saved))

    def test_reader_annotation_save_and_undo_remove_stale_illustrator_data(self):
        source = self.fixture()
        doc = self.open(source, read_only=True, annotations_enabled=True,
                        annotations_in_pdf=True)
        doc.add_note(1, 70, 100, "Reader note")
        doc.save_reader_pdf(str(source))
        with fitz.open(source) as saved:
            self.assertFalse(has_illustrator_editing_data(saved))
            self.assertEqual(next(saved[1].annots()).info["content"], "Reader note")
        doc.step_annotation_history()
        self.assertFalse(doc._doc.is_dirty)
        doc.save_reader_pdf(str(source))
        with fitz.open(source) as saved:
            self.assertFalse(has_illustrator_editing_data(saved))
            self.assertIsNone(saved[1].first_annot)

    def test_sidecar_export_strips_stale_data_without_changing_source(self):
        source = self.fixture()
        original = source.read_bytes()
        doc = self.open(source, read_only=True, annotations_enabled=True)
        doc.add_note(1, 70, 100, "Export note")
        target = self.root / "annotated.pdf"
        doc.export_annotated_pdf(target)
        with fitz.open(target) as saved:
            self.assertFalse(has_illustrator_editing_data(saved))
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue(has_illustrator_editing_data(doc._doc))

    def test_sidecar_export_can_preserve_illustrator_data(self):
        source = self.fixture()
        original = source.read_bytes()
        doc = self.open(source, read_only=True, annotations_enabled=True)
        doc.add_note(1, 70, 100, "Export note")
        target = self.root / "preserved-annotation.pdf"
        doc.export_annotated_pdf(target, illustrator_compatible=False)
        with fitz.open(target) as saved:
            self.assertTrue(has_illustrator_editing_data(saved))
            self.assertEqual(next(saved[1].annots()).info["content"], "Export note")
        self.assertEqual(source.read_bytes(), original)

    def test_encrypted_pdf_keeps_passwords_and_permissions(self):
        source = self.fixture()
        protected = self.root / "protected.pdf"
        with fitz.open(source) as pdf:
            pdf.save(protected, encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw="owner", user_pw="reader", permissions=fitz.PDF_PERM_MODIFY)
        doc = self.open(protected, password="owner", isolated=True)
        doc.delete_page(1)
        doc.save_as(protected)
        with fitz.open(protected) as saved:
            self.assertTrue(saved.needs_pass)
            self.assertTrue(saved.authenticate("reader"))
            self.assertEqual(len(saved), 2)
            self.assertFalse(has_illustrator_editing_data(saved))
            self.assertFalse(saved.permissions & fitz.PDF_PERM_ANNOTATE)
