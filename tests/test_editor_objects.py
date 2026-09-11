import tempfile
import unittest
from pathlib import Path

import fitz

from pdfeditor.core import Document
from pdfeditor import editor_objects as objects


class EditorObjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "objects.pdf"
        with fitz.open() as pdf:
            page = pdf.new_page(width=400, height=500)
            page.insert_text((30, 40), "Original text")
            pdf.save(self.path)
        self.original = self.path.read_bytes()
        self.doc = Document(str(self.path))

    def tearDown(self):
        self.doc.close()
        self.directory.cleanup()

    def test_rectangle_transform_save_reopen(self):
        identity = objects.create(self.doc, 0, "rectangle", (50, 70, 150, 120))
        objects.transform(self.doc, 0, identity, (100, 180, 250, 280))
        self.assertEqual(list(self.doc._doc[0].get_drawings()[-1]["rect"]), [100, 180, 250, 280])
        output = Path(self.directory.name) / "saved.pdf"
        self.doc.save_as(str(output))
        reopened = Document(str(output))
        try:
            self.assertEqual(objects.objects(reopened, 0)[0]["id"], identity)
            objects.transform(reopened, 0, identity, (30, 80, 130, 180))
            self.assertEqual(list(reopened._doc[0].get_drawings()[-1]["rect"]), [30, 80, 130, 180])
            self.assertIn("Original text", reopened._doc[0].get_text())
        finally:
            reopened.close()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_crop_and_rotations(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                before = self.doc.snapshot()
                page = self.doc._doc[0]
                page.set_cropbox(fitz.Rect(20, 30, 380, 470))
                page.set_rotation(rotation)
                identity = objects.create(self.doc, 0, "rectangle", (50, 70, 150, 120))
                objects.transform(self.doc, 0, identity, (100, 180, 250, 280))
                actual = self.doc._doc[0].get_drawings()[-1]["rect"]
                for a, b in zip(actual, (100, 180, 250, 280)):
                    self.assertAlmostEqual(a, b, places=3)
                self.doc.restore(before)

    def test_image_transform_and_save(self):
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 10), False)
        pixmap.clear_with(100)
        identity = objects.create(self.doc, 0, "image", (30, 60, 130, 110), image=pixmap.tobytes("png"))
        objects.transform(self.doc, 0, identity, (80, 90, 280, 190))
        actual = self.doc._doc[0].get_image_info()[0]["bbox"]
        for a, b in zip(actual, (80, 90, 280, 190)):
            self.assertAlmostEqual(a, b, places=3)
        output = Path(self.directory.name) / "image.pdf"
        self.doc.save_as(str(output))
        reopened = Document(str(output))
        try:
            self.assertEqual(objects.objects(reopened, 0)[0]["id"], identity)
            self.assertEqual(len(reopened._doc[0].get_image_info()), 1)
        finally:
            reopened.close()

    def test_snapshot_delete_restore(self):
        identity = objects.create(self.doc, 0, "rectangle", (50, 70, 150, 120))
        before = self.doc.snapshot()
        objects.delete(self.doc, 0, identity)
        self.assertEqual(objects.objects(self.doc, 0), [])
        self.assertEqual(self.doc._doc[0].get_drawings(), [])
        self.doc.restore(before)
        self.assertEqual(objects.objects(self.doc, 0)[0]["id"], identity)

    def test_invalid_transform_does_not_mutate(self):
        identity = objects.create(self.doc, 0, "rectangle", (50, 70, 150, 120))
        before = self.doc._doc.xref_stream(objects.objects(self.doc, 0)[0]["content"])
        for rect in ((0, 0, 0, 10), (0, 0, float("nan"), 5), (0, 0, 5, float("inf"))):
            with self.assertRaises(ValueError):
                objects.transform(self.doc, 0, identity, rect)
        self.assertEqual(self.doc._doc.xref_stream(objects.objects(self.doc, 0)[0]["content"]), before)

    def test_foreign_stream_change_disables_editing(self):
        identity = objects.create(self.doc, 0, "rectangle", (50, 70, 150, 120))
        item = objects.objects(self.doc, 0)[0]
        self.doc._doc.update_stream(item["content"], b"q Q")
        self.assertEqual(objects.objects(self.doc, 0), [])
        with self.assertRaises(ValueError):
            objects.transform(self.doc, 0, identity, (20, 30, 80, 90))

    def test_read_only_rejects_model_mutation(self):
        readonly = Document(str(self.path), read_only=True)
        try:
            with self.assertRaises(PermissionError):
                objects.create(readonly, 0, "rectangle", (10, 20, 30, 40))
        finally:
            readonly.close()

    def test_changed_page_box_disables_stale_objects(self):
        objects.create(self.doc, 0, "rectangle", (50, 70, 150, 120))
        self.doc._doc[0].set_cropbox(fitz.Rect(10, 20, 390, 490))
        self.assertEqual(objects.objects(self.doc, 0), [])

    def test_same_path_save_and_second_object(self):
        first = objects.create(self.doc, 0, "rectangle", (50, 70, 150, 120))
        second = objects.create(self.doc, 0, "rectangle", (80, 90, 180, 140))
        self.doc.save_as(str(self.path), backup=False)
        objects.transform(self.doc, 0, first, (100, 180, 250, 280))
        self.assertEqual([x["id"] for x in objects.objects(self.doc, 0)], [first, second])
        self.assertEqual(list(self.doc._doc[0].get_drawings()[1]["rect"]), [80, 90, 180, 140])
