import ctypes
import os
import unittest

import numpy as np
import pymupdf

from tests.gpu_support_fixtures import cases
from pdfeditor.mupdf_path import compile_page
from pdfeditor.rust_scene_compiler import compile_vector_page


class ExtendedCompilerTests(unittest.TestCase):
    def test_independent_blend_source_needs_no_backdrop_alpha_pass(self):
        from tests.test_gpu_raster import nonisolated_masked_image_pdf_bytes
        for mode in ('Multiply', 'Screen', 'Overlay', 'Color', 'Luminosity'):
            with self.subTest(mode=mode), pymupdf.open(
                    stream=nonisolated_masked_image_pdf_bytes(mode), filetype='pdf') as document:
                scene = compile_page(document[0])
                self.assertNotIn('gpu-backdrop', scene.features)
                self.assertNotIn('cpu-island', scene.features)

    def test_supported_cases_keep_gpu_and_bound_pixel_resources(self):
        for name, data in cases().items():
            with self.subTest(name=name), pymupdf.open(stream=data, filetype="pdf") as document:
                compiled = compile_page(document[0])
                features = set(compiled.features)
                self.assertLessEqual(compiled.image_bytes, 64 * 1024 * 1024)
                self.assertFalse(features & {"text-raster-fallback", "raster-pattern",
                    "raster-shading", "clip-mask", "alpha-image-fusion", "cpu-island"}, features)
                if name == "CMYK opacity":
                    self.assertIn("rgb-transparency-approximation", features)
                if name == "Backdrop blend":
                    self.assertIn("gpu-backdrop", features)
                if name.startswith("Mesh"):
                    self.assertIn("vector-mesh", features)
                if "mask" in name.lower():
                    self.assertIn("gpu-mask", features)

    def test_high_zoom_does_not_allocate_shading_pattern_or_mask_bitmaps(self):
        selected = {name: data for name, data in cases().items()
                    if name.startswith(("Mesh", "Type3")) or name in ("Pattern", "Soft mask", "Hairline dash")}
        for name, data in selected.items():
            with self.subTest(name=name), pymupdf.open(stream=data, filetype="pdf") as document:
                scene = compile_page(document[0], 32.)
                self.assertLessEqual(scene.image_bytes, 64 * 1024 * 1024)
                if name != "Type3 bitmap":
                    self.assertEqual(scene.image_bytes, 0)


@unittest.skipUnless(os.name == "nt", "Windows GPU renderer")
class ExtendedPixelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_extended_gpu_pixels_match_cpu_reference(self):
        from PIL import Image
        from pdfeditor.d2d_backend import D2DSurface
        from tests.benchmark_gpu_pipeline import render_sample
        user32 = ctypes.WinDLL("user32")
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32, *([ctypes.c_int] * 4), *([ctypes.c_void_p] * 4)]
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        width, height = 600, 480
        handle = user32.CreateWindowExW(0, "STATIC", "Extended GPU test", 0, 0, 0,
                                       width, height, None, None, None, None)
        surface = D2DSurface(handle, width, height)
        try:
            for name, data in cases().items():
                with self.subTest(name=name), pymupdf.open(stream=data, filetype="pdf") as document:
                    page = document[0]
                    scene = compile_vector_page(page)
                    self.assertTrue(scene.supported, scene.reason)
                    retained = surface.create_rust_scene(scene, page.rect.width, page.rect.height)
                    try:
                        frame = render_sample(surface, retained, (2., 0., 0., 2., 0., 0.),
                                              width, height, "completed", .001)[3]
                    finally:
                        retained.close()
                    actual = np.frombuffer(frame, dtype=np.uint8).reshape(height, width, 4)[:, :, :3][:, :, ::-1]
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    reference = Image.new("RGB", (width, height), "white")
                    reference.paste(Image.frombytes("RGB", (pix.width, pix.height), pix.samples), (0, 0))
                    expected = np.array(reference)
                    self.assertGreater(np.count_nonzero((expected < 245).any(axis=2)), 50)
                    delta = np.abs(actual.astype(int) - expected.astype(int))
                    self.assertLess(float(delta.mean()), 3.0, (name, float(delta.mean())))
                    stable = np.ones((height-4, width-4), bool)
                    center = expected[2:-2, 2:-2]
                    for y in range(5):
                        for x in range(5):
                            stable &= (expected[y:y+height-4, x:x+width-4] == center).all(axis=2)
                    bad = (delta[2:-2, 2:-2][stable] > 4).any(axis=1)
                    self.assertLess(np.count_nonzero(bad), max(20, np.count_nonzero(stable)*.001), name)
        finally:
            surface.close()
            user32.DestroyWindow(handle)

    def test_high_zoom_cropped_masks_and_effects_keep_valid_gpu_state(self):
        from PIL import Image
        from pdfeditor.d2d_backend import D2DSurface
        from tests.benchmark_gpu_pipeline import render_sample
        user32 = ctypes.WinDLL('user32')
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p,
            ctypes.c_wchar_p, ctypes.c_uint32, *([ctypes.c_int] * 4), *([ctypes.c_void_p] * 4)]
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        width, height, scale = 600, 480, 32.
        handle = user32.CreateWindowExW(0, 'STATIC', 'Cropped GPU test', 0,
                                      0, 0, width, height, None, None, None, None)
        surface = D2DSurface(handle, width, height)
        try:
            selected = cases()
            for name in ('Backdrop blend', 'Hairline dash', 'Type3 translucent',
                         'Mesh 6', 'Pattern', 'Soft mask', 'Blend mask', 'Image mask'):
                for corner in (False, True):
                    with self.subTest(name=name, corner=corner), \
                            pymupdf.open(stream=selected[name], filetype='pdf') as document:
                        page = document[0]
                        left = 0 if corner else (page.rect.width-width/scale)/2
                        top = 0 if corner else (page.rect.height-height/scale)/2
                        if name == 'Hairline dash' and not corner:
                            left, top = 100-width/scale/2, 30-height/scale/2
                        clip = pymupdf.Rect(left, top, left+width/scale, top+height/scale)
                        scene = compile_vector_page(page, scale, viewport=tuple(clip))
                        self.assertTrue(scene.supported, scene.reason)
                        retained = surface.create_rust_scene(scene, page.rect.width, page.rect.height)
                        try:
                            frame = render_sample(surface, retained,
                                (scale, 0., 0., scale, -left*scale, -top*scale),
                                width, height, 'completed', .001)[3]
                        finally:
                            retained.close()
                        actual = np.frombuffer(frame, np.uint8).reshape(height, width, 4)[:, :, :3][:, :, ::-1]
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
                        reference = Image.new('RGB', (width, height), 'white')
                        reference.paste(Image.frombytes('RGB', (pix.width, pix.height), pix.samples),
                                        (round(pix.x-left*scale), round(pix.y-top*scale)))
                        self.assertLess(float(np.abs(actual.astype(int)-np.array(reference).astype(int)).mean()), 6.)
                        if name == 'Hairline dash' and not corner:
                            band = slice(height//2-2, height//2+2)
                            ink = (actual[band].min(axis=(0, 2)) < 200)
                            expected_ink = (np.array(reference)[band].min(axis=(0, 2)) < 200)
                            self.assertGreater(float((ink == expected_ink).mean()), .97)
        finally:
            surface.close()
            user32.DestroyWindow(handle)
