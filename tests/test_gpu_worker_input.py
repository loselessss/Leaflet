"""Worker input must retain current pixels and outlive its source window."""
import os
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch

import fitz

from pdfeditor.core import Document
from pdfeditor.gpu_scene_worker import main


class GpuWorkerInputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "source.pdf"
        with fitz.open() as pdf:
            pdf.new_page(width=400, height=500)
            page = pdf.new_page(width=600, height=800)
            page.draw_rect((100, 100, 300, 400), fill=(1, 0, 0))
            page.set_cropbox(fitz.Rect(20, 30, 580, 760))
            page.set_rotation(90)
            pdf.save(self.source)

    def tearDown(self):
        self.directory.cleanup()

    def assert_pixels(self, document, index, target, worker_page):
        expected = document.render(index, 1)
        with fitz.open(target) as pdf:
            pix = pdf[worker_page].get_pixmap(alpha=False)
            self.assertEqual(expected, (pix.width, pix.height, pix.stride, pix.samples))

    def test_private_input_survives_document_close_and_preserves_page(self):
        doc = Document(str(self.source), read_only=True, isolated=True)
        target = self.root / "worker.pdf"
        try:
            page = doc.write_gpu_page_snapshot(1, target)
            self.assertEqual(page, 1)
            self.assertTrue(os.path.samefile(target, doc._snapshot.path))
            self.assert_pixels(doc, 1, target, page)
        finally:
            doc.close()
        result = self.root / "scene.pickle"
        self.assertEqual(main([str(target), str(result), "--page", str(page)]), 0)
        with result.open("rb") as stream:
            scene = pickle.load(stream)
        self.assertTrue(scene.supported)
        self.assertTrue(scene.items)  # Page zero is deliberately empty.

    def test_edited_input_exports_current_page(self):
        doc = Document(str(self.source), isolated=True)
        try:
            doc._doc[1].draw_rect((40, 40, 80, 80), fill=(0, 0, 1))
            target = self.root / "edited.pdf"
            with patch("pdfeditor.core.os.link", side_effect=AssertionError):
                page = doc.write_gpu_page_snapshot(1, target)
            self.assertEqual(page, 0)
            self.assert_pixels(doc, 1, target, page)
        finally:
            doc.close()

    def test_link_failure_falls_back_without_changing_pixels(self):
        doc = Document(str(self.source), read_only=True, isolated=True)
        try:
            target = self.root / "fallback.pdf"
            with patch("pdfeditor.core.os.link", side_effect=OSError("unsupported")):
                page = doc.write_gpu_page_snapshot(1, target)
            self.assertEqual(page, 0)
            self.assert_pixels(doc, 1, target, page)
        finally:
            doc.close()

    def test_restored_edit_does_not_reuse_original_input(self):
        doc = Document(str(self.source), isolated=True)
        try:
            doc._doc[1].draw_rect((40, 40, 80, 80), fill=(0, 1, 0))
            doc.restore(doc.snapshot())
            self.assertFalse(doc._doc.is_dirty)
            target = self.root / "restored.pdf"
            with patch("pdfeditor.core.os.link", side_effect=AssertionError):
                page = doc.write_gpu_page_snapshot(1, target)
            self.assertEqual(page, 0)
            self.assert_pixels(doc, 1, target, page)
        finally:
            doc.close()

    def test_encrypted_input_exports_authenticated_page(self):
        protected = self.root / "protected.pdf"
        with fitz.open(self.source) as pdf:
            pdf.save(protected, encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw="owner", user_pw="reader")
        doc = Document(str(protected), password="reader", read_only=True, isolated=True)
        try:
            target = self.root / "decrypted.pdf"
            with patch("pdfeditor.core.os.link", side_effect=AssertionError):
                page = doc.write_gpu_page_snapshot(1, target)
            self.assertEqual(page, 0)
            self.assert_pixels(doc, 1, target, page)
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
