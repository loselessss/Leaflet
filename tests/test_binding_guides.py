import tempfile
from pathlib import Path
import unittest
import pymupdf
from pdfeditor.core import Document
from pdfeditor.binding_guides import add_guides


class BindingGuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'source.pdf'
        with pymupdf.open() as pdf:
            for rotation in (0, 90, 180, 270):
                page = pdf.new_page(width=200, height=300)
                page.insert_text((40, 100), 'Original')
                page.set_rotation(rotation)
            pdf.save(self.path)
        self.doc = Document(str(self.path))

    def tearDown(self):
        self.doc.close()
        self.temp.cleanup()

    def test_saved_rotated_guides_use_visible_coordinates_and_selected_pages(self):
        add_guides(self.doc, [0, 1, 3], offset=20, inset=10, mirror=True)
        output = Path(self.temp.name) / 'guides.pdf'
        self.doc.save_as(str(output))
        with pymupdf.open(output) as pdf:
            for index in (0, 1, 3):
                page = pdf[index]
                line = page.get_drawings()[-1]['items'][0]
                start, end = (p * page.rotation_matrix for p in line[1:])
                expected_x = 20 if index % 2 == 0 else page.rect.width-20
                self.assertAlmostEqual(start.x, expected_x)
                self.assertAlmostEqual(end.x, expected_x)
                self.assertAlmostEqual(start.y, 10)
                self.assertAlmostEqual(end.y, page.rect.height-10)
                self.assertIn('Original', page.get_text())
            self.assertFalse(pdf[2].get_drawings())

    def test_invalid_geometry_does_not_partially_modify_pages(self):
        with self.assertRaises(ValueError):
            add_guides(self.doc, [1, 0], offset=250)
        self.assertFalse(self.doc._doc[1].get_drawings())

    def test_read_only_rejects_guides(self):
        self.doc.close()
        self.doc = Document(str(self.path), read_only=True)
        with self.assertRaises(PermissionError):
            add_guides(self.doc, [0])
