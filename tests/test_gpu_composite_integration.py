"""Cold retained-scene replay, including backdrop-dependent nested groups."""
import ctypes
import os
import time
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

    def test_repeated_nested_masks_match_fresh_surfaces_after_dpi_changes(self):
        def draw(surface, phase):
            surface.begin_frame(0x80607080)
            surface.begin_composite_mask((4, 4, 60, 60), False, 0)
            surface.fill_rect(8 + phase * 5, 8, 32 + phase * 5, 52,
                              (0x40 + phase * 0x40) << 24 | 0xffffff)
            surface.end_composite_mask()
            surface.begin_composite_group(0, .7, isolated=False)
            surface.begin_composite_group(1, .6)
            surface.fill_rect(4, 12 + phase * 4, 60, 40 + phase * 4,
                              (0xc0ff4020, 0x8040ff20, 0xa04020ff)[phase])
            surface.end_composite_group()
            surface.end_composite_group()
            surface.end_clip_group()
            pixels = surface.read_pixels_bgra(64, 64)
            surface.end_frame()
            return pixels

        for dpi in (96, 144, 96):
            self.surface.resize(64, 64, dpi)
            expected = {}
            for phase in range(3):
                hwnd = self.user32.CreateWindowExW(
                    0, "STATIC", "fresh composite reference", 0, 0, 0, 64, 64,
                    None, None, None, None)
                self.assertTrue(hwnd)
                try:
                    with D2DSurface(hwnd, 64, 64, dpi) as fresh:
                        expected[phase] = draw(fresh, phase)
                finally:
                    self.user32.DestroyWindow(hwnd)
            # Alternate coverage/color/alpha to expose stale scratch pixels.
            for phase in (0, 1, 2, 0, 2, 1):
                with self.subTest(dpi=dpi, phase=phase):
                    self.assertEqual(draw(self.surface, phase), expected[phase])

    def test_nested_captures_preserve_nonuniform_translucent_backdrop(self):
        # A uniform backdrop hides shifted/cropped snapshot copies. Exercise
        # drawable offscreen sources, transparent COPY pixels, fractional crop
        # origins, non-default DPI and the endpoint opacity fast paths together.
        clip = self.surface.create_path([
            ("move", 7.25, 5.75), ("line", 43.75, 7.25),
            ("line", 48.25, 43.75), ("line", 5.75, 48.25), ("close",)])
        try:
            for dpi in (96, 120, 144, 192):
                self.surface.resize(64, 64, dpi)
                self.surface.begin_frame(0)
                self.surface.begin_composite_group(0, 1)
                for y in range(8):
                    for x in range(8):
                        color = ((x * 31 + y * 17) % 256 << 24 |
                                 (x * 37) % 256 << 16 |
                                 (y * 41) % 256 << 8 | (x * 13 + y * 23) % 256)
                        self.surface.fill_rect(x * 8, y * 8, (x + 1) * 8,
                                               (y + 1) * 8, color)
                expected = self.surface.read_pixels_bgra(64, 64)
                for opacity in (0, .7, 1):
                    with self.subTest(dpi=dpi, opacity=opacity):
                        self.surface.begin_clip_group(clip)
                        self.surface.begin_composite_mask((9.25, 11.75, 41.25, 45.75), False, 0)
                        self.surface.fill_rect(0, 0, 64, 64, 0x80ffffff)
                        self.surface.end_composite_mask()
                        self.surface.begin_composite_group(0, opacity, isolated=False)
                        self.surface.end_composite_group()
                        self.surface.end_clip_group()
                        self.surface.end_clip_group()
                        actual = self.surface.read_pixels_bgra(64, 64)
                        self.assertLessEqual(max(abs(a-b) for a,b in zip(actual, expected)), 2)
                self.surface.end_composite_group()
                self.surface.end_frame()
        finally:
            clip.close()

    def test_batched_scratch_overwrites_match_explicit_submission_boundaries(self):
        def draw(fenced):
            self.surface.begin_frame(0x80607080)
            for index in range(12):
                # Equal bitmap sizes deliberately borrow the same scratch
                # resources for different masks/colors within a single frame.
                self.surface.begin_composite_mask((0, 0, 64, 64), False, 0)
                self.surface.fill_rect(0, index * 4, 64, index * 4 + 3,
                                       (0x40 + index * 13) << 24 | 0xffffff)
                self.surface.end_composite_mask()
                self.surface.begin_composite_group(index % 15 + 1, .6)
                self.surface.fill_rect(0, 0, 64, 64,
                                       0xc0000000 | (index * 0x173965) % 0x1000000)
                self.surface.end_composite_group()
                self.surface.end_clip_group()
                if fenced:
                    self.surface.read_pixels_bgra(64, 64)
            pixels = self.surface.read_pixels_bgra(64, 64)
            self.surface.end_frame()
            return pixels

        for dpi in (96, 120, 144):
            self.surface.resize(64, 64, dpi)
            with self.subTest(dpi=dpi):
                expected = draw(True)
                self.assertEqual(draw(False), expected)
                self.assertEqual(draw(False), expected)

    def test_worker_culls_sibling_batches_without_skipping_mask_transitions(self):
        box = self.surface.create_path([
            ("move", 0, 0), ("line", 6, 0), ("line", 6, 6),
            ("line", 0, 6), ("close",)])
        operations = [("composite_mask_begin", (0, 0, 384, 96), False, 0)]
        # Build/apply runs have enough siblings to form independent cull blocks.
        # Some scopes lie wholly outside each tile; others straddle its border.
        for origin in (0, 128, 256):
            for index in range(144):
                matrix = (1, 0, 0, 1, origin + index % 12 * 8, index // 12 * 8)
                operations.append(("path", box, 0x80ffffff, None, 1, matrix, None))
        operations.append(("composite_mask_end", ()))
        for origin in (0, 128, 256):
            for row in range(12):
                operations.append(("composite_push", 1, .7, False, True))
                for column in range(12):
                    matrix = (1, 0, 0, 1, origin + column * 8, row * 8)
                    operations.append(("path", box, 0xc04080c0, None, 1, matrix, None))
                operations.append(("composite_pop", None))
        operations.append(("clip_group_pop", None))
        scene = self.surface.create_scene(384, 128, operations)
        try:
            for dpi in (96, 144):
                self.surface.resize(64, 64, dpi)
                for transform in ((1, 0, 0, 1, 0, 0), (1, 0, 0, 1, -128, 0),
                                  (0, 1, -1, 0, 80, -128),
                                  (1, .25, .125, 1, -128, -24)):
                    with self.subTest(dpi=dpi, transform=transform):
                        self.surface.cancel_sharp()
                        self.surface.begin_frame(0xffffffff)
                        self.surface.draw_scene(scene, transform)
                        expected = self.surface.read_pixels_bgra(64, 64)
                        self.surface.end_frame()
                        self.assertTrue(self.surface.request_sharp_scene(scene, transform))
                        deadline = time.monotonic() + 10
                        while self.surface.sharp_status() in (1, 3) and time.monotonic() < deadline:
                            time.sleep(.005)
                        self.assertEqual(self.surface.sharp_status(), 2)
                        self.surface.begin_frame(0xffffffff)
                        self.assertTrue(self.surface.draw_sharp_scene(scene, transform))
                        actual = self.surface.read_pixels_bgra(64, 64)
                        self.surface.end_frame()
                        error = [abs(a-b) for a,b in zip(actual, expected)]
                        self.assertLessEqual(max(error), 3)
        finally:
            self.surface.cancel_sharp()
            scene.close()
            box.close()

    def test_mask_interpolation_preserves_unorm_intermediate_rounding(self):
        # The legacy graph rounds inside/outside premultiplied RGBA to UNORM8
        # separately. A fused float lerp must preserve those intermediate steps,
        # including colored alpha masks, transparent backdrops and endpoints.
        def center():
            pixels = self.surface.read_pixels_bgra(64, 64)
            return pixels[(32 * 64 + 32) * 4:(32 * 64 + 32) * 4 + 4]

        for dpi in (96, 120, 144):
            self.surface.resize(64, 64, dpi)
            for backdrop_alpha in (0, 128, 255):
                background = backdrop_alpha << 24 | 0x4080c0
                for source_alpha in (0, 85, 192, 255):
                    color = source_alpha << 24 | 0xc04080
                    self.surface.begin_frame(background)
                    backdrop = center()
                    self.surface.fill_rect(0, 0, 64, 64, color)
                    painted = center()
                    self.surface.end_frame()
                    for coverage in (0, 1, 63, 127, 191, 254, 255):
                        with self.subTest(dpi=dpi, backdrop=backdrop_alpha,
                                          source=source_alpha, mask=coverage):
                            self.surface.begin_frame(background)
                            self.surface.begin_composite_mask((0, 0, 64, 64), False, 0)
                            self.surface.fill_rect(0, 0, 64, 64,
                                                   coverage << 24 | 0x206040)
                            self.surface.end_composite_mask()
                            self.surface.fill_rect(0, 0, 64, 64, color)
                            self.surface.end_clip_group()
                            actual = center()
                            self.surface.end_frame()
                            expected = bytes(min(255,
                                round(b * (255-coverage) / 255) +
                                round(r * coverage / 255))
                                for b, r in zip(backdrop, painted))
                            self.assertEqual(actual, expected)

    def test_covering_rectangle_clip_matches_original_capture_with_nested_effects(self):
        fast = self.surface.create_path([
            ("move", -128, -128), ("line", 256, -128), ("line", 256, 256),
            ("line", -128, 256), ("close",)])
        # An extra collinear vertex keeps the identical region on the general
        # path/capture route, providing an independent scheduling reference.
        general = self.surface.create_path([
            ("move", -128, -128), ("line", 64, -128), ("line", 256, -128),
            ("line", 256, 256), ("line", -128, 256), ("close",)])
        hole = self.surface.create_path([
            ("move", -128, -128), ("line", 256, -128), ("line", 256, 256),
            ("line", -128, 256), ("close",),
            ("move", 8, 8), ("line", 48, 8), ("line", 48, 48),
            ("line", 8, 48), ("close",)], even_odd=True)

        def draw(path, transform, knockout):
            self.surface.begin_frame(0)
            self.surface.begin_composite_group(0, 1, knockout=knockout)
            self.surface.fill_rect(0, 0, 64, 64, 0x804080c0)
            self.surface.set_transform(*transform)
            self.surface.begin_clip_group(path)
            self.surface.set_transform(1, 0, 0, 1, 0, 0)
            self.surface.begin_composite_mask((4, 4, 60, 60), False, 0)
            self.surface.fill_rect(0, 0, 64, 64, 0xc0ffffff)
            self.surface.end_composite_mask()
            self.surface.begin_composite_group(1, .6)
            self.surface.fill_rect(0, 0, 64, 64, 0xc0c04080)
            self.surface.end_composite_group()
            self.surface.end_clip_group()
            self.surface.end_clip_group()
            self.surface.set_transform(1, 0, 0, 1, 0, 0)
            self.surface.fill_rect(0, 0, 4, 64, 0x8000ff00)
            self.surface.end_composite_group()
            result = self.surface.read_pixels_bgra(64, 64)
            self.surface.end_frame()
            return result

        try:
            for dpi in (96, 120, 144):
                self.surface.resize(64, 64, dpi)
                for transform in ((1, 0, 0, 1, 0, 0), (0, 1, -1, 0, 64, 0),
                                  (-1, 0, 0, 1, 64, 0), (1, .2, .1, 1, 0, 0)):
                    for knockout in (False, True):
                        with self.subTest(dpi=dpi, transform=transform, knockout=knockout):
                            reference = draw(general, transform, knockout)
                            self.assertEqual(draw(fast, transform, knockout), reference)
                # A large bounding box alone cannot prove full coverage: this
                # even-odd path has a hole that must retain the backdrop.
                actual = draw(hole, (1, 0, 0, 1, 0, 0), False)
                offset = (24 * 64 + 24) * 4
                self.assertEqual(tuple(actual[offset:offset+4]), (96, 64, 32, 128))
        finally:
            for path in (fast, general, hole):
                path.close()
