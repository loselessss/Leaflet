"""Type3 vector text: original color, glyph holes, transforms, safe fallbacks."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import pymupdf


def type3_pdf(*, variant="vector", mode=0, rotated=False, opacity=1.):
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=180)
        def stream(data):
            xref = document.get_new_xref()
            document.update_object(xref, "<< >>")
            document.update_stream(xref, data)
            return xref
        program = b"600 0 0 0 600 700 d1\n0 0 600 700 re 150 150 300 400 re f*"
        if variant == "colored":
            program = b"600 0 d0 1 0 0 rg 0 0 600 700 re f"
        elif variant == "multiple":
            program = b"600 0 0 0 600 700 d1 0 0 400 700 re f 200 0 400 700 re f"
        elif variant == "stroke":
            program = b"600 0 0 0 600 700 d1 20 w 0 0 600 700 re S"
        elif variant == "clip":
            program = b"600 0 0 0 600 700 d1 0 0 500 500 re W n 0 0 600 700 re f"
        elif variant == "bitmap":
            program = (b"600 0 0 0 600 700 d1 600 0 0 700 0 0 cm "
                       b"BI /W 1 /H 1 /BPC 1 /IM true ID \x00 EI")
        glyph = stream(program)
        blank = stream(b"600 0 0 0 600 700 d1")
        font = document.get_new_xref()
        document.update_object(font, f"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 600 700] "
            f"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << /A {glyph} 0 R /B {blank} 0 R >> "
            "/Encoding << /Type /Encoding /Differences [65 /A /B] >> "
            "/FirstChar 65 /LastChar 66 /Widths [600 600] /Resources << >> >>")
        resources = int(document.xref_get_key(page.xref, "Resources")[1].split()[0])
        document.update_object(resources, f"<< /Font << /T3 {font} 0 R >> "
            f"/ExtGState << /Fade << /ca {opacity} /CA {opacity} >> >> >>")
        matrix = "0.85 0.2 -0.15 0.9 25 45" if rotated else "1 0 0 1 25 45"
        contents = (f"q /Fade gs 0.1 0.35 0.7 rg BT /T3 70 Tf {mode} Tr {matrix} Tm (ABA) Tj ET "
                    + ("0.7 0.2 0.1 rg 0 0 240 180 re f " if mode >= 4 else "") + "Q")
        page.set_contents(stream(contents.encode()))
        return document.tobytes()


class Type3CompilerTests(unittest.TestCase):
    def test_simple_masked_glyph_is_vector_at_every_zoom(self):
        from pdfeditor.mupdf_path import compile_page
        for rotated in (False, True):
            with self.subTest(rotated=rotated), pymupdf.open(
                    stream=type3_pdf(rotated=rotated), filetype="pdf") as document:
                packets = []
                for scale in (1., 8., 32.):
                    scene = compile_page(document[0], scale)
                    self.assertEqual(scene.image_bytes, 0)
                    self.assertNotIn("text-raster-fallback", scene.features)
                    self.assertGreater(scene.command_count, 0)
                    packets.append(scene.to_bytes())
                self.assertEqual(packets[0], packets[1])
                self.assertEqual(packets[0], packets[2])

    def test_complex_glyphs_execute_without_text_raster(self):
        from pdfeditor.rust_scene_compiler import compile_vector_page
        for variant in ("colored", "multiple", "clip", "bitmap"):
            with self.subTest(variant=variant), pymupdf.open(
                    stream=type3_pdf(variant=variant), filetype="pdf") as document:
                scene = compile_vector_page(document[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertNotIn("text-raster-fallback", scene.features)

    def test_type3_stroke_and_clip_text_keep_existing_semantics(self):
        from pdfeditor.rust_scene_compiler import compile_vector_page
        for mode in (1, 4, 5, 6):
            with self.subTest(mode=mode), pymupdf.open(
                    stream=type3_pdf(mode=mode), filetype="pdf") as document:
                scene = compile_vector_page(document[0])
                self.assertTrue(scene.supported, scene.reason)
                # MuPDF can expand Type3 directly before text capture. Text
                # rendering modes must retain that existing behavior as well.
                self.assertGreater(scene.command_count, 0)

    def test_independent_worker_uses_same_vector_result(self):
        from pdfeditor.rust_scene_compiler import compile_vector_page
        from pdfeditor.scene_worker_result import load
        from tests.test_native_scene_worker import native_command
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "input.pdf", Path(directory) / "output.scene"
            source.write_bytes(type3_pdf(rotated=True))
            with pymupdf.open(source) as document:
                expected = compile_vector_page(document[0])
            subprocess.run(native_command() + [str(source), str(output)], check=True,
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with output.open("rb") as stream:
                actual = load(stream)
            self.assertTrue(actual.supported, actual.reason)
            self.assertEqual(actual, expected)
            self.assertNotIn("text-raster-fallback", actual.features)


@unittest.skipUnless(os.name == "nt", "Windows renderer")
class Type3PixelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_vector_glyph_keeps_color_hole_and_transformed_position(self):
        import ctypes
        import numpy as np
        from pdfeditor.d2d_backend import D2DSurface
        from pdfeditor.rust_scene_compiler import compile_vector_page
        from tests.benchmark_gpu_pipeline import render_sample
        user32 = ctypes.WinDLL("user32")
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32, *([ctypes.c_int] * 4), *([ctypes.c_void_p] * 4)]
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        hwnd = user32.CreateWindowExW(0, "STATIC", "Type3 test", 0, 0, 0, 480, 360,
                                      None, None, None, None)
        surface = D2DSurface(hwnd, 480, 360)
        try:
            cases = [(0, False, 1.), (0, True, 1.), (1, True, 1.),
                     (4, False, 1.), (5, True, 1.), (6, False, 1.), (0, True, .4)]
            for mode, rotated, opacity in cases:
                with self.subTest(mode=mode, rotated=rotated, opacity=opacity), pymupdf.open(
                        stream=type3_pdf(rotated=rotated, mode=mode, opacity=opacity), filetype="pdf") as document:
                    page = document[0]
                    scene = compile_vector_page(page)
                    self.assertTrue(scene.supported, scene.reason)
                    self.assertNotIn("text-raster-fallback", scene.features)
                    retained = surface.create_rust_scene(scene, 240., 180.)
                    try:
                        frame = render_sample(surface, retained, (2., 0., 0., 2., 0., 0.),
                                              480, 360, "completed", .001)[3]
                    finally:
                        retained.close()
                    actual = np.frombuffer(frame, dtype=np.uint8).reshape(360, 480, 4)[:, :, :3][:, :, ::-1]
                    expected = np.frombuffer(page.get_pixmap(matrix=pymupdf.Matrix(2, 2),
                        alpha=False).samples, dtype=np.uint8).reshape(360, 480, 3)
                    # Compare stable interiors, including glyph holes. Font
                    # hinting/antialiasing can differ only near contour edges.
                    stable = np.ones((356, 476), dtype=bool)
                    center = expected[2:-2, 2:-2]
                    for dy in range(5):
                        for dx in range(5):
                            stable &= (expected[dy:dy+356, dx:dx+476] == center).all(axis=2)
                    self.assertGreater(np.count_nonzero(stable & (center < 240).any(axis=2)), 500)
                    difference = np.abs(actual[2:-2, 2:-2].astype(int) - center.astype(int))
                    self.assertLessEqual(difference[stable].max(), 2)
        finally:
            surface.close()
            user32.DestroyWindow(hwnd)
