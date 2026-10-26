"""Viewport image storage, coordinate preservation and worker isolation."""
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from pdfeditor.gpu_raster import VectorImage, vector_page_from_pymupdf
from pdfeditor.gpu_viewport import crop_pixmap, image_crop


def image_pdf(rotation=0):
    with pymupdf.open() as doc:
        page = doc.new_page(width=100, height=100)
        pixels = bytearray()
        for y in range(512):
            for x in range(512):
                pixels.extend((x % 256, y % 256, 80, (x+y) % 256))
        pix = pymupdf.Pixmap(pymupdf.csRGB, 512, 512, bytes(pixels), True)
        xref = page.insert_image((0, 0, 100, 100), pixmap=pix)
        mask = int(doc.xref_get_key(xref, "SMask")[1].split()[0])
        for obj in (xref, mask):
            doc.xref_set_key(obj, "Interpolate", "true")
        page.insert_text((5, 80), "Vector text", fontsize=8)
        page.set_rotation(rotation)
        return doc.tobytes()


class ViewportImageTests(unittest.TestCase):
    def test_complex_illustrations_allocate_only_the_visible_part(self):
        from tests.test_gpu_regions import illustration_pdf
        with pymupdf.open(stream=illustration_pdf(), filetype="pdf") as doc:
            full = vector_page_from_pymupdf(doc[0], 16)
            crop = vector_page_from_pymupdf(
                doc[0], 16, viewport=(25, 365, 30, 370))
            outside = vector_page_from_pymupdf(
                doc[0], 16, viewport=(200, 200, 210, 210))
        for scene in (full, crop, outside):
            self.assertTrue(scene.supported, scene.reason)
            self.assertIn("complex-illustration", scene.features)
        cost = lambda scene: sum(len(i.pixels) for i in scene.items
                                 if isinstance(i, VectorImage))
        self.assertLess(cost(crop), cost(full) / 10)
        self.assertLess(cost(outside), 100)
        self.assertEqual(crop.paths, full.paths)

    def test_crop_preserves_source_samples_and_affine_grid(self):
        data = bytes(range(240))
        pix = pymupdf.Pixmap(pymupdf.csRGB, 10, 8, data, False)
        for transform in ((100, 0, 0, 80, 0, 0),
                          (0, 100, -80, 0, 80, 0),
                          (100, 20, 10, 80, 3, 4)):
            region = (35, 30, 45, 40)
            box = image_crop(10, 8, transform, region)
            result, _fraction = crop_pixmap(pix, transform, region)
            x0, y0, x1, y1 = box
            expected = b"".join(data[(y*10+x0)*3:(y*10+x1)*3]
                                for y in range(y0, y1))
            self.assertEqual(result.samples, expected)

    def test_high_zoom_fits_budget_preserves_vectors_and_alpha(self):
        for rotation in (0, 90, 180, 270):
            with pymupdf.open(stream=image_pdf(rotation), filetype="pdf") as doc:
                full = vector_page_from_pymupdf(doc[0], 8)
                with patch("pdfeditor.gpu_raster.MAX_GPU_IMAGE_BYTES", 100_000):
                    rejected = vector_page_from_pymupdf(doc[0], 8)
                    crop = vector_page_from_pymupdf(
                        doc[0], 8, viewport=(40, 40, 50, 50))
                self.assertFalse(rejected.supported)
                self.assertTrue(crop.supported, crop.reason)
                self.assertEqual(crop.viewport, (40, 40, 50, 50))
                self.assertEqual(crop.paths, full.paths)
                self.assertIn("alpha-image-fusion", crop.features)
                self.assertLess(sum(len(i.pixels) for i in crop.items
                                    if isinstance(i, VectorImage)), 20_000)
                original = next(i for i in full.items if isinstance(i, VectorImage))
                clipped = next(i for i in crop.items if isinstance(i, VectorImage))
                x0, y0, x1, y1 = image_crop(
                    original.width, original.height, original.transform, crop.viewport)
                expected = b"".join(original.pixels[
                    y*original.stride+x0*4:y*original.stride+x1*4]
                    for y in range(y0, y1))
                self.assertEqual(clipped.pixels, expected)

    def test_worker_crop_bypasses_full_page_disk_cache(self):
        from pdfeditor.gpu_scene_worker import main
        from pdfeditor.core import Document
        from pdfeditor import scene_disk_cache
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "page.pdf"
            result = Path(directory) / "scene.pickle"
            pdf.write_bytes(image_pdf())
            with patch.object(scene_disk_cache, "load") as load, \
                    patch.object(scene_disk_cache, "save") as save:
                self.assertEqual(main([str(pdf), str(result), "--scale", "8",
                    "--viewport", "40", "40", "50", "50",
                    "--disk-cache-key", "must-not-use"]), 0)
                load.assert_not_called()
                save.assert_not_called()
            scene = pickle.loads(result.read_bytes())
            self.assertTrue(scene.supported, scene.reason)
            doc = Document(str(pdf), read_only=True)
            try:
                self.assertIsNone(doc.install_gpu_vector_page(0, scene))
                self.assertFalse(doc._gpu_vector_cache)
            finally:
                doc.close()


if __name__ == "__main__":
    unittest.main()
