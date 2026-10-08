import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz

from pdfeditor.core import Document
from pdfeditor import editor_objects


class SaveCleanupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "source.pdf"
        with fitz.open() as pdf:
            pdf.new_page(width=240, height=300).insert_text((20, 40), "Keep visible text")
            pdf.set_metadata({"title": "Private title", "author": "Private author"})
            info = int(pdf.xref_get_key(-1, "Info")[1].split()[0])
            pdf.xref_set_key(info, "PrivateCustomKey", fitz.get_pdf_str("Custom secret"))
            pdf.set_xml_metadata('<x:xmpmeta xmlns:x="adobe:ns:meta/"><secret>Private XMP</secret></x:xmpmeta>')
            pdf[0].add_text_annot((180, 180), "Keep note")
            pdf.embfile_add("keep.txt", b"Keep attachment")
            pdf.save(self.path)
        self.original = self.path.read_bytes()

    def document(self, isolated):
        doc = Document(str(self.path), isolated=isolated)
        self.addCleanup(doc.close)
        editor_objects.create(doc, 0, "rectangle", (30, 80, 100, 120))
        return doc

    def test_options_are_independent_and_preserve_rendered_content(self):
        for isolated in (False, True):
            for metadata, editing in ((False, False), (True, False), (False, True), (True, True)):
                with self.subTest(isolated=isolated, metadata=metadata, editing=editing):
                    doc = self.document(isolated)
                    before = doc._doc[0].get_pixmap().samples
                    target = self.path.with_name(f"copy-{isolated}-{metadata}-{editing}.pdf")
                    doc.save_as(target, remove_metadata=metadata, remove_editing_data=editing)
                    with fitz.open(target) as pdf:
                        self.assertEqual(pdf[0].get_pixmap().samples, before)
                        self.assertEqual(pdf.metadata["author"], "" if metadata else "Private author")
                        self.assertEqual(bool(pdf.get_xml_metadata()), not metadata)
                        self.assertEqual(pdf.xref_get_key(-1, "Info")[0] == "null", metadata)
                        self.assertEqual(pdf.xref_get_key(pdf[0].xref, "SPDFObjects")[0] == "null", editing)
                        self.assertEqual(pdf.embfile_get("keep.txt"), b"Keep attachment")
                        self.assertEqual(next(pdf[0].annots()).info["content"], "Keep note")
                    self.assertEqual(doc._doc.metadata["author"], "" if metadata else "Private author")
                    self.assertEqual(bool(editor_objects.objects(doc, 0)), not editing)
                    # Normal Save must not reintroduce information removed on Save As.
                    doc.save_as(target)
                    with fitz.open(target) as pdf:
                        self.assertEqual(pdf.metadata["author"], "" if metadata else "Private author")
                    self.assertEqual(self.path.read_bytes(), self.original)

    def test_same_path_cleanup_succeeds_without_leaving_temporary_files(self):
        for isolated in (False, True):
            with self.subTest(isolated=isolated):
                self.path.write_bytes(self.original)
                doc = self.document(isolated)
                doc.save_as(self.path, remove_metadata=True, remove_editing_data=True)
                self.assertEqual(doc._doc.metadata["author"], "")
                self.assertEqual(editor_objects.objects(doc, 0), [])
                with fitz.open(self.path) as pdf:
                    self.assertEqual(pdf.get_xml_metadata(), "")
                    self.assertEqual(pdf.xref_get_key(pdf[0].xref, "SPDFObjects")[0], "null")
                self.assertFalse(list(self.path.parent.glob(".leaflet-*.pdf")))
                doc.close()

    def test_destination_failure_preserves_live_information_and_source(self):
        replace = os.replace
        for isolated in (False, True):
            with self.subTest(isolated=isolated):
                doc = self.document(isolated)
                def fail_destination(source, target):
                    if os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(self.path)):
                        raise PermissionError("destination locked")
                    return replace(source, target)
                with patch("pdfeditor.core.os.replace", side_effect=fail_destination):
                    with self.assertRaises(PermissionError):
                        doc.save_as(self.path, remove_metadata=True, remove_editing_data=True)
                self.assertEqual(self.path.read_bytes(), self.original)
                self.assertEqual(doc._doc.metadata["author"], "Private author")
                self.assertTrue(doc._doc.get_xml_metadata())
                self.assertTrue(editor_objects.objects(doc, 0))
                self.assertFalse(list(self.path.parent.glob(".leaflet-*.pdf")))

    def test_encryption_and_password_are_preserved(self):
        protected = self.path.with_name("protected.pdf")
        with fitz.open(self.path) as pdf:
            pdf.save(protected, encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw="owner", user_pw="reader", permissions=fitz.PDF_PERM_MODIFY)
        doc = Document(str(protected), password="owner", isolated=True)
        self.addCleanup(doc.close)
        target = self.path.with_name("clean-encrypted.pdf")
        doc.save_as(target, remove_metadata=True)
        with fitz.open(target) as pdf:
            self.assertTrue(pdf.needs_pass)
            self.assertTrue(pdf.authenticate("reader"))
            self.assertEqual(pdf.metadata["author"], "")
            self.assertEqual(pdf.get_xml_metadata(), "")


class SaveOptionsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_defaults_choices_and_cancellation(self):
        from PyQt5.QtWidgets import QCheckBox, QDialog
        from pdfeditor.save_options import choose_save_options
        def accept(dialog):
            choices = dialog.findChildren(QCheckBox)
            self.assertEqual([box.isChecked() for box in choices], [False, False])
            choices[1].setChecked(True)
            return QDialog.Accepted
        with patch.object(QDialog, "exec_", accept):
            self.assertEqual(choose_save_options(None), (False, True))
        with patch.object(QDialog, "exec_", return_value=QDialog.Rejected):
            self.assertIsNone(choose_save_options(None))
