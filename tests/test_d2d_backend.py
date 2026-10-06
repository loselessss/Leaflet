import ctypes
import itertools
import math
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pdfeditor.d2d_backend import (ABI_VERSION, D2DSurface, _NativeInfo,
                                  _SceneCommand, probe_d2d_backend)


def pdf_component_blend(mode, backdrop, source):
    """Independent PDF SetLum/SetSat reference, in unpremultiplied RGB."""
    def lum(color):
        return sum(c * w for c, w in zip(color, (.3, .59, .11)))

    def set_lum(color, target):
        delta = target - lum(color)
        result = [c + delta for c in color]
        low, high = min(result), max(result)
        if low < 0:
            result = [target + (c - target) * target / (target - low)
                      for c in result]
        if high > 1:
            result = [target + (c - target) * (1 - target) / (high - target)
                      for c in result]
        return result

    def set_sat(color, target):
        low, high = min(color), max(color)
        return ([(c - low) * target / (high - low) for c in color]
                if high > low else [0, 0, 0])

    if mode == 12:
        return set_lum(set_sat(source, max(backdrop) - min(backdrop)), lum(backdrop))
    if mode == 13:
        return set_lum(set_sat(backdrop, max(source) - min(source)), lum(backdrop))
    if mode == 14:
        return set_lum(source, lum(backdrop))
    if mode == 15:
        return set_lum(backdrop, lum(source))
    raise ValueError(mode)


