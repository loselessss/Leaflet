"""Cold retained-scene replay, including backdrop-dependent nested groups."""
import ctypes
import os
import unittest

import pymupdf
from PyQt5.QtWidgets import QApplication

from pdfeditor.d2d_backend import D2DSurface
from pdfeditor.gpu_raster import vector_page_from_pymupdf
from pdfeditor.reader_view import ReaderPageView
from tests.test_gpu_raster import (blended_mask_pdf_bytes,
                                  nonisolated_nested_blend_pdf_bytes)


@unittest.skipUnless(os.name == "nt", "Direct2D requires Windows")
class CompositeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.user32 = ctypes.WinDLL("user32", use_last_error=True)
        cls.user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        cls.user32.CreateWindowExW.restype = ctypes.c_void_p
        cls.user32.DestroyWindow.argtypes = [ctypes.c_void_p]

    def setUp(self):
        self.hwnd = self.user32.CreateWindowExW(
            0, "STATIC", "composite test", 0, 0, 0, 64, 64,
            None, None, None, None)
        self.assertTrue(self.hwnd)
        self.view = ReaderPageView(use_opengl=False)
        self.surface = D2DSurface(self.hwnd, 64, 64)
        self.view._d2d_surface = self.surface
        self.view._page_sizes = {0: (300, 240)}

    def tearDown(self):
        self.view._release_d2d_surface()
        self.view.close()
        self.view.deleteLater()
        self.user32.DestroyWindow(self.hwnd)
        self.app.processEvents()

    def check_retained(self, data):
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
            self.assertTrue(scene.supported, scene.reason)
            self.assertNotIn("cpu-island", scene.features)
            reference = pdf[0].get_pixmap(matrix=pymupdf.Matrix(.2, .2))
            self.view._native_vector_draws(0, scene)
            retained = self.view._d2d_vector_paths[0][3]
            for _ in range(2):  # Both initial replay and cached replay.
                self.surface.begin_frame(0xffffffff)
                self.surface.draw_scene(retained, (.2, 0, 0, .2, 0, 0))
                actual = self.surface.read_pixels_bgra(64, 64)
                self.surface.end_frame()
                for x, y in ((2, 2), (10, 20), (25, 25), (50, 10), (35, 30), (50, 40)):
                    offset = (y * 64 + x) * 4
                    rgb = tuple(reversed(actual[offset:offset + 3]))
                    expected = reference.pixel(x, y)
                    self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(rgb, expected)),
                                    (x, y, rgb, expected))

    def test_cold_retained_luminosity_mask_prepares_color_table(self):
        self.assertFalse(hasattr(self.surface, "_luminosity_profile"))
        self.check_retained(blended_mask_pdf_bytes(image=True))
        self.assertTrue(hasattr(self.surface, "_luminosity_profile"))

    def test_retained_nonisolated_group_with_nested_blend(self):
        self.check_retained(nonisolated_nested_blend_pdf_bytes(0.7, True))

    def test_nonisolated_group_interpolates_premultiplied_alpha_once(self):
        for backdrop_alpha in (0, 128, 255):
            for opacity in (0, .3, .7, 1):
                with self.subTest(alpha=backdrop_alpha, opacity=opacity):
                    self.surface.begin_frame(0x00000000)
                    self.surface.fill_rect(0, 0, 64, 64, (backdrop_alpha << 24) | 0x4080c0)
                    self.surface.begin_composite_group(0, opacity, isolated=False)
                    self.surface.begin_composite_group(1, .6)
                    self.surface.fill_rect(8, 8, 56, 56, 0xc0c04080)
                    self.surface.end_composite_group()
                    self.surface.end_composite_group()
                    actual = self.surface.read_pixels_bgra(64, 64)
                    self.surface.end_frame()
                    ad, af = backdrop_alpha / 255, 192 / 255 * .6
                    expected = []
                    for cb, cf in zip((192, 128, 64), (128, 64, 192)):
                        cb, cf = cb / 255, cf / 255
                        painted = cb * cf * ad * af + cf * af * (1-ad) + cb * ad * (1-af)
                        expected.append(round(255 * ((1-opacity)*cb*ad + opacity*painted)))
                    expected.append(round(255 * (ad + opacity*af*(1-ad))))
                    offset = (32 * 64 + 32) * 4
                    self.assertTrue(all(abs(a-b) <= 3 for a,b in
                                        zip(actual[offset:offset+4], expected)), expected)
                    outside = tuple(round(c*ad) for c in (192,128,64)) + (backdrop_alpha,)
                    self.assertEqual(tuple(actual[:4]), outside)
