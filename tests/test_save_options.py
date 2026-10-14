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
            self.assertEqual([box.isChecked() for box in choices], [False, False, True])
            choices[1].setChecked(True)
            return QDialog.Accepted
        with patch.object(QDialog, "exec_", accept):
            self.assertEqual(choose_save_options(None), (False, True, True))
        with patch.object(QDialog, "exec_", return_value=QDialog.Rejected):
            self.assertIsNone(choose_save_options(None))

    def test_illustrator_only_dialog_preserves_other_information(self):
        from PyQt5.QtWidgets import QCheckBox, QDialog
        from pdfeditor.save_options import choose_save_options
        def accept(dialog):
            choices = dialog.findChildren(QCheckBox)
            self.assertEqual(len(choices), 1)
            self.assertTrue(choices[0].isChecked())
            choices[0].setChecked(False)
            return QDialog.Accepted
        with patch.object(QDialog, "exec_", accept):
            self.assertEqual(choose_save_options(None, compatibility_only=True), (False, False, False))

    def test_illustrator_option_uses_selected_ui_language(self):
        from PyQt5.QtWidgets import QCheckBox, QDialog
        from pdfeditor.i18n import set_language
        from pdfeditor.save_options import choose_save_options
        try:
            for language, expected in (("en", "Illustrator-compatible save"),
                                       ("ko", "Illustrator 호환 저장")):
                set_language(language)
                def inspect(dialog):
                    choice = dialog.findChild(QCheckBox, "illustratorCompatibleSave")
                    self.assertTrue(choice.text().startswith(expected))
                    return QDialog.Rejected
                with patch.object(QDialog, "exec_", inspect):
                    self.assertIsNone(choose_save_options(None))
        finally:
            set_language("en")


class IllustratorSaveUITests(unittest.TestCase):
    from tests import test_editor_workspace as _fixtures
    setUpClass = classmethod(_fixtures.EditorWorkspaceTests.setUpClass.__func__)
    tearDownClass = classmethod(_fixtures.EditorWorkspaceTests.tearDownClass.__func__)
    setUp = _fixtures.EditorWorkspaceTests.setUp
    tearDown = _fixtures.EditorWorkspaceTests.tearDown
    settle = _fixtures.EditorWorkspaceTests.settle
    open_editor = _fixtures.EditorWorkspaceTests.open_editor

    def add_private_data(self, tab):
        tab.doc._doc.xref_set_key(tab.doc._doc.pdf_catalog(), "PieceInfo",
                                 "<< /Illustrator << /Private (Original AI editing data) >> >>")
        tab.mark_dirty()

    def test_normal_save_cancel_preserves_source_and_pending_information(self):
        from pdfeditor.save_options_core import has_illustrator_editing_data
        tab = self.open_editor()
        self.add_private_data(tab)
        with patch("pdfeditor.annots.choose_save_options", return_value=None) as choice:
            self.assertFalse(tab.save())
        choice.assert_called_once_with(tab, compatibility_only=True)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(tab._dirty)
        self.assertTrue(has_illustrator_editing_data(tab.doc._doc))

    def test_normal_save_respects_opt_out_then_checked_cleanup(self):
        from pdfeditor.save_options_core import has_illustrator_editing_data
        tab = self.open_editor()
        self.add_private_data(tab)
        with patch("pdfeditor.annots.choose_save_options", return_value=(False, False, False)):
            self.assertTrue(tab.save())
        self.assertTrue(has_illustrator_editing_data(tab.doc._doc))
        with patch("pdfeditor.annots.choose_save_options", return_value=(False, False, True)):
            self.assertTrue(tab.save())
        self.assertFalse(has_illustrator_editing_data(tab.doc._doc))

    def test_save_as_forwards_checked_option(self):
        from pdfeditor.save_options_core import has_illustrator_editing_data
        tab = self.open_editor()
        self.add_private_data(tab)
        target = self.path.with_name("compatible-copy.pdf")
        with patch("pdfeditor.annots.QFileDialog.getSaveFileName", return_value=(str(target), "PDF")), \
                patch("pdfeditor.annots.choose_save_options", return_value=(False, False, True)):
            self.assertTrue(tab.save_as_dialog())
        self.assertFalse(has_illustrator_editing_data(tab.doc._doc))
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_reader_shows_compatibility_only_and_respects_opt_out(self):
        from pdfeditor.save_options_core import has_illustrator_editing_data
        window = self.module.new_window(str(self.path), workspace_mode="reader")
        self.settle()
        tab = window._tabs.currentWidget()
        self.add_private_data(tab)
        tab.doc.add_note(0, 100, 100, "Reader note")
        with patch("pdfeditor.annots.choose_save_options", return_value=(False, False, False)) as choice:
            self.assertTrue(tab.save())
        choice.assert_called_once_with(tab, compatibility_only=True)
        self.assertTrue(has_illustrator_editing_data(tab.doc._doc))
        self.assertTrue(tab.read_only)