class D2DBackendTests(unittest.TestCase):
    def test_native_structure_has_stable_abi_layout(self):
        self.assertEqual(ABI_VERSION, 20)
        self.assertEqual(_NativeInfo.adapter_name.offset, 20)
        if os.name == "nt":
            self.assertEqual(ctypes.sizeof(_NativeInfo), 276)
            self.assertEqual(_SceneCommand.data.offset, 96)
            self.assertEqual(ctypes.sizeof(_SceneCommand), 112)

    def test_missing_library_is_a_safe_fallback(self):
        with patch("pdfeditor.d2d_backend.os.name", "nt"):
            result = probe_d2d_backend(Path("missing-spdf-renderer.dll"))
        self.assertFalse(result.available)
        self.assertEqual(result.reason, "native renderer is not built")

    @unittest.skipUnless(os.name == "nt", "Direct2D is Windows-only")
    def test_built_renderer_creates_d2d_and_directwrite_devices(self):
        library = Path(__file__).resolve().parents[1] / "native" / "bin" / \
            "spdf_d2d_renderer.dll"
        if not library.is_file():
            self.skipTest("native renderer is not built")
        result = probe_d2d_backend(library)
        self.assertTrue(result.available, result)
        self.assertIn(result.driver, ("hardware", "warp"))
        self.assertGreaterEqual(result.feature_level, 0xA000)
        self.assertTrue(result.adapter_name)

    @unittest.skipUnless(os.name == "nt", "Direct2D is Windows-only")
    def test_vector_edges_use_grayscale_antialiasing(self):
        library = Path(__file__).resolve().parents[1] / "native" / "bin" / \
            "spdf_d2d_renderer.dll"
        if not library.is_file():
            self.skipTest("native renderer is not built")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.DestroyWindow.restype = ctypes.c_int
        hwnd = user32.CreateWindowExW(
            0, "STATIC", "sPDF D2D AA test", 0, 0, 0, 64, 64,
            None, None, None, None)
        self.assertTrue(hwnd, ctypes.get_last_error())
        try:
            with D2DSurface(hwnd, 64, 64, path=library) as surface:
                path = surface.create_path([
                    ("move", 8.2, 8.2), ("line", 55.7, 17.4),
                    ("line", 13.1, 55.6), ("close",)])
                try:
                    surface.begin_frame(0x00000000)
                    surface.fill_path(path, 0xffffffff)
                    transparent = surface.read_pixels_bgra(64, 64)
                    surface.end_frame()
                    alpha = transparent[3::4]
                    self.assertTrue(any(0 < value < 255 for value in alpha))

                    surface.begin_frame(0xffffffff)
                    surface.fill_path(path, 0xff000000)
                    opaque = surface.read_pixels_bgra(64, 64)
                    surface.end_frame()
                    pixels = [opaque[i:i + 4] for i in range(0, len(opaque), 4)]
                    self.assertTrue(any(
                        bgra[3] == 255 and 0 < bgra[0] < 255 and
                        bgra[0] == bgra[1] == bgra[2]
                        for bgra in pixels))
                finally:
                    path.close()
        finally:
            user32.DestroyWindow(hwnd)

    @unittest.skipUnless(os.name == "nt", "Direct2D is Windows-only")
    def test_retained_scene_replays_with_page_transform(self):
        library = Path(__file__).resolve().parents[1] / "native" / "bin" / \
            "spdf_d2d_renderer.dll"
        if not library.is_file():
            self.skipTest("native renderer is not built")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.DestroyWindow.restype = ctypes.c_int
        hwnd = user32.CreateWindowExW(
            0, "STATIC", "sPDF retained scene test", 0, 0, 0, 32, 32,
            None, None, None, None)
        self.assertTrue(hwnd, ctypes.get_last_error())
        try:
            with D2DSurface(hwnd, 32, 32, path=library) as surface:
                path = surface.create_path([
                    ("move", 0, 0), ("line", 8, 0),
                    ("line", 8, 8), ("line", 0, 8), ("close",)])
                scene = surface.create_scene(32, 32, (
                    ("rect_clip_push", None, (1, 0, 0, 1, 2, 3),
                     (0, 0, 4, 8)),
                    ("path", path, 0xffff0000, None, 1.0,
                     (1, 0, 0, 1, 2, 3), None),
                    ("rect_clip_pop", None)))
                path.close()
                surface.begin_frame(0xff000000)
                surface.draw_scene(scene, (1, 0, 0, 1, 4, 5))
                pixels = surface.read_pixels_bgra(32, 32)
                surface.end_frame()
                inside = pixels[(10 * 32 + 8) * 4:(10 * 32 + 8) * 4 + 4]
                outside = pixels[(10 * 32 + 12) * 4:(10 * 32 + 12) * 4 + 4]
                self.assertEqual(inside, bytes((0, 0, 255, 255)))
                self.assertEqual(outside, bytes((255, 255, 255, 255)))
                # Padding with transparent operations exercises the bounded
                # complex-scene cache while retaining an uncached reference.
                path = surface.create_path([
                    ("move", 4.2, 4.2), ("line", 11.7, 4.2),
                    ("line", 11.7, 11.7), ("line", 4.2, 11.7), ("close",)])
                operations = (
                    ("composite_mask_begin", (4, 4, 12, 12), False, 0),
                    ("path", path, 0xffffffff, None, 1.0, None, None),
                    ("composite_mask_end", ()),
                    ("path", path, 0xffff0000, None, 1.0, None, None),
                    ("clip_group_pop", None))
                reference = surface.create_scene(32, 32, operations)
                cached = surface.create_scene(32, 32, operations + (
                    ("path", path, 0x00000000, None, 1.0, None, None),) * 256)
                for dpi in (96, 144):
                    surface.resize(32, 32, dpi)
                    for scale, dx, dy in ((1, 0, 0), (1, -4, -2),
                                          (1, .25, .5), (1, -3.75, -1.5),
                                          (1.25, 3, 5), (1, 0, 0)):
                        results = []
                        for candidate in (reference, cached):
                            surface.begin_frame(0xff0000ff)
                            surface.draw_scene(candidate, (scale, 0, 0, scale, dx, dy))
                            results.append(surface.read_pixels_bgra(32, 32))
                            surface.end_frame()
                        differences = [abs(a - b) for a, b in zip(*results)]
                        if dpi == 96:
                            self.assertEqual(results[0], results[1], (dpi, scale, dx, dy))
                        else:
                            # Fractional-DIP target origins can alter coverage
                            # rounding at a handful of mask edge pixels.
                            self.assertLessEqual(max(differences), 16)
                            self.assertLess(sum(differences) / len(differences), .25)
        finally:
            user32.DestroyWindow(hwnd)

    @unittest.skipUnless(os.name == "nt", "Direct2D is Windows-only")
    def test_mask_transfer_table_modulates_layer_alpha(self):
        library = Path(__file__).resolve().parents[1] / "native" / "bin" / \
            "spdf_d2d_renderer.dll"
        if not library.is_file():
            self.skipTest("native renderer is not built")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.DestroyWindow.restype = ctypes.c_int
        hwnd = user32.CreateWindowExW(
            0, "STATIC", "sPDF D2D mask transfer test", 0, 0, 0, 32, 32,
            None, None, None, None)
        self.assertTrue(hwnd, ctypes.get_last_error())
        try:
            with D2DSurface(hwnd, 32, 32, path=library) as surface:
                inverse = tuple(1.0 - index / 255.0 for index in range(256))
                surface.begin_frame(0xff0000ff)
                surface.begin_mask((0, 0, 32, 32), False, 0)
                surface.fill_rect(0, 0, 32, 32, 0xffffffff)
                surface.end_mask(inverse)
                surface.fill_rect(0, 0, 32, 32, 0xffff0000)
                surface.pop_clip()
                pixels = surface.read_pixels_bgra(32, 32)
                surface.end_frame()
                center = pixels[(16 * 32 + 16) * 4:(16 * 32 + 16) * 4 + 4]
                self.assertEqual(center, bytes((255, 0, 0, 255)))

                path = surface.create_path([
                    ("move", 4, 4), ("line", 12, 4),
                    ("line", 12, 12), ("line", 4, 12), ("close",)])
                retained = surface.create_scene(32, 32, (
                    ("composite_mask_begin", (4, 4, 12, 12), False, 0),
                    ("path", path, 0xffffffff, None, 1.0, None, None),
                    ("composite_mask_end", ()),
                    ("path", path, 0xffff0000, None, 1.0, None, None),
                    ("clip_group_pop", None)))
                surface.begin_frame(0xff0000ff)
                surface.draw_scene(retained, (1.25, 0, 0, 1.25, 3, 5))
                pixels = surface.read_pixels_bgra(32, 32)
                surface.end_frame()
                center = pixels[(12 * 32 + 10) * 4:(12 * 32 + 10) * 4 + 4]
                outside = pixels[(6 * 32 + 4) * 4:(6 * 32 + 4) * 4 + 4]
                self.assertEqual(center, bytes((0, 0, 255, 255)))
                self.assertEqual(outside, bytes((255, 255, 255, 255)))
        finally:
            user32.DestroyWindow(hwnd)

    @unittest.skipUnless(os.name == "nt", "Direct2D is Windows-only")
    def test_built_renderer_presents_and_resizes_hidden_hwnd(self):
        library = Path(__file__).resolve().parents[1] / "native" / "bin" / \
            "spdf_d2d_renderer.dll"
        if not library.is_file():
            self.skipTest("native renderer is not built")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.DestroyWindow.restype = ctypes.c_int
        hwnd = user32.CreateWindowExW(
            0, "STATIC", "sPDF D2D test", 0, 0, 0, 64, 64,
            None, None, None, None)
        self.assertTrue(hwnd, ctypes.get_last_error())
        try:
            with D2DSurface(hwnd, 64, 64, path=library) as surface:
                surface.clear(0xff1a73e8)
                pixels = bytes((
                    0x00, 0x00, 0xff, 0xff, 0x00, 0xff, 0x00, 0xff,
                    0xff, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff))
                bitmap = surface.create_bitmap_bgra(pixels, 2, 2)
                # Magnified continuous-tone images should gain intermediate
                # colors instead of four large nearest-neighbor blocks.
                color_counts = []
                for interpolate in (False, True):
                    surface.begin_frame()
                    surface.draw_bitmap(bitmap, 0, 0, 64, 64,
                                        interpolate=interpolate)
                    rendered = surface.read_pixels_bgra(64, 64)
                    color_counts.append(len({rendered[i:i + 4]
                                             for i in range(0, len(rendered), 4)}))
                    surface.end_frame()
                self.assertEqual(color_counts[0], 4)
                self.assertGreater(color_counts[1], 100)
                # The native bitmap owns its upload after this function
                # returns, including for mutable input containing NUL bytes.
                mutable = bytearray((0, 0, 255, 255)) * 4
                uploaded = surface.create_bitmap_bgra(mutable, 2, 2)
                mutable[:] = b"\0" * len(mutable)
                surface.begin_frame()
                surface.draw_bitmap(uploaded, 0, 0, 64, 64)
                retained = surface.read_pixels_bgra(64, 64)
                surface.end_frame()
                self.assertEqual(retained[(32 * 64 + 32) * 4:][:4],
                                 bytes((0, 0, 255, 255)))
                uploaded.close()
                path = surface.create_path([
                    ("move", 6, 6), ("line", 58, 6),
                    ("line", 58, 58), ("line", 6, 58), ("close",)])
                group = surface.create_geometry_group([
                    (path, (0.5, 0, 0, 0.5, 4, 4)),
                    (path, (0.25, 0, 0, 0.25, 40, 40)),
                ])
                stroke_style = surface.create_stroke_style(
                    (1, 1, 1, 2, 10.0, 0.5, (1.5, 0.75)))
                stroked_path = surface.create_stroked_path(
                    path, 4.0, stroke_style)
                surface.begin_frame(0xff202020)
                surface.draw_bitmap(bitmap, 8, 8, 56, 56)
                surface.set_transform(1, 0, 0, 1, 0, 0)
                surface.fill_rect(4, 4, 20, 12, 0x600078d7)
                surface.stroke_rect(2, 2, 62, 62, 0xff00a05a, 1.0)
                surface.fill_path(path, 0x600078d7)
                surface.stroke_path(path, 0xff00a05a, 2.0)
                surface.fill_linear_gradient(
                    path, (6, 6), (58, 58),
                    ((0.0, 0xffff0000), (1.0, 0xff0000ff)))
                surface.stroke_path(path, 0xffff8000, 4.0, stroke_style)
                surface.push_clip_path(path)
                surface.push_clip_path(stroked_path)
                surface.push_clip_path(group)
                surface.push_opacity_layer(0.65)
                surface.fill_path(group, 0x800000ff)
                surface.pop_layer()
                surface.pop_clip()
                surface.pop_clip()
                surface.pop_clip()
                surface.set_transform(1, 0, 0, 1, 0, 0)
                surface.begin_mask((0, 0, 64, 64), True, 0xff000000)
                surface.fill_rect(8, 8, 56, 56, 0xffffffff)
                surface.end_mask()
                surface.fill_rect(0, 0, 64, 64, 0xffff0000)
                surface.pop_clip()
                surface.end_frame()
                # Verify all supported PDF blend modes in premultiplied pixels,
                # including a translucent backdrop and separate group opacity.
                def blend_value(mode, backdrop, source):
                    if mode == 1:
                        return backdrop * source
                    if mode == 2:
                        return backdrop + source - backdrop * source
                    if mode == 3:
                        return (2 * backdrop * source if backdrop <= .5 else
                                1 - 2 * (1 - backdrop) * (1 - source))
                    if mode == 4:
                        return min(backdrop, source)
                    if mode == 5:
                        return max(backdrop, source)
                    if mode == 6:
                        return min(1, backdrop / (1 - source))
                    if mode == 7:
                        return 1 - min(1, (1 - backdrop) / source)
                    if mode == 8:
                        return (2 * backdrop * source if source <= .5 else
                                1 - 2 * (1 - backdrop) * (1 - source))
                    if mode == 9:
                        if source <= .5:
                            return backdrop - (1 - 2 * source) * backdrop * (1 - backdrop)
                        curve = (((16 * backdrop - 12) * backdrop + 4) * backdrop
                                 if backdrop <= .25 else math.sqrt(backdrop))
                        return backdrop + (2 * source - 1) * (curve - backdrop)
                    if mode == 10:
                        return abs(backdrop - source)
                    return backdrop + source - 2 * backdrop * source

                for mode in range(1, 12):
                    with self.subTest(blend_mode=mode):
                        surface.begin_frame(0xffffffff)
                        surface.begin_composite_group(0, 1)
                        surface.fill_rect(0, 0, 64, 64, 0x804080c0)
                        surface.begin_composite_group(mode, .6)
                        surface.fill_rect(8, 8, 56, 56, 0xc0c04080)
                        surface.end_composite_group()
                        pixels = surface.read_pixels_bgra(64, 64)
                        offset = (32 * 64 + 32) * 4
                        actual = tuple(pixels[offset:offset + 4])
                        ad, af = 128 / 255, 192 / 255 * .6
                        expected = []
                        for cb, cf in zip((192, 128, 64), (128, 64, 192)):
                            cb, cf = cb / 255, cf / 255
                            expected.append(round(255 * (
                                blend_value(mode, cb, cf) * ad * af +
                                cf * af * (1 - ad) + cb * ad * (1 - af))))
                        expected.append(round(255 * (af + ad * (1 - af))))
                        for value, target in zip(actual, expected):
                            self.assertLessEqual(abs(value - target), 4,
                                (mode, actual, expected))
                        # Outside the source, preserve the existing backdrop.
                        self.assertEqual(tuple(pixels[:4]), (96, 64, 32, 128))
                        surface.end_composite_group()
                        surface.end_frame()
                # Nonseparable modes combine RGB components, not independent
                # channels. Exercise all hue sectors, achromatic inputs, gamut
                # clipping, transparent inputs, and group opacity separately.
                color_pairs = (
                    (0x4080c0, 0xc04080), (0xff0000, 0x00ff00),
                    (0x00ff00, 0x0000ff), (0x0000ff, 0xff0000),
                    (0xffff00, 0x00ffff), (0x00ffff, 0xff00ff),
                    (0xff00ff, 0xffff00), (0x808080, 0xc08020),
                    (0x2040c0, 0x808080), (0x000000, 0xffffff),
                    (0xffffff, 0x000000), (0x808080, 0x404040))
                for mode in range(12, 16):
                    for backdrop, source in color_pairs:
                        for ab, af, opacity in ((255, 255, 1), (128, 192, .6),
                                                (0, 255, 1), (255, 0, 1)):
                            with self.subTest(component_mode=mode, backdrop=backdrop,
                                              source=source, alpha=(ab, af, opacity)):
                                surface.begin_frame()
                                surface.begin_composite_group(0, 1)
                                surface.fill_rect(0, 0, 64, 64, (ab << 24) | backdrop)
                                surface.begin_composite_group(mode, opacity)
                                surface.fill_rect(8, 8, 56, 56, (af << 24) | source)
                                surface.end_composite_group()
                                pixels = surface.read_pixels_bgra(64, 64)
                                offset = (32 * 64 + 32) * 4
                                actual = tuple(pixels[offset:offset + 4])
                                cb = [((backdrop >> shift) & 255) / 255
                                      for shift in (16, 8, 0)]
                                cf = [((source >> shift) & 255) / 255
                                      for shift in (16, 8, 0)]
                                mixed = pdf_component_blend(mode, cb, cf)
                                ad, source_alpha = ab / 255, af / 255 * opacity
                                expected_rgb = [round(255 * (
                                    b * ad * source_alpha + s * source_alpha * (1 - ad) +
                                    d * ad * (1 - source_alpha)))
                                    for b, s, d in zip(mixed, cf, cb)]
                                expected = list(reversed(expected_rgb)) + [
                                    round(255 * (source_alpha + ad * (1 - source_alpha)))]
                                self.assertTrue(all(abs(a - b) <= 4 for a, b in
                                    zip(actual, expected)), (actual, expected))
                                surface.end_composite_group()
                                surface.end_frame()
                # End-to-end: parse actual PDF blend groups, replay the native
                # scene, and compare interior pixels with MuPDF's CPU render.
                import pymupdf
                from pdfeditor.gpu_raster import (
                    ClipPush, ClipPop, GroupPush, GroupPop, VectorPath, VectorImage,
                    MaskBegin, MaskEnd,
                    vector_page_from_pymupdf)
                from tests.test_gpu_raster import (
                    isolated_group_pdf_bytes, blended_mask_pdf_bytes,
                    nonisolated_masked_image_pdf_bytes, nested_knockout_clip_pdf_bytes,
                    nonisolated_nested_blend_pdf_bytes,
                    empty_glyph_pdf_bytes)
                pdf_cases = [("%s clipped=%s" % (name, clipped),
                              isolated_group_pdf_bytes(name, background=True, clip=clipped))
                             for name, clipped in itertools.product(("Multiply", "Screen", "Overlay", "Darken", "Lighten",
                             "ColorDodge", "ColorBurn", "HardLight", "SoftLight",
                             "Difference", "Exclusion", "Hue", "Saturation",
                             "Color", "Luminosity"), (False, True))]
                for name, luminosity, mask_blend, color in itertools.product(
                        ("Multiply", "SoftLight", "Hue"), (False, True), (False, True),
                        ((.5, .5, .5), (1, 0, 0), (0, 1, 0), (0, 0, 1))):
                    pdf_cases.append(("%s mask=%s inner_blend=%s color=%s" %
                        (name, luminosity, mask_blend, color), blended_mask_pdf_bytes(
                            name, luminosity, mask_blend, color)))
                pdf_cases.append(("bitmap luminosity mask", blended_mask_pdf_bytes(image=True)))
                for clipped in (False, True):
                    with pymupdf.open(stream=isolated_group_pdf_bytes(
                            background=True, clip=clipped), filetype="pdf") as pdf:
                        pdf.xref_set_key(5, "Group/I", "false")
                        pdf_cases.append((f"nonisolated normal clipped={clipped}", pdf.tobytes()))
                for mode, knockout in itertools.product(
                        ("Normal", "Multiply", "SoftLight"), (False, True)):
                    pdf_cases.append((f"masked nonisolated {mode} knockout={knockout}",
                                      nonisolated_masked_image_pdf_bytes(mode, knockout)))
                for opacity, clipped, blend in itertools.product(
                        (0, .3, .7, 1), (False, True), ("Multiply", "Screen", "SoftLight")):
                    pdf_cases.append((f"nonisolated nested {opacity} {clipped} {blend}",
                        nonisolated_nested_blend_pdf_bytes(opacity, clipped, blend)))
                pdf_cases.append(("nested knockout clip", nested_knockout_clip_pdf_bytes()))
                for mode in (0, 1, 5, 7):
                    pdf_cases.append((f"empty glyph mode={mode}", empty_glyph_pdf_bytes(mode)))
                for name, pdf_bytes in pdf_cases:
                    with self.subTest(pdf_blend=name), pymupdf.open(
                            stream=pdf_bytes, filetype="pdf") as pdf:
                        scene = vector_page_from_pymupdf(pdf[0])
                        self.assertTrue(scene.supported, scene.reason)
                        self.assertNotIn("cpu-island", scene.features)
                        reference = pdf[0].get_pixmap(matrix=pymupdf.Matrix(.2, .2))
                        surface.begin_frame(0xffffffff)
                        frame_paths = []
                        for item in scene.drawables:
                            if isinstance(item, GroupPush):
                                surface.begin_composite_group(
                                    item.blend_mode, item.opacity, item.knockout, item.isolated)
                            elif isinstance(item, GroupPop):
                                surface.end_composite_group()
                            elif isinstance(item, ClipPop):
                                surface.end_clip_group()
                            elif isinstance(item, MaskBegin):
                                surface.set_transform(.2, 0, 0, .2, 0, 0)
                                surface.begin_composite_mask(
                                    item.area, item.luminosity, item.background_argb)
                            elif isinstance(item, MaskEnd):
                                surface.set_transform(1, 0, 0, 1, 0, 0)
                                surface.end_composite_mask()
                            elif isinstance(item, VectorImage):
                                surface.set_transform(*(value * .2 for value in item.transform))
                                bitmap_resource = surface.create_bitmap_bgra(
                                    item.pixels, item.width, item.height, item.stride)
                                frame_paths.append(bitmap_resource)
                                surface.draw_bitmap(bitmap_resource, 0, 0, 1, 1, item.opacity,
                                                    interpolate=item.interpolate)
                            elif isinstance(item, (VectorPath, ClipPush)):
                                matrix = item.transform or (1, 0, 0, 1, 0, 0)
                                surface.set_transform(*(value * .2 for value in matrix))
                                geometry = surface.create_path(
                                    item.commands, even_odd=item.even_odd)
                                frame_paths.append(geometry)
                                if isinstance(item, ClipPush):
                                    surface.begin_clip_group(geometry)
                                else:
                                    if item.fill_argb is not None:
                                        surface.fill_path(geometry, item.fill_argb)
                                    if item.stroke_argb is not None:
                                        surface.stroke_path(geometry, item.stroke_argb,
                                                            item.stroke_width)
                        actual = surface.read_pixels_bgra(64, 64)
                        surface.end_frame()
                        for geometry in frame_paths:
                            geometry.close()
                        for x, y in ((2, 2), (10, 20), (25, 25), (50, 10),
                                     (6, 25), (20, 20), (35, 30), (50, 40)):
                            offset = (y * 64 + x) * 4
                            native_rgb = tuple(reversed(actual[offset:offset + 3]))
                            reference_rgb = reference.pixel(x, y)
                            self.assertTrue(all(abs(a - b) <= 3 for a, b in
                                zip(native_rgb, reference_rgb)),
                                (name, (x, y), native_rgb, reference_rgb))
                # Fractional clip edges must interpolate once, even with
                # translucent backdrops and nested captures at non-default DPI.
                fractional = surface.create_path([
                    ("move", 10.25, 9.75), ("line", 43.75, 9.75),
                    ("line", 43.75, 51.25), ("line", 10.25, 51.25), ("close",)])
                for dpi in (96.0, 120.0):
                    surface.resize(80, 80, dpi)
                    for luminosity, nesting in itertools.product((False, True), (1, 2)):
                        with self.subTest(mask_dpi=dpi, luminosity=luminosity, nesting=nesting):
                            surface.begin_frame(0xff4080c0)
                            for _ in range(nesting):
                                surface.begin_composite_mask((8, 8, 48, 48), luminosity,
                                                             0xff000000 if luminosity else 0)
                                surface.fill_rect(0, 0, 64, 64, 0x80ffffff)
                                surface.end_composite_mask()
                            surface.begin_composite_group(9, .6)
                            surface.fill_rect(0, 0, 64, 64, 0xc0c04080)
                            surface.end_composite_group()
                            for _ in range(nesting):
                                surface.end_clip_group()
                            masked = surface.read_pixels_bgra(80, 80)
                            surface.end_frame()
                            outside = (3 * 80 + 3) * 4
                            self.assertEqual(masked[outside:outside + 4], bytes((192, 128, 64, 255)))
                            inside = (24 * 80 + 24) * 4
                            weight = (128 / 255) ** nesting
                            af = 192 / 255 * .6
                            expected = [round(255 * (cb / 255 + weight * af *
                                (blend_value(9, cb / 255, cf / 255) - cb / 255)))
                                for cb, cf in zip((192, 128, 64), (128, 64, 192))]
                            self.assertTrue(all(abs(a - b) <= 4 for a, b in
                                zip(masked[inside:inside + 3], expected)),
                                (masked[inside:inside + 4], expected))
                    for transform in ((1, 0, 0, 1, 0, 0), (0, 1, -1, 0, 64, 0)):
                        with self.subTest(clip_dpi=dpi, transform=transform):
                            surface.begin_frame()
                            surface.begin_composite_group(0, 1)
                            surface.set_transform(*transform)
                            surface.push_clip_path(fractional)
                            surface.set_transform(1, 0, 0, 1, 0, 0)
                            surface.fill_rect(0, 0, 80, 80, 0xffffffff)
                            surface.pop_clip()
                            coverage = surface.read_pixels_bgra(80, 80)[3::4]
                            self.assertTrue(any(0 < a < 255 for a in coverage))
                            surface.end_composite_group()
                            surface.end_frame()

                            def blended_frame(clip_count):
                                surface.begin_frame()
                                surface.begin_composite_group(0, 1)
                                surface.set_transform(1, 0, 0, 1, 0, 0)
                                surface.fill_rect(0, 0, 80, 80, 0x804080c0)
                                for _ in range(clip_count):
                                    surface.set_transform(*transform)
                                    surface.begin_clip_group(fractional)
                                surface.set_transform(1, 0, 0, 1, 0, 0)
                                surface.fill_rect(0, 0, 80, 80, 0x4080c040)
                                surface.begin_composite_group(9, .6)
                                surface.fill_rect(0, 0, 80, 80, 0xc0c04080)
                                surface.end_composite_group()
                                for _ in range(clip_count):
                                    surface.end_clip_group()
                                result = surface.read_pixels_bgra(80, 80)
                                surface.end_composite_group()
                                surface.end_frame()
                                return result

                            full = blended_frame(0)
                            backdrop = (96, 64, 32, 128)
                            for nesting in (1, 2):
                                actual = blended_frame(nesting)
                                worst = 0
                                worst_pixel = None
                                for pixel, alpha in enumerate(coverage):
                                    weight = (alpha / 255) ** nesting
                                    for channel, base in enumerate(backdrop):
                                        index = pixel * 4 + channel
                                        expected = round(base + (full[index] - base) * weight)
                                        error = abs(actual[index] - expected)
                                        if error > worst:
                                            worst = error
                                            worst_pixel = (pixel % 80, pixel // 80, channel,
                                                           alpha, full[index], actual[index], expected)
                                self.assertLessEqual(worst, 3, (dpi, transform, nesting, worst_pixel))
                fractional.close()
                surface.resize(96, 80, 120.0)
                surface.begin_frame(0xff4080c0)
                surface.begin_composite_group(9, .6)
                surface.fill_rect(8, 8, 56, 56, 0xc0c04080)
                surface.end_composite_group()
                actual = surface.read_pixels_bgra(96, 80)
                # 120 DPI: eight DIPs start at ten physical pixels.
                outside = (20 * 96 + 8) * 4
                self.assertEqual(tuple(actual[outside:outside + 4]), (192, 128, 64, 255))
                inside = (20 * 96 + 12) * 4
                af = 192 / 255 * .6
                expected = [round(255 * (blend_value(9, cb / 255, cf / 255) * af +
                    cb / 255 * (1 - af))) for cb, cf in
                    zip((192, 128, 64), (128, 64, 192))]
                self.assertTrue(all(abs(a - b) <= 3 for a, b in
                    zip(actual[inside:inside + 3], expected)))
                surface.end_frame()
                surface.begin_frame()
                for invalid_mode in (16, 99, -1):
                    with self.subTest(invalid_mode=invalid_mode), self.assertRaises(OSError):
                        surface.begin_composite_group(invalid_mode, 1)
                surface.push_clip_path(path)
                with self.assertRaises(OSError):
                    surface.begin_composite_group(9, 1)
                surface.pop_clip()
                surface.end_frame()
                surface.begin_frame()
                surface.begin_composite_group(9, 1)
                with self.assertRaises(OSError):
                    surface.end_frame()  # Reject and unwind an incomplete capture.
                surface.clear(0xfff7f7f7)
                surface.begin_frame()
                surface.begin_clip_group(path)
                with self.assertRaises(OSError):
                    surface.end_composite_group()  # Wrong capture type must not pop.
                with self.assertRaises(OSError):
                    surface.end_frame()  # Unwind an unfinished clip capture too.
                surface.clear(0xfff7f7f7)
                surface.begin_frame()
                surface.begin_composite_mask((0, 0, 64, 64), False, 0)
                with self.assertRaises(OSError):
                    surface.end_composite_group()
                with self.assertRaises(OSError):
                    surface.end_frame()
                surface.clear(0xfff7f7f7)
                self.assertFalse(surface.closed)
                bitmap.close()
                self.assertTrue(bitmap.closed)
                path.close()
                self.assertTrue(path.closed)
                group.close()
                self.assertTrue(group.closed)
                stroke_style.close()
                self.assertTrue(stroke_style.closed)
                stroked_path.close()
                self.assertTrue(stroked_path.closed)
            self.assertTrue(surface.closed)
        finally:
            user32.DestroyWindow(hwnd)

    @unittest.skipUnless(os.name == "nt", "Direct2D is Windows-only")
    def test_knockout_group_replaces_overlapping_primitives(self):
        library = Path(__file__).resolve().parents[1] / "native" / "bin" / \
            "spdf_d2d_renderer.dll"
        if not library.is_file():
            self.skipTest("native renderer is not built")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.DestroyWindow.restype = ctypes.c_int
        hwnd = user32.CreateWindowExW(
            0, "STATIC", "sPDF D2D test", 0, 0, 0, 32, 32,
            None, None, None, None)
        self.assertTrue(hwnd, ctypes.get_last_error())
        try:
            with D2DSurface(hwnd, 32, 32, path=library) as surface:
                def overlap_pixel(knockout):
                    surface.begin_frame(0xffffffff)
                    surface.begin_composite_group(0, 1, knockout)
                    surface.fill_rect(4, 4, 24, 24, 0x80ff0000)
                    surface.fill_rect(12, 12, 28, 28, 0x800000ff)
                    surface.end_composite_group()
                    pixels = surface.read_pixels_bgra(32, 32)
                    surface.end_frame()
                    offset = (16 * 32 + 16) * 4
                    return tuple(pixels[offset:offset + 4])

                normal = overlap_pixel(False)
                knockout = overlap_pixel(True)
        finally:
            user32.DestroyWindow(hwnd)
        self.assertNotEqual(normal, knockout)
        self.assertLessEqual(abs(knockout[0] - 255), 3)
        self.assertLessEqual(abs(knockout[1] - 127), 4)
        self.assertLessEqual(abs(knockout[2] - 127), 4)
        self.assertEqual(knockout[3], 255)


if __name__ == "__main__":
    unittest.main()
