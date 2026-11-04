import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pymupdf
from pdfeditor.ocr_page_source import PageSource


class OcrPageSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "문서.pdf"
        with pymupdf.open() as doc:
            for rotation in (0, 90):
                page = doc.new_page(width=250, height=180)
                page.draw_rect((20, 20, 120, 100), fill=(.2, .4, .8))
                page.insert_text((25, 60), "OCR transport")
                page.set_rotation(rotation)
            doc.save(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_pixels_match_direct_render_and_child_exits(self):
        with PageSource(dict(path=str(self.path)), 5100) as source:
            with pymupdf.open(self.path) as doc:
                for number in (1, 0):
                    image, zoom = source.read(number)
                    pix = doc[number].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False,
                                                colorspace=pymupdf.csRGB)
                    expected = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                    np.testing.assert_array_equal(image, expected)
        self.assertIsNotNone(source.process.poll())

    def test_password_and_fixed_zoom(self):
        encrypted = self.path.with_name("encrypted.pdf")
        with pymupdf.open(self.path) as doc:
            doc.save(encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                     user_pw="secret", owner_pw="owner")
        with PageSource(dict(path=str(encrypted), password="secret", zoom=2), 5100) as source:
            image, zoom = source.read(0)
            self.assertEqual(zoom, 2)
            self.assertEqual(image.shape, (360, 500, 3))
        with PageSource(dict(path=str(encrypted), password="wrong"), 5100) as source:
            with self.assertRaisesRegex(RuntimeError, "password"):
                source.read(0)

    def test_page_error_and_early_close_cleanup(self):
        with PageSource(dict(path=str(self.path)), 2000) as source:
            with self.assertRaises(RuntimeError):
                source.read(100)
        self.assertIsNotNone(source.process.poll())
        with PageSource(dict(path=str(self.path)), 2000) as source:
            pass
        self.assertIsNotNone(source.process.poll())
