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

    def test_compiled_illustration_preserves_alpha_clip_and_foreground(self):
        from itertools import product
        from tests.test_gpu_regions import illustration_pdf

        for dpi, angle, clipped in product((96, 192), (0, 90), (False, True)):
            self.surface.resize(400, 400, dpi)
            with self.subTest(dpi=dpi, rotation=angle, clipped=clipped), pymupdf.open(
                    stream=illustration_pdf(clip=clipped, rotation=angle), filetype="pdf") as pdf:
                page = pdf[0]
                scene = vector_page_from_pymupdf(page)
                self.assertTrue(scene.supported, scene.reason)
                self.assertIn("complex-illustration", scene.features)
                reference = page.get_pixmap(alpha=False)
                self.view._page_sizes = {0: (400, 400)}
                self.view._native_vector_draws(0, scene)
                draws = self.view._d2d_vector_paths[0][1]
                retained = self.surface.create_scene(400, 400, draws)
                try:
                    # This source-over-only scene can use the direct command
                    # list path; request_sharp_scene correctly declines it.
                    self.surface.begin_frame(0xffffffff)
                    scale = 96 / dpi  # Keep the same physical pixels.
                    self.surface.draw_scene(retained, (scale, 0, 0, scale, 0, 0), reuse_groups=False)
                    actual = self.surface.read_pixels_bgra(400, 400)
                    self.surface.end_frame()
                finally:
                    retained.close()
                for px, py in ((10, 10), (25, 365), (25, 375), (35, 365), (35, 375)):
                    point = pymupdf.Point(px, py) * page.rotation_matrix
                    x, y = int(point.x), int(point.y)
                    offset = (y * 400 + x) * 4
                    rgb = tuple(reversed(actual[offset:offset + 3]))
                    expected = reference.pixel(x, y)
                    self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(rgb, expected)),
                                    (clipped, x, y, rgb, expected))

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

    def test_replacing_sharp_jobs_keeps_each_scene_analysis_and_resources_alive(self):
        def make_scene(phase):
            path = self.surface.create_path([
                ("move", 4 + phase, 4), ("line", 58, 8 + phase),
                ("line", 54 - phase, 58), ("line", 6, 54), ("close",)])
            try:
                operations = [
                    ("composite_mask_begin", (0, 0, 64, 64), False, 0),
                    ("path", path, 0xc0ffffff, None, 1, None, None),
                    ("composite_mask_end", ()),
                    ("linear_gradient", path, (0, 0), (64, 64),
                     ((0, (0xc0ff4020, 0x8040ff20, 0xa04020ff)[phase]),
                      (1, 0xff204080)), None),
                    ("clip_group_pop", None),
                ]
                # Different index sizes and culling batches for each identity.
                operations += [("path", path, 0, None, 1, None, None)] * (128 + phase * 65)
                return self.surface.create_scene(64, 64, operations)
            finally:
                path.close()  # Retained resources must own their native data.

        for dpi in (96, 144):
            self.surface.resize(64, 64, dpi)
            for phase in (0, 1, 2, 0):
                with self.subTest(dpi=dpi, phase=phase):
                    retired, current = make_scene((phase + 1) % 3), make_scene(phase)
                    try:
                        transform = (.8, 0, 0, .8, .25, .5)
                        self.surface.begin_frame(0xff123456)
                        self.surface.draw_scene(current, transform)
                        expected = self.surface.read_pixels_bgra(64, 64)
                        self.surface.end_frame()
                        self.assertTrue(self.surface.request_sharp_scene(retired, transform))
                        self.assertTrue(self.surface.request_sharp_scene(current, transform))
                        retired.close()  # Cancelled worker may still own its analysis.
                        deadline = time.monotonic() + 10
                        while self.surface.sharp_status() in (1, 3) and time.monotonic() < deadline:
                            time.sleep(.005)
                        self.assertEqual(self.surface.sharp_status(), 2)
                        self.surface.begin_frame(0xff123456)
                        self.assertTrue(self.surface.draw_sharp_scene(current, transform))
                        actual = self.surface.read_pixels_bgra(64, 64)
                        self.surface.end_frame()
                        self.assertLess(sum(abs(a - b) for a, b in zip(actual, expected)) /
                                        len(actual), .25)
                    finally:
                        retired.close()
                        current.close()
                    self.assertEqual(self.surface.sharp_status(), 0)

    def test_worker_binds_closed_resources_and_keeps_gradient_state_separate(self):
        path = self.surface.create_path([
            ("move", 4, 4), ("line", 60, 4), ("line", 60, 60),
            ("line", 4, 60), ("close",)])
        bitmap = self.surface.create_bitmap_bgra(bytes((20, 80, 160, 192)) * 4, 2, 2)
        style = self.surface.create_stroke_style((1, 1, 1, 2, 10, .5, (1.5, .75)))
        stops = [(0, 0x804020ff), (.4, 0xc0ff4020), (1, 0xff20c080)]
        transfer = [0, .2, .8, 1]
        try:
            scene = self.surface.create_scene(64, 64, (
                ("composite_mask_begin", (0, 0, 64, 64), False, 0),
                ("linear_gradient", path, (0, 0), (64, 64), stops, None),
                ("composite_mask_end", transfer),
                ("radial_gradient", path, (32, 32), (3, -2), (30, 26), stops, None),
                ("image", bitmap, .7, (20, 0, 0, 20, 20, 20), True),
                ("path", path, None, 0xff204080, 2, None, style),
                ("clip_group_pop", None)))
        finally:
            path.close()
            bitmap.close()
            style.close()
        # Worker binding happens after submission, when original handles and
        # Python tables may already be gone. The retained scene must own both.
        stops[:] = [(0, 0), (1, 0)]
        transfer[:] = [0, 0]
        try:
            for dpi in (96, 144):
                self.surface.resize(600, 450, dpi)
                for transform in ((5, 0, 0, 5, 30.25, 20.5),
                                  (0, 5, -5, 0, 370.25, 20.5)):
                    with self.subTest(dpi=dpi, transform=transform):
                        self.surface.begin_frame(0xff123456)
                        self.surface.draw_scene(scene, transform)
                        expected = self.surface.read_pixels_bgra(600, 450)
                        self.surface.end_frame()
                        self.assertTrue(self.surface.request_sharp_scene(scene, transform))
                        # UI and worker must never mutate the same brushes.
                        for scale in (2, 3, 1):
                            self.surface.begin_frame(0xff123456)
                            self.surface.draw_scene(scene, (scale, 0, 0, scale, .5, .25))
                            self.surface.end_frame()
                        deadline = time.monotonic() + 10
                        while self.surface.sharp_status() in (1, 3) and time.monotonic() < deadline:
                            time.sleep(.005)
                        self.assertEqual(self.surface.sharp_status(), 2)
                        self.surface.begin_frame(0xff123456)
                        self.assertTrue(self.surface.draw_sharp_scene(scene, transform))
                        actual = self.surface.read_pixels_bgra(600, 450)
                        self.surface.end_frame()
                        self.assertLess(sum(abs(a - b) for a, b in zip(actual, expected)) /
                                        len(actual), .25)
                        self.surface.cancel_sharp()
        finally:
            scene.close()

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

    def test_tile_plan_keeps_empty_copy_groups_and_nonzero_mask_transfer(self):
        box = self.surface.create_path([
            ("move", 4, 4), ("line", 60, 4), ("line", 60, 60),
            ("line", 4, 60), ("close",)])
        paint = ("path", box, 0xffd04020, None, 1, None, None)
        try:
            for knockout in (False, True):
                operations = [("composite_push", 0, 1, knockout, True), paint,
                              ("composite_push", 0, .7, False, True)]
                for dx in (-200, 200):
                    operations += [("composite_push", 1, .8, False, True),
                        ("path", box, 0xff2040c0, None, 1, (1, 0, 0, 1, dx, 0), None),
                        ("composite_pop", None)]
                operations += [("composite_pop", None), ("composite_pop", None)]
                scene = self.surface.create_scene(64, 64, operations)
                try:
                    expected = self._draw_retained_pixels(scene, (1, 0, 0, 1, 0, 0))
                    actual = self._render_sharp_operations(operations, (1, 0, 0, 1, 0, 0))
                    self.assertEqual(actual, expected, knockout)
                    center = (32 * 64 + 32) * 4
                    self.assertEqual(actual[center:center + 4],
                                     bytes((255, 255, 255, 255)) if knockout else bytes((32, 64, 208, 255)))
                finally:
                    scene.close()
            # No visible mask-building draw. TR(0)=1 still makes content visible.
            operations = [("composite_mask_begin", (0, 0, 320, 64), False, 0),
                ("path", box, 0xffffffff, None, 1, (1, 0, 0, 1, 200, 0), None),
                ("composite_mask_end", (1, 1)), paint, ("clip_group_pop", None)]
            scene = self.surface.create_scene(320, 64, operations)
            try:
                expected = self._draw_retained_pixels(scene, (1, 0, 0, 1, 0, 0))
                actual = self._render_sharp_operations(operations, (1, 0, 0, 1, 0, 0),
                                                       320, 64, read_size=(64, 64))
                self.assertEqual(actual, expected)
                center = (32 * 64 + 32) * 4
                self.assertEqual(actual[center:center + 4], bytes((32, 64, 208, 255)))
            finally:
                scene.close()
        finally:
            box.close()

    def _draw_retained_pixels(self, scene, transform, width=64, height=64):
        self.surface.begin_frame(0)
        self.surface.draw_scene(scene, transform)
        pixels = self.surface.read_pixels_bgra(width, height)
        self.surface.end_frame()
        return pixels

    def test_tile_plan_preserves_nested_origins_and_antialiasing(self):
        triangle = self.surface.create_path([
            ("move", .25, .5), ("line", 55.75, 4.25), ("line", 12.5, 42.75), ("close",)])
        wide = self.surface.create_path([
            ("move", -500, -500), ("line", 2000, -500),
            ("line", 2000, 2000), ("line", -500, 2000), ("close",)])
        operations = [("composite_push", 0, .63, False, True),
            ("path", triangle, 0xc02060a0, None, 1, (1, 0, 0, 1, 80.25, 70.5), None),
            ("composite_push", 0, .57, False, True), ("clip_group_push", wide, None),
            ("composite_push", 5, .75, False, True)]
        for dx, dy in ((95.25, 80.5), (525.25, 290.5), (1400.25, 700.5)):
            operations.append(("path", triangle, 0x90d04080, 0xc040a020, 3,
                               (1, 0, 0, 1, dx, dy), None))
        operations += [("composite_pop", None), ("clip_group_pop", None),
                       ("composite_pop", None), ("composite_pop", None)]
        try:
            for dpi in (96, 144):
                self.surface.resize(1200, 900, dpi)
                for transform in ((1, 0, 0, 1, .25, .5), (0, 1, -1, 0, 800.25, .5),
                                  (1, .15, .1, 1, -50.25, -30.5)):
                    with self.subTest(dpi=dpi, transform=transform):
                        self.surface.cancel_sharp()
                        # An identity mask protects the independent general
                        # capture route. Both sides use the same tile rasterizer.
                        reference = [("composite_mask_begin", (-1000, -1000, 4000, 4000), False, 0),
                            ("path", wide, 0xffffffff, None, 1, None, None),
                            ("composite_mask_end", ())] + operations + [("clip_group_pop", None)]
                        expected = self._render_sharp_operations(reference, transform, 1600, 900,
                                                                 read_size=(1200, 900))
                        actual = self._render_sharp_operations(operations, transform, 1600, 900,
                                                               read_size=(1200, 900))
                        self.assertEqual(len(actual), len(expected))
                        error = [abs(a-b) for a, b in zip(actual, expected)]
                        self.assertLessEqual(max(error), 3)
                        self.assertLess(sum(error) / len(error), .02)
        finally:
            triangle.close()
            wide.close()

    def _render_sharp_operations(self, operations, transform, width=64, height=64, *, read_size=None):
        scene = self.surface.create_scene(width, height, operations)
        try:
            self.assertTrue(self.surface.request_sharp_scene(scene, transform))
            deadline = time.monotonic() + 15
            while self.surface.sharp_status() in (1, 3) and time.monotonic() < deadline:
                time.sleep(.002)
            self.assertEqual(self.surface.sharp_status(), 2)
            self.surface.begin_frame(0)
            self.assertTrue(self.surface.draw_sharp_scene(scene, transform))
            pixels = self.surface.read_pixels_bgra(*(read_size or (width, height)))
            self.surface.end_frame()
            return pixels
        finally:
            self.surface.cancel_sharp()
            scene.close()

    def test_empty_native_layers_preserve_nested_state(self):
        clip = self.surface.create_path([
            ("move", 7.25, 5.75), ("line", 45.75, 8.25),
            ("line", 49.25, 45.75), ("line", 5.75, 49.25), ("close",)])
        paint = self.surface.create_path([
            ("move", 2, 2), ("line", 58, 2), ("line", 58, 58),
            ("line", 2, 58), ("close",)])

        def path(color):
            return ("path", paint, color, None, 1, None, None)

        # These layers contain no draw. Distinct transforms and zero opacity
        # expose a leaked transform or an accidental pop of the enclosing clip.
        empty = [("clip_push", clip, (.8, .2, -.1, 1, 3, 4)),
                 ("clip_pop", None),
                 ("rect_clip_push", None, (1, 0, 0, 1, 17, 9), (0, 0, 3, 5)),
                 ("rect_clip_pop", None),
                 ("group_push", 0), ("clip_push", clip, None),
                 ("clip_pop", None), ("group_pop", None)]
        try:
            for dpi in (96, 144):
                self.surface.resize(64, 64, dpi)
                for context in ("normal", "copy", "nonisolated", "mask"):
                    before = [("composite_push", 0, .73, context == "copy",
                               context != "nonisolated"), path(0x804080c0),
                              ("clip_push", clip, None), path(0x9050c080)]
                    after = [path(0xb0c06030), ("clip_pop", None),
                             path(0x704060c0), ("composite_pop", None)]
                    if context == "mask":
                        before = [("composite_mask_begin", (0, 0, 64, 64), False, 0)] + before
                        after += [("composite_mask_end", tuple(
                            0.0 if index < 128 else 1.0 for index in range(256))),
                                  path(0xffff8020), ("clip_group_pop", None)]
                    for transform in ((1, 0, 0, 1, .25, .5),
                                      (0, 1, -1, 0, 63.25, .5),
                                      (-1, 0, 0, 1, 63.25, .5),
                                      (1, .2, .1, 1, -3.25, -4.5)):
                        with self.subTest(dpi=dpi, context=context, transform=transform):
                            expected = self._render_sharp_operations(before + after, transform)
                            actual = self._render_sharp_operations(before + empty * 8 + after, transform)
                            self.assertEqual(actual, expected)
        finally:
            clip.close()
            paint.close()

    def test_direct_clip_geometry_maps_bitmap_source_across_tiles(self):
        clip = self.surface.create_path([
            ("move", 42.25, 7.5), ("line", 556.75, 12.25),
            ("line", 558.25, 87.75), ("line", 44.25, 93.5), ("close",)])
        paint = self.surface.create_path([
            ("move", 0, 0), ("line", 600, 0), ("line", 600, 100),
            ("line", 0, 100), ("close",)])
        image = self.surface.create_bitmap_bgra(bytes([
            0x20, 0x40, 0xc0, 0xff, 0xc0, 0x80, 0x20, 0xff,
            0x40, 0xa0, 0x60, 0xff, 0xa0, 0x20, 0x80, 0xff]), 2, 2, 8)
        try:
            for dpi in (96, 144):
                self.surface.resize(600, 100, dpi)
                for transform in ((1, 0, 0, 1, .25, .5),
                                  (-1, 0, 0, 1, 599.25, .5),
                                  (1, .025, .1, 1, -3.25, -4.5)):
                    operations = []
                    for phase in range(4):
                        operations += [
                            ("composite_push", 0, .63, False, True),
                            ("clip_group_push", clip, (1, .01, -.02, 1, phase * .25, .5)),
                            ("composite_push", 1, .7, False, True),
                            ("image", image, .83, (600, 0, 0, 100, 0, 0), False),
                            ("composite_pop", None),
                            ("path", paint, 0x404080c0, None, 1, None, None),
                            ("clip_group_pop", None), ("composite_pop", None)]
                    reference = []
                    for operation in operations:
                        reference.append(operation)
                        if operation[0] == "composite_push" and operation[1] == 0:
                            # Keep the independent mask-based composition route.
                            reference.append(("path", paint, 0, None, 1, None, None))
                    with self.subTest(dpi=dpi, transform=transform):
                        expected = self._render_sharp_operations(reference, transform, 600, 100)
                        actual = self._render_sharp_operations(operations, transform, 600, 100)
                        self.assertTrue(any(value != 255 for value in expected))
                        # Four translucent overlaps accumulate UNORM8 rounding.
                        # The old mask-based fusion differs by up to 4 here;
                        # direct coverage adds at most two more channel steps.
                        self.assertLessEqual(max(abs(a-b) for a, b in zip(actual, expected)), 6)
        finally:
            image.close()
            paint.close()
            clip.close()

    def test_isolated_group_clip_fusion_matches_general_worker(self):
        clip = self.surface.create_path([
            ("move", 7.25, 5.75), ("line", 43.75, 7.25),
            ("line", 48.25, 43.75), ("line", 5.75, 48.25), ("close",)])
        outer = self.surface.create_path([
            ("move", -20, -20), ("line", 100, -20),
            ("line", 100, 100), ("line", -20, 100), ("close",)])
        paint = self.surface.create_path([
            ("move", 2, 2), ("line", 58, 2), ("line", 58, 58),
            ("line", 2, 58), ("close",)])
        dot = self.surface.create_path([
            ("move", 0, 0), ("line", 4, 0), ("line", 4, 4),
            ("line", 0, 4), ("close",)])
        wide = self.surface.create_path([
            ("move", -500, -500), ("line", 0, -500), ("line", 500, -500),
            ("line", 500, 500), ("line", -500, 500), ("close",)])
        full_rect = self.surface.create_path([
            ("move", -500, -500), ("line", 500, -500),
            ("line", 500, 500), ("line", -500, 500), ("close",)])

        def path(resource, color):
            return ("path", resource, color, None, 1, None, None)

        def render(operations, transform):
            scene = self.surface.create_scene(64, 64, operations)
            try:
                self.assertTrue(self.surface.request_sharp_scene(scene, transform))
                deadline = time.monotonic() + 15
                while self.surface.sharp_status() in (1, 3) and time.monotonic() < deadline:
                    time.sleep(.002)
                self.assertEqual(self.surface.sharp_status(), 2)
                self.surface.begin_frame(0)
                self.assertTrue(self.surface.draw_sharp_scene(scene, transform))
                pixels = self.surface.read_pixels_bgra(64, 64)
                self.surface.end_frame()
                return pixels
            finally:
                self.surface.cancel_sharp()
                scene.close()

        try:
            for dpi in (96, 144):
                self.surface.resize(64, 64, dpi)
                for opacity in (0, .58, 1):
                    for kind in ("eligible", "copy_parent", "nonisolated", "sibling",
                                 "nested", "knockout_group", "blended_group", "mask_build",
                                 "repeated", "full_rectangle"):
                        operations = [
                            ("composite_push", 0, 1, kind == "copy_parent", True),
                            path(paint, 0x804080c0)]
                        if kind != "copy_parent":
                            operations.append(("clip_group_push", outer, None))
                        target_start = len(operations)
                        operations.append(("composite_push", 5 if kind == "blended_group" else 0,
                                           opacity, kind == "knockout_group", kind != "nonisolated"))
                        if kind == "sibling":
                            operations.append(path(dot, 0xff00a060))
                        child_clip = wide if kind == "repeated" else full_rect if kind == "full_rectangle" else clip
                        operations.append(("clip_group_push", child_clip, None))
                        if kind == "nested":
                            operations.extend((("composite_push", 0, .7, False, True),
                                               ("clip_group_push", clip, (.9, .1, -.05, 1, 2, 3))))
                        operations.extend((
                            ("composite_push", 1, .6, False, True), path(paint, 0xc0c04080),
                            ("composite_pop", None),
                            ("composite_mask_begin", (9, 9, 50, 50), False, 0),
                            path(paint, 0x80ffffff), ("composite_mask_end", ()),
                            path(paint, 0x8060c020), ("clip_group_pop", None)))
                        if kind == "nested":
                            operations.extend((("clip_group_pop", None), ("composite_pop", None)))
                        operations.extend((("clip_group_pop", None), ("composite_pop", None)))
                        if kind == "repeated":
                            target = list(operations[target_start:])
                            for phase in range(3):
                                if phase:
                                    operations.extend(target)
                                # A following full-size blend can overwrite the
                                # same scratch dimensions before its next Flush.
                                operations.extend((("composite_push", 3, .7, False, True),
                                    path(paint, (0x90c04080, 0xa040c080, 0x806080c0)[phase]),
                                    ("composite_pop", None)))
                        if kind != "copy_parent":
                            operations.append(("clip_group_pop", None))
                        operations.append(("composite_pop", None))
                        if kind == "mask_build":
                            operations = [("composite_mask_begin", (0, 0, 64, 64), True, 0)] + operations
                            operations.extend((("composite_mask_end", tuple(
                                0.0 if index < 128 else 1.0 for index in range(256))),
                                path(paint, 0xffff8020), ("clip_group_pop", None)))
                        reference = []
                        for operation in operations:
                            reference.append(operation)
                            if (operation[0] == "composite_push" and operation[1] == 0
                                    and not operation[3] and operation[4]):
                                # A transparent source-over sibling preserves the
                                # pixels but selects the independent general route.
                                reference.append(path(clip, 0))
                        for transform in ((1, 0, 0, 1, .25, .5), (0, 1, -1, 0, 63.25, .5),
                                          (-1, 0, 0, 1, 63.25, .5),
                                          (1, .2, .1, 1, -3.25, -4.5)):
                            with self.subTest(dpi=dpi, opacity=opacity, kind=kind, transform=transform):
                                expected = render(reference, transform)
                                actual = render(operations, transform)
                                error = [abs(a-b) for a, b in zip(actual, expected)]
                                # Three overlapping captures can accumulate one
                                # extra UNORM8 step across GPU implementations.
                                limit = 4 if kind == "repeated" else 3
                                self.assertLessEqual(max(error), limit, self.surface.info)
                                self.assertLess(sum(error) / len(error), .25, self.surface.info)
        finally:
            for resource in (clip, outer, paint, dot, wide, full_rect):
                resource.close()

    def test_worker_keeps_live_mask_inputs_with_many_surface_sizes(self):
        cover = self.surface.create_path([
            ("move", -2000, -2000), ("line", 4000, -2000),
            ("line", 4000, 4000), ("line", -2000, 4000), ("close",)])
        def paint(argb):
            return ("path", cover, argb, None, 1, None, None)
        operations = [paint(0x80607080)]
        for phase in range(3):
            for index in range(72):
                left = (index * 17 + phase * 23) % 470 + 4
                top = (index * 11 + phase * 13) % 75 + 4
                width, height = 8 + index, 7 + index % 29
                area = (left, top, left + width, top + height)
                inner = (left + 1, top + 1, left + width - 1, top + height - 1)
                # Keep the raw outer mask live while the inner mask is generated.
                operations += [("composite_mask_begin", area, False, 0),
                    paint((0x40 + index % 160) << 24 | 0xffffff),
                    ("composite_mask_end", ()),
                    ("composite_mask_begin", inner, False, 0), paint(0xa0ffffff),
                    ("composite_mask_end", (0, .15, .9, 1)),
                    ("composite_push", 1 + index % 15, .6, False, True),
                    paint((0x80 + phase * 16) << 24 | ((index + phase * 7) * 0x173965) % 0x1000000),
                    ("composite_pop", None), ("clip_group_pop", None),
                    ("clip_group_pop", None)]
        try:
            for dpi in (96, 192, 96):
                self.surface.resize(600, 140, dpi)
                with self.subTest(dpi=dpi):
                    scene = self.surface.create_scene(600, 140, operations)
                    try:
                        scale = 96 / dpi  # Keep coverage on whole physical pixels.
                        transform = (scale, 0, 0, scale, 0, 0)
                        expected = self._draw_retained_pixels(scene, transform, 600, 140)
                        actual = self._render_sharp_operations(operations, transform, 600, 140)
                        self.assertEqual(actual, expected)
                    finally:
                        scene.close()
        finally:
            cover.close()

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
