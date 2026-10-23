"""Alpha folding arithmetic, eligibility, bounded storage and real extraction."""
from dataclasses import replace
import unittest
from unittest.mock import patch

import pymupdf

from pdfeditor.gpu_alpha import fuse_alpha_images, refine_alpha_image
from pdfeditor.gpu_raster import (ClipPop, ClipPush, MaskBegin, MaskEnd,
                                 VectorImage, VectorPage, can_refine_images,
                                 refine_page_images, vector_page_from_pymupdf)


def alpha_pdf(rotation=0):
    with pymupdf.open() as doc:
        page = doc.new_page(width=64, height=64)
        pix = pymupdf.Pixmap(pymupdf.csRGB, 2, 2,
                             bytes((20, 40, 80, 255)) * 4, True)
        xref = page.insert_image((8, 8, 56, 56), pixmap=pix)
        mask = int(doc.xref_get_key(xref, "SMask")[1].split()[0])
        doc.update_stream(mask, bytes((0, 64, 128, 255)))
        for obj in (xref, mask):
            doc.xref_set_key(obj, "Interpolate", "true")
        page.insert_text((3, 62), "Vector", fontsize=5)
        page.set_rotation(rotation)
        return doc.tobytes()


class AlphaImageTests(unittest.TestCase):
    def scope(self, width=1, height=1, pixels=bytes((20, 40, 80, 255)),
              alpha=bytes((128, 128, 128, 128))):
        transform = (48, 0, 0, 48, 8, 8)
        mask = VectorImage(alpha, width, height, width*4, transform)
        source = VectorImage(pixels, width, height, width*4, transform,
                             opacity=.37, source_index=7, refresh_key=("image", 7))
        return (MaskBegin((10, 11, 52, 53), False, 0), mask,
                MaskEnd(), source, ClipPop())

    def test_all_alpha_pairs_keep_premultiplied_bgra_and_opacity(self):
        source, mask, expected = bytearray(), bytearray(), bytearray()
        for a in range(256):
            for m in range(256):
                source.extend((a//4, a//2, a, a))
                mask.extend((m, m, m, m))
                expected.extend((c*m+127)//255 for c in (a//4, a//2, a, a))
        items = self.scope(256, 256, bytes(source), bytes(mask))
        out, count, cost = fuse_alpha_images(items)
        self.assertEqual(count, 1)
        self.assertEqual(out[1].pixels, bytes(expected))
        self.assertEqual(items[3].pixels, bytes(source))
        self.assertEqual(out[1].opacity, .37)
        self.assertIsNone(out[1].source_index)
        self.assertIsNone(out[1].refresh_key)
        self.assertEqual(cost, len(expected))
        self.assertIsInstance(out[0], ClipPush)
        self.assertIn(("move", 10, 11), out[0].commands)
        self.assertFalse(can_refine_images(VectorPage(True, items=out)))

    def test_guards_preserve_original_scopes(self):
        items = self.scope()
        changes = ((0, replace(items[0], luminosity=True)),
                   (0, replace(items[0], background_argb=0xff000000)),
                   (0, replace(items[0], area=(0, 0, float("inf"), 4))),
                   (1, replace(items[1], opacity=.5)),
                   (1, replace(items[1], interpolate=False)),
                   (1, replace(items[1], width=2)),
                   (1, replace(items[1], stride=8)),
                   (1, replace(items[1], transform=(1, 0, 0, 1, 0, 0))),
                   (2, MaskEnd((0, 255))))
        for index, item in changes:
            with self.subTest(index=index, item=item):
                changed = items[:index] + (item,) + items[index+1:]
                out, count, _ = fuse_alpha_images(changed)
                self.assertEqual(out, changed)
                self.assertEqual(count, 0)
        # Multiple content operations are not a single-image scope.
        changed = items[:4] + (items[3],) + items[4:]
        self.assertEqual(fuse_alpha_images(changed)[0], changed)

    def test_budget_accounts_for_shared_originals_and_cumulative_creation(self):
        items = self.scope() * 3  # Two original buffers shared three times.
        out, count, cost = fuse_alpha_images(items, byte_limit=12)
        self.assertEqual(count, 1)
        self.assertEqual(cost, 12)
        self.assertEqual(len(out), 13)
        self.assertEqual(fuse_alpha_images(items, byte_limit=7)[1], 0)

    def test_conversion_failure_and_timeout(self):
        items = self.scope()
        with patch("pdfeditor.gpu_alpha._combine", side_effect=RuntimeError("decode")):
            self.assertEqual(fuse_alpha_images(items)[0], items)
        with self.assertRaises(TimeoutError):
            fuse_alpha_images(items, abort=lambda: True)
        with self.assertRaises(TimeoutError):
            fuse_alpha_images(items, abort=iter((False, True)).__next__)

    def test_refinement_requires_both_matching_source_callbacks(self):
        from pdfeditor.gpu_raster import _valid_refresh_key
        items = self.scope()
        mask = replace(items[1], refresh_key=("mask", 2))
        items = (items[0], mask, *items[2:])
        fused = fuse_alpha_images(items)[0][1]
        self.assertEqual(fused.refresh_key, ("alpha", (("mask", 2), ("image", 7))))
        self.assertTrue(_valid_refresh_key(fused.refresh_key))
        replacements = {mask.refresh_key: mask, items[3].refresh_key: items[3]}
        self.assertEqual(refine_alpha_image(fused, replacements), fused)
        self.assertIsNone(refine_alpha_image(fused, {}))
        replacements[mask.refresh_key] = replace(mask, interpolate=False)
        self.assertIsNone(refine_alpha_image(fused, replacements))
        for invalid in (("alpha", ()), ("alpha", (("mask", -1), ("image", 7))),
                        ("alpha", (("alpha", ()), ("image", 7)))):
            self.assertFalse(_valid_refresh_key(invalid))

    def test_real_pdf_extraction_disk_roundtrip_and_zoom(self):
        from pdfeditor import scene_disk_cache as cache
        for rotation in (0, 90):
            with self.subTest(rotation=rotation), pymupdf.open(
                    stream=alpha_pdf(rotation), filetype="pdf") as doc:
                baseline = vector_page_from_pymupdf(doc[0], fuse_alpha=False)
                scene = vector_page_from_pymupdf(doc[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertIn("alpha-image-fusion", scene.features)
                self.assertTrue(any(isinstance(x, MaskBegin) for x in baseline.items))
                self.assertFalse(any(isinstance(x, MaskBegin) for x in scene.items))
                self.assertIn("text", scene.features)
                self.assertTrue(can_refine_images(scene))
                encoded = cache._encode(scene)
                self.assertEqual(cache._decode(encoded, cache._types()), scene)
                zoom = vector_page_from_pymupdf(doc[0], raster_scale=2)
                self.assertTrue(zoom.supported, zoom.reason)
                self.assertIn("alpha-image-fusion", zoom.features)
                refined = refine_page_images(doc[0], scene, 2)
                self.assertIsNotNone(refined)
                self.assertEqual(refined.items, zoom.items)


if __name__ == "__main__":
    unittest.main()
