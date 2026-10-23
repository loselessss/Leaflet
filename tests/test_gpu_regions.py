"""Independent illustration compilation, including alpha, state and budgets."""
import pickle
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from pdfeditor.gpu_raster import (
    VectorImage, VectorPath, can_refine_images, refine_page_images,
    vector_page_from_pymupdf,
)


def illustration_pdf(*, operations=150, text=False, image=False, isolated=True,
                     alpha=.5, softmask=False, clip=False, rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((60, 50), "Vector label")
    font = page.get_fonts()[0][0]
    opacity = doc.get_new_xref()
    doc.update_object(opacity, f"<< /Type /ExtGState /ca {alpha} >>")
    image_resources = ""
    if image:
        pix = pymupdf.Pixmap(pymupdf.csRGB, 2, 2, bytes((50, 100, 150)) * 4, False)
        image_xref = page.insert_image(pymupdf.Rect(100, 100, 110, 110), pixmap=pix)
        image_resources = f"/XObject << /Im {image_xref} 0 R >>"
    form = doc.get_new_xref()
    doc.update_object(form,
        "<< /Type /XObject /Subtype /Form /BBox [20 20 40 40] "
        f"/Group << /S /Transparency /I {'true' if isolated else 'false'} /K true /CS /DeviceRGB >> "
        f"/Resources << /ExtGState << /A {opacity} 0 R >> "
        f"/Font << /F {font} 0 R >> {image_resources} >> >>")
    content = b"/A gs 1 0 0 rg\n" + b"20 20 20 20 re f\n" * operations
    if text:
        content += b"BT /F 4 Tf 22 25 Td (Text) Tj ET\n"
    if image:
        content += b"q 10 0 0 10 25 25 cm /Im Do Q\n"
    doc.update_stream(form, content)
    if softmask:
        gs = doc.get_new_xref()
        doc.update_object(gs, f"<< /Type /ExtGState /SMask << /S /Alpha /G {form} 0 R >> >>")
        page_resources = f"<< /ExtGState << /M {gs} 0 R >> >>"
        draw = b"q /M gs 0 1 0 rg 20 20 20 20 re f Q\n"
    else:
        extra = f"/Next {image_xref} 0 R" if image else ""
        page_resources = f"<< /XObject << /Illustration {form} 0 R {extra} >> >>"
        draw = b"q /Illustration Do Q\n"
        if image:
            draw += b"q 10 0 0 10 60 20 cm /Next Do Q\n"
    doc.xref_set_key(page.xref, "Resources", page_resources)
    stream = doc.get_new_xref()
    doc.update_object(stream, "<< >>")
    # Blue behind the illustration, green in front; capture must keep stacking.
    before = b"0 0 1 rg 0 0 400 400 re f\n"
    if clip:
        draw = b"q 20 20 10 20 re W n\n" + draw + b"Q\n"
    doc.update_stream(stream, before + draw + b"0 1 0 rg 30 20 10 10 re f\n")
    doc.xref_set_key(page.xref, "Contents", f"[{stream} 0 R]")
    # Reinsert live text outside the illustration with normal page font resources.
    page = doc.reload_page(page)
    page.insert_text((60, 50), "Vector label")
    page.set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    return data


class ComplexIllustrationTests(unittest.TestCase):
    def scene(self, data=None, **kwargs):
        with pymupdf.open(stream=data or illustration_pdf(), filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0], **kwargs)
        self.assertTrue(scene.supported, scene.reason)
        return scene

    def test_compile_before_expanding_paths_and_preserve_stacking_and_text(self):
        data = illustration_pdf()
        baseline = self.scene(data, simplify_regions=False)
        scene = self.scene(data)
        self.assertIn("complex-illustration", scene.features)
        self.assertNotIn("complex-illustration", baseline.features)
        self.assertLess(len(scene.drawables), len(baseline.drawables))
        index = next(i for i, item in enumerate(scene.items) if isinstance(item, VectorImage))
        self.assertTrue(any(isinstance(x, VectorPath) and x.fill_argb == 0xff0000ff
                            for x in scene.items[:index]))
        self.assertTrue(any(isinstance(x, VectorPath) and x.fill_argb == 0xff00ff00
                            for x in scene.items[index + 1:]))
        self.assertIn("text", scene.features)
        self.assertTrue(any(isinstance(x, VectorPath) and x.fill_argb == 0xff000000
                            for x in scene.items[index + 1:]))

    def test_cpu_source_is_premultiplied_once_and_has_transparent_padding(self):
        scene = self.scene()
        image = next(x for x in scene.items if isinstance(x, VectorImage))
        offset = (image.height // 2 * image.width + image.width // 2) * 4
        b, g, r, a = image.pixels[offset:offset + 4]
        self.assertEqual((b, g), (0, 0))
        self.assertGreater(a, 120)
        self.assertLess(a, 135)
        self.assertEqual(r, a)  # Applying alpha twice would yield about 64.
        self.assertEqual(image.pixels[:4], b"\0" * 4)

    def test_small_nonisolated_and_text_groups_stay_vector(self):
        for kwargs in (dict(operations=4), dict(isolated=False), dict(text=True)):
            with self.subTest(kwargs=kwargs):
                self.assertNotIn("complex-illustration", self.scene(illustration_pdf(**kwargs)).features)

    def test_mask_build_is_protected(self):
        scene = self.scene(illustration_pdf(softmask=True))
        self.assertNotIn("complex-illustration", scene.features)

    def test_budget_rejection_replays_original_group(self):
        with patch("pdfeditor.gpu_regions.MAX_REGION_BYTES", 1):
            scene = self.scene()
        self.assertNotIn("complex-illustration", scene.features)
        self.assertTrue(any(isinstance(x, VectorPath) for x in scene.items))

    def test_raster_rejection_keeps_the_original_scene(self):
        data = illustration_pdf()
        expected = self.scene(data, simplify_regions=False)
        with patch("pdfeditor.gpu_regions.RegionDevice._rasterize", return_value=None):
            actual = self.scene(data)
        self.assertEqual(actual, expected)

    def test_captured_images_keep_later_source_indices_and_disk_roundtrip(self):
        from pdfeditor import scene_disk_cache as disk
        with pymupdf.open(stream=illustration_pdf(image=True), filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
            self.assertTrue(scene.supported, scene.reason)
            images = [x for x in scene.items if isinstance(x, VectorImage)]
            self.assertEqual([x.source_index for x in images], [None, 1])
            payload = disk._encode(scene)
            restored = disk._decode(payload, disk._types(), disk._source_pixels(pdf[0], payload))
            self.assertEqual(restored, scene)

    def test_capture_limit_and_timeout_return_complete_cpu_fallback(self):
        with patch("pdfeditor.gpu_regions.MAX_REGION_OPERATIONS", 10):
            with pymupdf.open(stream=illustration_pdf(), filetype="pdf") as pdf:
                scene = vector_page_from_pymupdf(pdf[0])
            self.assertFalse(scene.supported)
            self.assertIn("operation limit", scene.reason)
        with pymupdf.open(stream=illustration_pdf(), filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0], timeout_seconds=0)
        self.assertFalse(scene.supported)
        self.assertIn("time budget", scene.reason)

    def test_rotation_and_clip_do_not_leave_unbalanced_scopes(self):
        for angle in (0, 90, 180, 270):
            scene = self.scene(illustration_pdf(clip=True, rotation=angle))
            self.assertIn("complex-illustration", scene.features)

    def test_zoom_regenerates_sources_after_original_document_is_closed(self):
        data = illustration_pdf()
        first = self.scene(data)
        first = pickle.loads(pickle.dumps(first))
        self.assertFalse(can_refine_images(first))
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            self.assertIsNone(refine_page_images(pdf[0], first, 2))
            second = vector_page_from_pymupdf(pdf[0], 2)
        a = next(x for x in first.items if isinstance(x, VectorImage))
        b = next(x for x in second.items if isinstance(x, VectorImage))
        self.assertGreater(b.width, a.width)
        self.assertGreater(b.height, a.height)

    def test_worker_transports_compiled_source_without_live_pdf_objects(self):
        from pdfeditor.gpu_scene_worker import main
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "input.pdf", Path(directory) / "scene.pickle"
            source.write_bytes(illustration_pdf())
            self.assertEqual(main([str(source), str(target)]), 0)
            source.unlink()
            scene = pickle.loads(target.read_bytes())
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("complex-illustration", scene.features)
        self.assertTrue(next(x for x in scene.items if isinstance(x, VectorImage)).pixels)


if __name__ == "__main__":
    unittest.main()
