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

    def add_original_images(self):
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 10), False)
        pix.clear_with(100)
        page = self.doc._doc[0]
        xref = page.insert_image(fitz.Rect(50, 70, 150, 120), stream=pix.tobytes("png"))
        page.insert_image(fitz.Rect(200, 70, 300, 120), xref=xref)
        return xref

    def assert_image_box(self, actual, expected):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=3)

    def test_existing_image_moves_only_selected_placement_and_reopens(self):
        xref = self.add_original_images()
        source = self.doc._doc.xref_stream(xref)
        items = objects.objects(self.doc, 0)
        self.assertEqual(len(items), 2)
        identity = objects.transform(self.doc, 0, items[0]["id"], (80, 180, 280, 280))
        objects.transform(self.doc, 0, identity, (30, 160, 130, 210))
        actual = self.doc._doc[0].get_image_info()
        self.assert_image_box(actual[0]["bbox"], (30, 160, 130, 210))
        self.assertEqual(actual[1]["bbox"], (200, 70, 300, 120))
        self.assertEqual(self.doc._doc.xref_stream(xref), source)
        self.assertIn("Original text", self.doc._doc[0].get_text())
        output = Path(self.directory.name) / "existing.pdf"
        self.doc.save_as(str(output))
        with fitz.open(output) as pdf:
            self.assert_image_box(pdf[0].get_image_info()[0]["bbox"], (30, 160, 130, 210))
        reopened = Document(str(output))
        try:
            items = objects.objects(reopened, 0)
            self.assertEqual(len(items), 2)
            objects.transform(reopened, 0, items[0]["id"], (60, 160, 160, 210))
            self.assert_image_box(reopened._doc[0].get_image_info()[0]["bbox"], (60, 160, 160, 210))
        finally:
            reopened.close()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_existing_image_shared_content_is_copied_before_edit(self):
        self.add_original_images()
        pdf = self.doc._doc
        contents = pdf[0].get_contents()
        resources = pdf.xref_get_key(pdf[0].xref, "Resources")[1]
        other = pdf.new_page(width=400, height=500)
        pdf.xref_set_key(other.xref, "Resources", resources)
        pdf.xref_set_key(other.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in contents) + "]")
        original_streams = [pdf.xref_stream(x) for x in contents]
        item = objects.objects(self.doc, 0)[0]
        objects.transform(self.doc, 0, item["id"], (80, 180, 280, 280))
        self.assertEqual(pdf[1].get_image_info()[0]["bbox"], (50, 70, 150, 120))
        self.assertEqual([pdf.xref_stream(x) for x in contents], original_streams)

    def test_existing_image_crop_rotation_and_snapshot_delete_restore(self):
        self.add_original_images()
        before = self.doc.snapshot()
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                self.doc.restore(before)
                page = self.doc._doc[0]
                page.set_cropbox(fitz.Rect(20, 30, 380, 470))
                page.set_rotation(rotation)
                item = objects.objects(self.doc, 0)[0]
                self.assertEqual(item["rect"], list(page.get_image_info()[0]["bbox"]))
                identity = objects.transform(self.doc, 0, item["id"], (60, 180, 260, 280))
                self.assert_image_box(self.doc._doc[0].get_image_info()[0]["bbox"], (60, 180, 260, 280))
                snapshot = self.doc.snapshot()
                objects.delete(self.doc, 0, identity)
                self.assertEqual(len(self.doc._doc[0].get_image_info()), 1)
                self.doc.restore(snapshot)
                self.assertEqual(len(objects.objects(self.doc, 0)), 2)

    def test_existing_images_skip_clipping_inline_bytes_and_fake_string_operators(self):
        self.add_original_images()
        pdf = self.doc._doc
        stream = pdf[0].get_contents()[1]
        data = pdf.xref_stream(stream)
        pdf.update_stream(stream, b"(fake /image Do q cm) Tj\n" + data)
        self.assertEqual(len(objects.objects(self.doc, 0)), 2)
        pdf.update_stream(stream, b"q 0 0 50 50 re W n\n" + data + b" Q")
        self.assertEqual(len(objects.objects(self.doc, 0)), 1)
        pdf.update_stream(stream, b"BI /W 1 /H 1 /BPC 8 /CS /RGB ID abc EI\n" + data)
        self.assertEqual(objects.objects(self.doc, 0), [])

    def test_existing_image_shear_and_graphics_state_across_content_streams(self):
        self.add_original_images()
        pdf = self.doc._doc
        contents = pdf[0].get_contents()
        pdf.update_stream(contents[0], b"q .8 .2 .3 1 0 0 cm\n" + pdf.xref_stream(contents[0]))
        pdf.update_stream(contents[-1], pdf.xref_stream(contents[-1]) + b"\nQ")
        item = objects.objects(self.doc, 0)[0]
        self.assert_image_box(item["rect"], pdf[0].get_image_info()[0]["bbox"])
        other = pdf[0].get_image_info()[1]["bbox"]
        objects.transform(self.doc, 0, item["id"], (60, 180, 260, 280))
        self.assert_image_box(pdf[0].get_image_info()[0]["bbox"], (60, 180, 260, 280))
        self.assert_image_box(pdf[0].get_image_info()[1]["bbox"], other)

    def test_existing_image_and_owned_objects_follow_paint_order(self):
        self.add_original_images()
        identity = objects.create(self.doc, 0, "rectangle", (50, 70, 150, 120))
        self.assertEqual(objects.objects(self.doc, 0)[-1]["id"], identity)

    def test_images_inside_forms_are_not_exposed_as_direct_placements(self):
        self.add_original_images()
        source = fitz.open(stream=self.doc._doc.tobytes(), filetype="pdf")
        try:
            target = self.doc._doc.new_page(width=400, height=500)
            target.show_pdf_page(target.rect, source, 0)
            self.assertEqual(len(target.get_image_info()), 2)
            self.assertEqual(objects.objects(self.doc, 1), [])
        finally:
            source.close()

    def test_existing_image_edit_preserves_pdf_token_boundaries(self):
        self.add_original_images()
        pdf = self.doc._doc
        stream = pdf[0].get_contents()[1]
        data = pdf.xref_stream(stream).replace(b"\n/", b"/")
        pdf.update_stream(stream, data)
        item = objects.objects(self.doc, 0)[0]
        objects.transform(self.doc, 0, item["id"], (60, 180, 260, 280))
        self.assert_image_box(pdf[0].get_image_info()[0]["bbox"], (60, 180, 260, 280))
        self.assertEqual(len(objects.objects(self.doc, 0)), 2)
